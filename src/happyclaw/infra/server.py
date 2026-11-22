"""OctopServer — process-level orchestrator."""

from __future__ import annotations

import asyncio
import gzip
import logging
import os
import re
import shutil
import threading
import time
import uuid
from collections.abc import Iterator
from contextlib import suppress
from dataclasses import dataclass
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
from typing import TYPE_CHECKING, Any

from happyclaw.config import OctopConfig, load_config
from happyclaw.infra.setup.wizard_tokens import WizardTokenStore
from happyclaw.infra.utils.paths import PathLayout
from happyclaw.infra.utils.process_resources import ensure_nofile_limit

# Everything below is imported lazily inside the boot phases. Importing the agent
# stack (happyclaw_harness → deepagents → langchain, plus the expert catalogs and the
# scheduler) at module scope costs tens of seconds on slow volumes, and it all
# happens again from scratch during ``start_runtime()`` — which runs *after* the
# socket is bound. Keep this module import cheap so the listener comes up early.
if TYPE_CHECKING:
    from happyclaw.infra.agents.experts.catalog import ExpertCatalog
    from happyclaw.infra.agents.manager import AgentManager
    from happyclaw.infra.agents.plugins.manager import PluginManager
    from happyclaw.infra.agents.subagents.catalog import SubagentCatalog
    from happyclaw.infra.auth.ldap.service import LdapAuthService
    from happyclaw.infra.auth.ldap.throttle import LdapBindThrottle
    from happyclaw.infra.auth.sso.service import SsoService
    from happyclaw.infra.cron.manager import CronManager
    from happyclaw.infra.db.services import SharedServices
    from happyclaw.infra.gateway.gateway import Gateway
    from happyclaw.infra.history.trajectory.service import TrajectoryService
    from happyclaw.infra.proactive.scheduler import ProactiveCareScheduler
    from happyclaw.infra.users.manager import UserManager

logger = logging.getLogger(__name__)

# Default 100 MiB per active log file before size-triggered rollover (in addition to daily).
DEFAULT_LOG_MAX_BYTES = 100 * 1024 * 1024
DEFAULT_LOG_RETENTION_DAYS = 14


class SizeTimedRotatingFileHandler(TimedRotatingFileHandler):
    """Daily rotation with an optional per-file byte cap (whichever triggers first)."""

    def __init__(
        self,
        filename: str | os.PathLike[str],
        *,
        max_bytes: int = 0,
        compress_rotated: bool = True,
        **kwargs: object,
    ) -> None:
        super().__init__(filename, **kwargs)  # type: ignore[arg-type]
        self.max_bytes = max(0, max_bytes)
        self.compress_rotated = compress_rotated

    def shouldRollover(self, record: logging.LogRecord) -> bool:
        if super().shouldRollover(record):
            return True
        if self.max_bytes <= 0:
            return False
        if self.stream is None:
            self.stream = self._open()
        self.stream.flush()
        return self.stream.tell() >= self.max_bytes

    def rotate(self, source: str, dest: str) -> None:
        super().rotate(source, dest)
        if self.compress_rotated:
            # logrotate delaycompress: leave this cycle's dest plain; gzip prior plains.
            delaycompress_rotated_logs(Path(dest).parent, enabled=True, keep=Path(dest))

    def rotation_filename(self, default_name: str) -> str:
        """Place the date before ``.log``, and avoid clobbering an existing backup.

        A second size-triggered roll the same day becomes ``octop.YYYY-MM-DD.log.001``.
        """
        named = super().rotation_filename(default_name)
        if not os.path.exists(named) and not os.path.exists(f"{named}.gz"):
            return named
        index = 1
        while True:
            candidate = f"{named}.{index:03d}"
            if not os.path.exists(candidate) and not os.path.exists(f"{candidate}.gz"):
                return candidate
            index += 1


def _dated_log_namer(default_name: str) -> str:
    """Turn ``octop.log.2026-10-16`` into ``octop.2026-10-16.log``."""
    directory, filename = os.path.split(default_name)
    if "." not in filename:
        return default_name
    base, date = filename.rsplit(".", 1)
    stem, ext = os.path.splitext(base)
    if not ext or not date:
        return default_name
    renamed = f"{stem}.{date}{ext}"
    return os.path.join(directory, renamed) if directory else renamed


# ``octop.log.2026-10-16``, ``octop.log.2026-10-16-001``, and their ``.gz`` forms.
_LEGACY_ROTATED_LOG = re.compile(r"^octop\.log\.(\d{4}-\d{2}-\d{2})(?:-(\d+))?(\.gz)?$")
# New names plus any legacy file a rename could not move.
_ROTATED_LOG_NAME = re.compile(
    r"^octop\.(?:"
    r"\d{4}-\d{2}-\d{2}\.log(?:\.\d+)?"
    r"|"
    r"log\.\d{4}-\d{2}-\d{2}(?:-\d+)?"
    r")(?:\.gz)?$"
)


def _migrate_legacy_rotated_logs(log_dir: Path) -> None:
    """Rename ``octop.log.YYYY-MM-DD`` to ``octop.YYYY-MM-DD.log``."""
    if not log_dir.is_dir():
        return
    for entry in list(log_dir.iterdir()):
        match = _LEGACY_ROTATED_LOG.fullmatch(entry.name)
        if match is None or not entry.is_file():
            continue
        date, index, gz = match.group(1), match.group(2), match.group(3) or ""
        index_part = f".{index}" if index else ""
        dest = log_dir / f"octop.{date}.log{index_part}{gz}"
        if dest.exists():
            continue
        with suppress(OSError):
            entry.rename(dest)


def _iter_rotated_logs(log_dir: Path) -> Iterator[Path]:
    if not log_dir.is_dir():
        return
    for entry in log_dir.iterdir():
        if entry.is_file() and _ROTATED_LOG_NAME.fullmatch(entry.name):
            yield entry


def gzip_rotated_log(path: Path) -> None:
    """Compress a rotated log file to ``{name}.gz`` and remove the plain file."""
    if not path.is_file() or path.suffix == ".gz":
        return
    gz_path = path.with_name(f"{path.name}.gz")
    if gz_path.exists():
        return
    try:
        with path.open("rb") as src, gzip.open(gz_path, "wb", compresslevel=6) as dst:
            shutil.copyfileobj(src, dst)
        path.unlink()
    except OSError:
        with suppress(OSError):
            if gz_path.exists():
                gz_path.unlink()


def _parse_log_compress() -> bool:
    raw = (os.environ.get("OCTOP_LOG_COMPRESS", "1") or "1").strip().lower()
    return raw not in ("0", "false", "no", "off")


def delaycompress_rotated_logs(
    log_dir: Path,
    *,
    enabled: bool,
    keep: Path | None = None,
) -> None:
    """Gzip older rotated plains; leave ``keep`` (or the newest) uncompressed.

    Matches logrotate ``compress`` + ``delaycompress``: postpone compression of the
    previous log file until the next rotation cycle
    (https://github.com/logrotate/logrotate).
    """
    if not enabled or not log_dir.is_dir():
        return
    plains = [entry for entry in _iter_rotated_logs(log_dir) if not entry.name.endswith(".gz")]
    if not plains:
        return
    keep_path = max(plains, key=lambda p: p.stat().st_mtime) if keep is None else keep
    keep_resolved = keep_path.resolve()
    for entry in plains:
        if entry.resolve() == keep_resolved:
            continue
        gzip_rotated_log(entry)


def _parse_log_retention_days() -> int:
    raw = os.environ.get("OCTOP_LOG_RETENTION_DAYS", str(DEFAULT_LOG_RETENTION_DAYS)) or str(
        DEFAULT_LOG_RETENTION_DAYS
    )
    try:
        return int(raw)
    except ValueError:
        return DEFAULT_LOG_RETENTION_DAYS


def _parse_log_max_bytes() -> int:
    raw = os.environ.get("OCTOP_LOG_MAX_BYTES", str(DEFAULT_LOG_MAX_BYTES)) or str(
        DEFAULT_LOG_MAX_BYTES
    )
    try:
        return max(0, int(raw))
    except ValueError:
        return DEFAULT_LOG_MAX_BYTES


class _OctopLogFormatter(logging.Formatter):
    """Process log line, with the active harness agent id when one is in scope."""

    def format(self, record: logging.LogRecord) -> str:
        text = super().format(record)
        agent = getattr(record, "agent", None)
        if not agent:
            from happyclaw_harness.observability.logging import current_log_agent_id

            agent = current_log_agent_id()
        if not agent:
            return text
        return f"{text} [agent={agent}]"


def _build_log_handler(
    log_path: Path,
    retention_days: int,
    *,
    max_bytes: int = DEFAULT_LOG_MAX_BYTES,
    compress_rotated: bool = True,
) -> SizeTimedRotatingFileHandler:
    """Create a daily + size-capped rotating file handler with retention."""
    handler = SizeTimedRotatingFileHandler(
        log_path,
        when="midnight",
        interval=1,
        backupCount=retention_days,
        encoding="utf-8",
        max_bytes=max_bytes,
        compress_rotated=compress_rotated,
    )
    # Rotated files are ``octop.YYYY-MM-DD.log`` (date before the extension).
    handler.suffix = "%Y-%m-%d"
    handler.namer = _dated_log_namer
    handler.setFormatter(_OctopLogFormatter("%(asctime)s %(levelname)-5s %(name)s — %(message)s"))
    return handler


def _purge_stale_logs(log_dir: Path, retention_days: int) -> None:
    """Delete rotated octop log files older than ``retention_days`` (mtime based).

    ``TimedRotatingFileHandler`` only trims by count at rollover time, so a service
    that is offline for a long stretch can accumulate stale files. This purges them
    on startup as a safety net.
    """
    if retention_days <= 0:
        return
    cutoff = time.time() - retention_days * 86400
    for entry in _iter_rotated_logs(log_dir):
        if entry.stat().st_mtime < cutoff:
            with suppress(OSError):
                entry.unlink()


def _attach_log_handler(target: logging.Logger, handler: TimedRotatingFileHandler) -> None:
    """Add ``handler`` to ``target`` only if an equivalent one is not present yet."""
    if not any(
        isinstance(h, TimedRotatingFileHandler) and h.baseFilename == handler.baseFilename
        for h in target.handlers
    ):
        target.addHandler(handler)


@dataclass
class AppRuntime:
    """Live singletons — constructed after boot."""

    agent_registry: AgentManager
    gateway: Gateway
    cron_manager: CronManager
    user_manager: UserManager
    proactive_scheduler: ProactiveCareScheduler
    trajectory_service: TrajectoryService | None = None
    bridge_manager: Any | None = None

    def replace_services(self, services: SharedServices, config: OctopConfig) -> None:
        """Retarget all runtime singletons onto a new SharedServices / config.

        Used when the setup wizard hot-swaps the control-plane DB while empty.
        """
        self.user_manager.replace_services(services)
        self.agent_registry.replace_persistence(services.repos, config)
        self.gateway.replace_repos(services.repos)
        self.cron_manager.replace_repos(services.repos)
        self.proactive_scheduler.replace_persistence(
            config_repo=services.repos.proactive_care_config_repo,
            session_repo=services.repos.session_repo,
            care_push_repo=services.repos.care_push_repo,
            thread_repo=services.repos.thread_repo,
        )
        if self.trajectory_service is not None:
            from happyclaw.infra.history.trajectory.store import TrajectoryStore  # noqa: PLC0415

            self.trajectory_service.replace_store(TrajectoryStore(services.trajectory_event_repo))


class _LazyCatalogProxy:
    """Catalog handle that loads the real one on first attribute use.

    ``AgentManager`` only reads the expert catalog when an agent is created
    from a template, so holding this proxy keeps the catalog import and its
    directory scan off both the listen path and the first-turn path.
    """

    __slots__ = ("_server", "_attr")

    def __init__(self, server: OctopServer, attr: str) -> None:
        self._server = server
        self._attr = attr

    def __getattr__(self, item: str) -> Any:
        return getattr(getattr(self._server, self._attr), item)


class OctopServer:
    def __init__(self, home: Path | None = None) -> None:
        self._home = home or PathLayout.from_env().root
        self.paths = PathLayout(self._home)
        self.config: OctopConfig | None = None
        self.services: SharedServices | None = None
        self.app_runtime: AppRuntime | None = None
        self._expert_catalog: ExpertCatalog | None = None
        self._subagent_catalog: SubagentCatalog | None = None
        self._catalog_lock = threading.Lock()
        self.plugin_manager: PluginManager | None = None
        self.wizard_tokens = WizardTokenStore(ttl_seconds=300)
        self._started = False
        self._started_at: int | None = None
        self._default_agent_task: asyncio.Task[None] | None = None
        self._agent_restore_task: asyncio.Task[None] | None = None
        self.instance_id = uuid.uuid4().hex
        self._serve_background = True
        self._sso_service: SsoService | None = None
        self._ldap_service: LdapAuthService | None = None
        self._ldap_bind_throttle: LdapBindThrottle | None = None
        self._ldap_bind_throttle_services: SharedServices | None = None

    # Backward compat: expose user_manager directly
    @property
    def user_manager(self) -> UserManager | None:
        return self.app_runtime.user_manager if self.app_runtime else None

    @property
    def expert_catalog(self) -> ExpertCatalog:
        """Expert catalog, loaded on first use (import + directory scan ~5–11s)."""
        self.ensure_catalogs()
        assert self._expert_catalog is not None
        return self._expert_catalog

    @property
    def subagent_catalog(self) -> SubagentCatalog:
        self.ensure_catalogs()
        assert self._subagent_catalog is not None
        return self._subagent_catalog

    @property
    def expert_catalog_lazy(self) -> Any:
        """Handle for callers that can defer until the first real lookup."""
        return _LazyCatalogProxy(self, "expert_catalog")

    def ensure_catalogs(self) -> None:
        """Load catalogs once; safe to call from the event loop or a thread."""
        if self._expert_catalog is not None and self._subagent_catalog is not None:
            return
        with self._catalog_lock:
            if self._expert_catalog is None or self._subagent_catalog is None:
                self._load_catalogs()

    @property
    def owner_identity(self) -> Any:
        """The single local user for this installation."""
        if self.services is None:
            from happyclaw.infra.errors import ErrorCode, OctopError  # noqa: PLC0415

            raise OctopError(
                ErrorCode.SINGLE_USER_INIT_FAILED,
                "control-plane database is not available",
                status=503,
            )
        return self.services.owner

    @property
    def sso_service(self) -> SsoService:
        """Process-level SSO service so discovery/JWKS cache survives across requests."""
        from happyclaw.infra.auth.sso.service import SsoService as SsoServiceCls  # noqa: PLC0415

        if self.services is None or self.user_manager is None:
            raise RuntimeError("SSO service requires a started server with user manager")
        if (
            self._sso_service is None
            or getattr(self._sso_service, "_services", None) is not self.services
            or getattr(self._sso_service, "_user_manager", None) is not self.user_manager
        ):
            self._sso_service = SsoServiceCls(self.services, self.user_manager)
        return self._sso_service

    @property
    def ldap_service(self) -> LdapAuthService:
        """Process-level LDAP service, rebound whenever services are swapped."""
        from happyclaw.infra.auth.ldap.service import (
            LdapAuthService as LdapAuthServiceCls,  # noqa: PLC0415
        )

        if self.services is None or self.user_manager is None:
            raise RuntimeError("LDAP service requires a started server with user manager")
        if (
            self._ldap_service is None
            or getattr(self._ldap_service, "_services", None) is not self.services
            or getattr(self._ldap_service, "_user_manager", None) is not self.user_manager
        ):
            self._ldap_service = LdapAuthServiceCls(self.services, self.user_manager)
        return self._ldap_service

    @property
    def ldap_bind_throttle(self) -> LdapBindThrottle:
        """Process-level brute-force backoff for directory binds."""
        from happyclaw.infra.auth.ldap.throttle import LdapBindThrottle as ThrottleCls  # noqa: PLC0415

        if self.services is None:
            raise RuntimeError("LDAP throttle requires a started server")
        if (
            self._ldap_bind_throttle is None
            or self._ldap_bind_throttle_services is not self.services
        ):
            config = self.services.config
            self._ldap_bind_throttle = ThrottleCls(
                max_attempts=config.login_max_attempts,
                window_seconds=60,
                block_seconds=config.login_lockout_seconds,
            )
            self._ldap_bind_throttle_services = self.services
        return self._ldap_bind_throttle

    @property
    def database_bound(self) -> bool:
        """True once the control-plane DB is open and shared services exist."""
        return self.services is not None

    @property
    def runtime_ready(self) -> bool:
        """True once the agent runtime (gateway/cron/agents) is wired."""
        return self.app_runtime is not None

    async def start(self, *, serve_background: bool = True, boot_runtime: bool = True) -> None:
        """Open the DB and build shared services.

        ``boot_runtime=False`` leaves the agent runtime unwired so the caller can
        bind the HTTP listener first and call :meth:`start_runtime` afterwards
        (``octop run`` does exactly that to keep the splash screen short).
        """
        if self._started:
            return
        from happyclaw.infra.utils import startup_timing as _timing  # noqa: PLC0415

        import time  # noqa: PLC0415

        _timing.mark("start.enter")
        self._serve_background = serve_background
        self.paths.ensure_root()
        # fnOS/容器内非 root 用户场景：把用户级 npm 全局 bin 目录（~/.npm-global）
        # 纳入进程 PATH，保证连接器 CLI（wecom-cli / lark-cli）可被检测与调用。
        _preflight_t0 = time.perf_counter()
        # ``ensure_cli_path`` lives in the connectors package, whose import chain
        # (Feishu/WeCom/DingTalk SDKs → aiohttp) costs seconds. Nothing on the
        # pre-listen path needs it; connector CLIs are only spawned later, so it
        # runs in ``_prepare_runtime`` instead.
        _preflight_cli = time.perf_counter()
        from happyclaw.infra.utils.env_file import apply_env_file, env_file_path  # noqa: PLC0415

        apply_env_file(env_file_path(self.paths.root))
        from happyclaw.infra.utils.proxy_env import ensure_loopback_no_proxy  # noqa: PLC0415

        # Local model servers must never be routed through a system proxy.
        ensure_loopback_no_proxy()
        _preflight_env = time.perf_counter()
        self._setup_logging()
        _preflight_log = time.perf_counter()
        # Split the otherwise opaque "process" segment: these three lines make it
        # obvious whether the pre-listen time is interpreter/imports or preflight.
        _timing.emit("preflight.cli_path", (_preflight_cli - _preflight_t0) * 1000.0)
        _timing.emit("preflight.env_file", (_preflight_env - _preflight_cli) * 1000.0)
        _timing.emit("preflight.logging", (_preflight_log - _preflight_env) * 1000.0)
        _timing.emit(
            "preflight.total",
            (_preflight_log - _preflight_t0) * 1000.0,
            since_start_enter_ms=round(_timing.since_mark_ms("start.enter") or 0.0, 1),
        )
        # Logged only now: the file handler does not exist before _setup_logging().
        _timing.emit_process()
        ensure_nofile_limit()
        from happyclaw.infra.backend.grep_safety import install_safe_grep_fallback  # noqa: PLC0415
        from happyclaw.infra.backend.shell_output import install_shell_output_decoding  # noqa: PLC0415
        from happyclaw.infra.utils.google_discovery import (  # noqa: PLC0415
            install_google_discovery_fallback,
        )

        install_safe_grep_fallback()
        install_shell_output_decoding()
        # The bundle drops googleapiclient's offline discovery corpus; wrap
        # build() so Google Drive/Gmail tools fall back to the network.
        install_google_discovery_fallback()
        with _timing.segment("config"):
            from happyclaw.infra.control.mobile.config_probe import (  # noqa: PLC0415
                ensure_mobile_capabilities_probed,
            )

            with _timing.segment("config.load"):
                config = ensure_mobile_capabilities_probed(self.paths.config)
            self.config = config

        import time  # noqa: PLC0415

        self._started_at = int(time.time())

        from happyclaw.infra.db.factory import (  # noqa: PLC0415
            open_database,
            should_defer_control_plane_db,
        )

        if should_defer_control_plane_db(config, self.paths):
            # Deprecated: single-user mode always binds the default SQLite DB at
            # boot. The branch stays empty on purpose so a stale config cannot
            # defer the control plane and block /api/health on first launch.
            logger.info("single-user mode: ignoring deferred control-plane setup")

        with _timing.segment("db"):
            from happyclaw.infra.db.migrate import run_migrations  # noqa: PLC0415

            db = open_database(config, self.paths)
            run_migrations(db)
        with _timing.segment("services"):
            from happyclaw.infra.db.services import build_shared_services  # noqa: PLC0415

            self.services = build_shared_services(db=db, paths=self.paths, config=config)
            from happyclaw.infra.auth.captcha import boot_from_services  # noqa: PLC0415

            boot_from_services(self.services.settings_repo, self.services.secret_repo)
            self._ensure_jwt_secret()
            # Resolve (and create when the DB is empty) the one local owner before
            # serving traffic so every request maps to the same identity.
            self.services.owner.ensure()
        self._started = True
        _timing.mark("services.done")
        if boot_runtime:
            await self.start_runtime()

    async def start_runtime(self) -> None:
        """Build catalogs and boot the agent runtime after the socket is bound.

        Split out of :meth:`start` on purpose: this phase imports the agent stack
        (harness, langchain, deepagents) and scans the expert/subagent catalogs,
        which together dominate cold-start time. The HTTP listener is already
        accepting connections while it runs, so ``/api/health`` answers first.
        """
        from happyclaw.infra.utils import startup_timing as _timing  # noqa: PLC0415

        if self.app_runtime is not None:
            return
        config = self.config
        if config is None:
            raise RuntimeError("start_runtime() called before start()")
        if self.services is None:
            raise RuntimeError("start_runtime() called before the database is bound")

        with _timing.segment("runtime.prepare"):
            await asyncio.to_thread(self._prepare_runtime)

        with _timing.segment("runtime"):
            await self._boot_runtime(config)

        assert self.user_manager is not None
        self._emit_wizard_password(user_count=self.user_manager.count())
        self._schedule_default_agent_bootstrap()

    def _prepare_runtime(self) -> None:
        """Worker-thread half of :meth:`start_runtime`: imports, catalogs, plugins.

        Runs off the event loop so ``/api/health`` keeps answering while the
        agent stack (harness → deepagents → langchain) is being imported.
        """
        import happyclaw.infra.agents.manager  # noqa: F401, PLC0415
        import happyclaw.infra.agents.plugins.manager  # noqa: F401, PLC0415
        import happyclaw.infra.agents.providers.store  # noqa: F401, PLC0415
        import happyclaw.infra.agents.subagents.catalog  # noqa: F401, PLC0415
        import happyclaw.infra.cron.manager  # noqa: F401, PLC0415
        import happyclaw.infra.gateway.gateway  # noqa: F401, PLC0415
        import happyclaw.infra.proactive.scheduler  # noqa: F401, PLC0415
        import happyclaw.infra.proactive.service  # noqa: F401, PLC0415
        import happyclaw.infra.users.manager  # noqa: F401, PLC0415

        from happyclaw.infra.connectors.gateway.cli_install import ensure_cli_path  # noqa: PLC0415

        ensure_cli_path()
        self._load_plugins()

    async def _deferred_runtime_warmup(self, config: OctopConfig) -> None:
        """Filesystem walks and config tweaks that do not gate first paint.

        Runs as a fire-and-forget ``asyncio.create_task`` from ``_boot_runtime``
        so the agent runtime keeps wiring the event loop while these happen.
        Never raises — a failed avatar/snapshot scan must not bring the server
        down.
        """
        if self.services is None:
            return
        from happyclaw.infra.agents.experts.snapshot_store import (  # noqa: PLC0415
            adopt_local_snapshots,
        )
        from happyclaw.infra.users.profile_avatar import adopt_local_avatars  # noqa: PLC0415
        from happyclaw.infra.utils.browser_media import (  # noqa: PLC0415
            configure_browser_idle_timeout,
        )

        try:
            adopt_local_avatars(
                self.services.profile_avatar_repo,
                self.services.settings_repo,
                self.paths,
            )
            adopt_local_snapshots(
                self.services.control_file_repo,
                self.services.settings_repo,
                self.paths.published_experts_dir,
            )
            configure_browser_idle_timeout(config.browser_idle_timeout_minutes)
        except Exception:  # pragma: no cover - best effort only
            logger.exception("deferred runtime warmup failed (non-fatal)")

    def _load_catalogs(self) -> None:
        from happyclaw.infra.utils import startup_timing as _timing  # noqa: PLC0415

        with _timing.segment("catalogs.load"):
            from happyclaw.infra.agents.experts.catalog import (  # noqa: PLC0415
                ExpertCatalog,
                default_library_root,
            )
            from happyclaw.infra.agents.subagents.catalog import (  # noqa: PLC0415
                SubagentCatalog,
                default_package_root,
            )

            expert_catalog = ExpertCatalog(
                default_library_root(),
                extra_roots=[self.paths.expert_market_dir],
            )
            expert_catalog.refresh()
            subagent_catalog = SubagentCatalog(default_package_root())
            subagent_catalog.refresh()
            self._expert_catalog = expert_catalog
            self._subagent_catalog = subagent_catalog

    def _load_plugins(self, *, install_deps: bool = False) -> None:
        """Discover bundled + on-disk plugins.

        ``install_deps`` defaults to ``False`` so cold start never blocks on
        ``pip install``. The per-plugin dependency install is triggered lazily
        only when the user first opens the plugin management page — bundling is
        already complete, so deferring dependencies only affects freshly
        dropped user plugins, not the shipped demo plugins.
        """
        from happyclaw.infra.agents.plugins.manager import PluginManager  # noqa: PLC0415

        self.plugin_manager = PluginManager(
            plugins_dir=self.paths.plugins_dir,
            config_path=self.paths.config,
        )
        self.plugin_manager.seed_bundled()
        self.plugin_manager.load_installed(install_deps=install_deps)
        self._apply_plugin_channels()

    def _schedule_default_agent_bootstrap(self) -> None:
        """Create the default ``main`` expert right after the server starts.

        Fire-and-forget on purpose: first paint (``/api/health``) must never
        wait for market pulls or workspace seeding. Any failure is logged and
        ignored — the user can still create an expert by hand. Tests opt out
        with ``OCTOP_DISABLE_DEFAULT_AGENT=1``.
        """
        disabled = os.environ.get("OCTOP_DISABLE_DEFAULT_AGENT", "").strip().lower()
        if disabled in {"1", "true", "yes", "on"}:
            return
        self._default_agent_task = asyncio.create_task(self._bootstrap_default_agent())

    async def _bootstrap_default_agent(self) -> None:
        from happyclaw.infra.utils import startup_timing as _timing  # noqa: PLC0415

        started = time.perf_counter()
        queued_ms = _timing.since_mark_ms("services.done")
        status = "ok"
        try:
            if self.services is None:
                return
            from happyclaw.infra.agents.experts.default_agent import (  # noqa: PLC0415
                SETUP_DEFAULT_AGENT_ID,
                try_bootstrap_default_agent,
            )

            await try_bootstrap_default_agent(
                self,
                user_id=self.services.owner.owner_id(),
                agent_id=SETUP_DEFAULT_AGENT_ID,
            )
        except Exception:  # pragma: no cover - non-fatal by design
            status = "failed"
            logger.exception("default agent bootstrap failed (non-fatal)")
        finally:
            _timing.emit(
                "default_agent",
                (time.perf_counter() - started) * 1000.0,
                status=status,
                queued_after_boot_ms=None if queued_ms is None else round(queued_ms, 1),
            )

    async def bind_control_plane(self) -> None:
        """Open the configured control-plane DB and boot runtime (first-run wizard).

        Idempotent when already bound: no-op. Call after persisting ``database``
        into ``config.json``. Does not rebind an existing live pool — use
        ``rebind_control_plane`` only when swapping while ``user_count == 0``.
        """
        if self.database_bound:
            return
        config = load_config(self.paths.config)
        self.config = config
        from happyclaw.infra.db.factory import open_database  # noqa: PLC0415
        from happyclaw.infra.db.migrate import run_migrations  # noqa: PLC0415
        from happyclaw.infra.db.services import build_shared_services  # noqa: PLC0415

        if self.plugin_manager is None:
            self._load_plugins()
        db = open_database(config, self.paths)
        try:
            run_migrations(db)
        except Exception:
            db.close()
            raise
        self.services = build_shared_services(db=db, paths=self.paths, config=config)
        from happyclaw.infra.auth.captcha import boot_from_services  # noqa: PLC0415

        boot_from_services(self.services.settings_repo, self.services.secret_repo)
        self._ensure_jwt_secret()
        await self._boot_runtime(config)
        logger.info(
            "control-plane database bound driver=%s",
            config.database.driver,
        )

    async def _boot_runtime(self, config: OctopConfig) -> None:
        assert self.services is not None
        assert self.plugin_manager is not None

        from happyclaw.infra.utils import startup_timing as _timing  # noqa: PLC0415
        # Imported here, not at module scope: this is the agent stack (harness →
        # deepagents → langchain) and it must stay off the pre-listen path.
        from happyclaw.infra.agents.manager import AgentManager  # noqa: PLC0415
        from happyclaw.infra.agents.providers.store import (  # noqa: PLC0415
            sync_provider_preset_models,
        )
        from happyclaw.infra.cron.manager import CronManager  # noqa: PLC0415
        from happyclaw.infra.gateway.gateway import Gateway  # noqa: PLC0415
        from happyclaw.infra.proactive.scheduler import ProactiveCareScheduler  # noqa: PLC0415
        from happyclaw.infra.proactive.service import ProactiveCareService  # noqa: PLC0415
        from happyclaw.infra.users.manager import UserManager  # noqa: PLC0415

        with _timing.segment("services.providers"):
            added = await asyncio.get_running_loop().run_in_executor(
                None, sync_provider_preset_models, self.services.provider_repo
            )
        if added:
            logger.info("Added %d newly bundled provider models", added)

        # Deferred past a fast initial scan: avatar/snapshot adoption and
        # browser idle-tuning are pure filesystem/config tweaks and never
        # block the HTTP listener.
        asyncio.create_task(
            self._deferred_runtime_warmup(config),
            name="deferred-runtime-warmup",
        )

        # attach_control_plane must run after services are bound (DB access), but
        # seed_bundled + load_installed(install_deps=False) already ran in
        # ``_prepare_runtime``; do not repeat the pip-less scan.
        self.plugin_manager.attach_control_plane(
            self.services.control_file_repo,
            self.services.settings_repo,
        )

        registry = AgentManager(
            repos=self.services.repos,
            paths=self.paths,
            config=config,
            expert_catalog=self.expert_catalog_lazy,
            plugin_manager=self.plugin_manager,
        )

        from happyclaw.infra.history.retire_v2 import migrate_history_v2  # noqa: PLC0415

        try:
            with _timing.segment("services.history_migrate"):
                await asyncio.to_thread(migrate_history_v2, self.paths, self.services.db, registry)
        except Exception:
            self.services.db.close()
            self.services = None
            raise

        from happyclaw.infra.history.trajectory.live import TrajectoryLiveBus  # noqa: PLC0415
        from happyclaw.infra.history.trajectory.service import TrajectoryService  # noqa: PLC0415
        from happyclaw.infra.history.trajectory.store import TrajectoryStore  # noqa: PLC0415

        trajectory_service = TrajectoryService(
            TrajectoryStore(self.services.trajectory_event_repo),
            TrajectoryLiveBus(),
        )

        gateway = Gateway(
            agent_manager=registry,
            repos=self.services.repos,
            trajectory_service=trajectory_service,
            instance_id=self.instance_id,
        )
        with _timing.segment("services.gateway_boot"):
            await gateway.boot(serve_background=self._serve_background)

        from happyclaw import __version__  # noqa: PLC0415

        started_at = self._started_at
        if started_at is None:
            import time  # noqa: PLC0415

            started_at = int(time.time())
        gateway.set_slash_meta(version=__version__, started_at=started_at)
        self._started_at = started_at

        from happyclaw.infra.cron.delivery import CronDeliveryService  # noqa: PLC0415

        cron_delivery = CronDeliveryService(
            gateway=gateway,
            agent_manager=registry,
            repos=self.services.repos,
        )
        cron_mgr = CronManager(
            gateway=gateway,
            delivery_service=cron_delivery,
            repos=self.services.repos,
            timezone=config.default_timezone,
            instance_id=self.instance_id,
        )
        with _timing.segment("services.cron"):
            await cron_mgr.boot(serve_background=self._serve_background)

        if self._serve_background:
            from happyclaw.infra.setup.tls.renewal import install_auto_renewal_job

            install_auto_renewal_job(cron_mgr, paths=self.paths)

            from happyclaw.infra.backup.auto import install_auto_backup_job

            install_auto_backup_job(cron_mgr, server=self)

        registry.set_cron_manager(cron_mgr)
        registry.set_team_processor(gateway.processor.teams)
        hitl_session_store = gateway.processor.hitl_coordinator.session_policies
        hitl_session_store.replace_repo(self.services.repos.thread_repo)
        registry.set_hitl_session_store(hitl_session_store)

        care_service = ProactiveCareService(
            gateway=gateway,
            care_push_repo=self.services.repos.care_push_repo,
            agent_manager=registry,
            timezone=config.default_timezone,
        )
        proactive_scheduler = ProactiveCareScheduler(
            care_service=care_service,
            config_repo=self.services.repos.proactive_care_config_repo,
            session_repo=self.services.repos.session_repo,
            agent_repo=self.services.repos.agent_repo,
            user_repo=self.services.repos.user_repo,
            thread_repo=self.services.repos.thread_repo,
            care_push_repo=self.services.repos.care_push_repo,
            is_agent_busy=registry.is_agent_active,
            default_timezone=config.default_timezone,
        )
        registry.set_proactive_scheduler(proactive_scheduler)

        with _timing.segment("services.agents"):
            # Wiring only: agent graph compilation is deferred to
            # ``_restore_agents_background`` so the socket binds first.
            await registry.boot(restore_agents=False)
        registry.schedule_idle_reclaim_sweep()
        with _timing.segment("services.media"):
            await gateway.refresh_media_backends()

        user_mgr = UserManager(self.services)
        with _timing.segment("services.users"):
            await user_mgr.boot()
        with _timing.segment("services.proactive"):
            await proactive_scheduler.start_all()

        # Single-user mode: login/MFA flows are retired, so nothing enqueues
        # auth challenges or pending TOTP enrolments anymore. The startup prune
        # was the only remaining background writer to those tables; skip it so
        # retained legacy data is not touched.
        from happyclaw.infra.auth.tokens import PURPOSE_ACCESS, sign_token
        from happyclaw.infra.bridge.manager import BridgeManager, public_base_url_from_config

        services = self.services
        if services is None:
            raise RuntimeError("shared services not ready for bridge")

        def _sign_user_token(user: Any) -> str:
            secret = services.secret_repo.get("jwt")
            if secret is None:
                raise RuntimeError("jwt secret missing")
            ttl = services.config.access_token_ttl_seconds
            row = services.user_repo.get(int(user.id))
            mfa_version = int(row.mfa_version) if row is not None else 0
            password_version = int(row.password_version) if row is not None else 0
            return sign_token(
                secret,
                sub=int(user.id),
                uname=str(user.username),
                role=str(user.role),
                purpose=PURPOSE_ACCESS,
                ttl_seconds=ttl,
                mfa_version=mfa_version,
                password_version=password_version,
            )

        advertise = public_base_url_from_config(config.bind_host, config.port)
        bridge_mgr = BridgeManager(
            bridge_repo=services.bridge_connection_repo,
            secret_repo=services.secret_repo,
            user_repo=services.user_repo,
            advertise_base_url=advertise,
            token_signer=_sign_user_token,
        )

        self.app_runtime = AppRuntime(
            agent_registry=registry,
            gateway=gateway,
            cron_manager=cron_mgr,
            user_manager=user_mgr,
            proactive_scheduler=proactive_scheduler,
            trajectory_service=trajectory_service,
            bridge_manager=bridge_mgr,
        )
        from happyclaw.infra.knowledge.gate import (  # noqa: PLC0415
            warn_if_local_embedding_deps_missing,
        )
        from happyclaw.infra.knowledge.jobs import resume_pending_index_jobs  # noqa: PLC0415
        from happyclaw.infra.knowledge.ocr import warn_if_local_ocr_deps_missing  # noqa: PLC0415

        warn_if_local_embedding_deps_missing(
            self.services.settings_repo.get,
            self.services.provider_repo,
        )
        warn_if_local_ocr_deps_missing(
            self.services.settings_repo.get,
            self.services.provider_repo,
        )
        resume_pending_index_jobs(self.services)

        # Resume Bridge links that opted into auto-reconnect (best-effort).
        async def _resume_bridges() -> None:
            with suppress(Exception):
                await bridge_mgr.resume_auto_connections()

        asyncio.create_task(_resume_bridges(), name="bridge-auto-resume")
        self._agent_restore_task = asyncio.create_task(
            self._restore_agents_background(registry), name="agent-restore"
        )

    async def _restore_agents_background(self, registry: AgentManager) -> None:
        """Start persisted agents after the socket is bound (never raise)."""
        from happyclaw.infra.utils import startup_timing as _timing  # noqa: PLC0415

        started = time.perf_counter()
        try:
            await registry.restore_agents()
        except asyncio.CancelledError:
            raise
        except Exception:  # pragma: no cover - boot must survive any agent failure
            logger.exception("background agent restore failed (non-fatal)")
        finally:
            _timing.emit("agents.restored", (time.perf_counter() - started) * 1000.0)

    async def refresh_plugin_channels(self) -> None:
        """Reconcile only changed kinds and report registration failures to callers."""
        from happyclaw_harness.plugins.registry import PluginRegistry  # noqa: PLC0415

        from happyclaw.infra.errors import ErrorCode, OctopError
        from happyclaw.infra.gateway.plugin_channels import (
            changed_plugin_channel_kinds,
            current_registration_errors,
        )

        changed = changed_plugin_channel_kinds(PluginRegistry())
        if self.app_runtime is not None:
            await self.app_runtime.gateway.reload_plugin_channels(
                self._apply_plugin_channels, kinds=changed
            )
        else:
            self._apply_plugin_channels()
        errors = current_registration_errors()
        if errors:
            raise OctopError(
                ErrorCode.PLUGIN_INSTALL_FAILED,
                "plugin channel registration failed",
                details={"registration_errors": errors},
            )

    def _apply_plugin_channels(self) -> None:
        """Register plugin-contributed channel kinds with the gateway.

        Called after every plugin load/reload so channel kinds are always in
        sync with the plugin registry. Best-effort: a failure in one plugin's
        registration never blocks boot (already handled inside
        ``apply_plugin_channels``).
        """
        if self.plugin_manager is None:
            return
        try:
            from happyclaw_harness.plugins.registry import PluginRegistry  # noqa: PLC0415

            from happyclaw.infra.gateway.plugin_channels import apply_plugin_channels  # noqa: PLC0415

            apply_plugin_channels(registry=PluginRegistry())
        except Exception:
            logger.exception("applying plugin channel kinds failed")

    def _emit_wizard_password(self, *, user_count: int) -> None:
        # Single-user mode: no setup wizard account and no one-time password
        # file. Existing ``octop-login.txt`` files stay on disk untouched.
        logger.info("single-user mode: skipping first-run wizard password (user_count=%s)", user_count)
        return

    def _legacy_emit_wizard_password(self, *, user_count: int) -> None:
        from happyclaw.infra.setup import password_file as _wizard_pw  # noqa: PLC0415

        config = self.config
        if config is None:
            return
        wizard_home = self.paths.root
        if config.require_setup_password:
            try:
                new_pw = _wizard_pw.boot_self_heal(
                    wizard_home,
                    user_count=user_count,
                    legacy_home=Path.home(),
                )
            except OSError as err:
                logger.warning("wizard self-heal failed: %s", err)
                new_pw = None
        else:
            new_pw = None
        if new_pw is not None:
            file_path = _wizard_pw.resolve_password_path(wizard_home, legacy_home=Path.home())
            try:
                rel = file_path.relative_to(Path.home())
                display_file = f"~/{rel.as_posix()}"
            except ValueError:
                display_file = str(file_path)
            file_label = f"File: {display_file}"
            if len(file_label) > 54:
                file_label = f"File: ...{str(file_path)[-(54 - 9) :]}"
            banner = (
                "\n\033[33m"
                "╔══════════════════════════════════════════════════════════╗\n"
                "║  HappyClaw first-run wizard password (one-time use):          ║\n"
                f"║  {new_pw:<54}  ║\n"
                "║  Open the dashboard and paste it into the setup wizard.  ║\n"
                f"║  {file_label:<54}  ║\n"
                "╚══════════════════════════════════════════════════════════╝"
                "\033[0m\n"
            )
            print(banner, flush=True)
            logger.info(
                "wizard password generated; file=%s",
                file_path,
            )

    async def stop(self) -> None:
        if not self._started:
            return
        task = self._default_agent_task
        if task is not None and not task.done():
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        self._default_agent_task = None
        restore = self._agent_restore_task
        if restore is not None and not restore.done():
            restore.cancel()
            with suppress(asyncio.CancelledError):
                await restore
        self._agent_restore_task = None
        try:
            from happyclaw.infra.connectors.gateway import agently_auth

            await agently_auth.close()
            if self.app_runtime is not None:
                rt = self.app_runtime
                await rt.proactive_scheduler.shutdown()
                await rt.cron_manager.shutdown()
                await rt.gateway.shutdown()
                await rt.agent_registry.shutdown()
                await rt.user_manager.shutdown_all()
            from happyclaw.infra.backend.browse import dispose_all_browse_sessions

            dispose_all_browse_sessions()
        finally:
            if self.services is not None:
                self.services.db.close()
            self.services = None
            self.app_runtime = None
            self._started = False
            logger.info("octop server stopped")

    # ----- helpers -----

    def _setup_logging(self) -> None:
        log_dir = self.paths.logs_dir
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = self.paths.log

        # Migrate the legacy single-file log (~/.octop/octop.log) into the new logs dir.
        legacy = self.paths.root / "octop.log"
        if legacy.exists() and not log_path.exists():
            with suppress(OSError):
                legacy.replace(log_path)

        retention_days = _parse_log_retention_days()
        max_bytes = _parse_log_max_bytes()
        compress_rotated = _parse_log_compress()
        _migrate_legacy_rotated_logs(log_dir)
        handler = _build_log_handler(
            log_path,
            retention_days,
            max_bytes=max_bytes,
            compress_rotated=compress_rotated,
        )
        _purge_stale_logs(log_dir, retention_days)
        # Catch up: gzip older plains, leave the newest rotated file plain (delaycompress).
        delaycompress_rotated_logs(log_dir, enabled=compress_rotated)

        root = logging.getLogger()
        _attach_log_handler(root, handler)
        # Persist framework (uvicorn) request/error logs into the same file too.
        for name in ("uvicorn", "uvicorn.access", "uvicorn.error"):
            _attach_log_handler(logging.getLogger(name), handler)

        level = os.environ.get("OCTOP_LOG_LEVEL", "info").upper()
        root.setLevel(getattr(logging, level, logging.INFO))
        if root.level > logging.DEBUG:
            # httpx logs full request URLs at INFO, leaking query-string
            # secrets (OAuth access_token, corpsecret) into the log file.
            logging.getLogger("httpx").setLevel(logging.WARNING)
            logging.getLogger("httpcore").setLevel(logging.WARNING)

    def _ensure_jwt_secret(self) -> None:
        assert self.services is not None
        self.services.secret_repo.get_or_create("jwt", lambda: os.urandom(32))
