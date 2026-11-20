"""One-shot upgrade from an Octop install to the projects/threads model.

The upgrade never moves user files. Every old workspace becomes a project
(1:1); expert configuration and memory are copied into the expert's private
directory, and threads get a project + workspace snapshot. The only conflict is
a default workspace that already holds user files: keeping files in place
changes the sidebar grouping, while keeping grouping requires a copy. That
choice is mandatory and recorded in ``choice.json`` next to the reports.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from octop.infra.backup.system_archive import create_system_backup
from octop.infra.db.services import SharedServices
from octop.infra.utils.ulid import new_ulid

CHOICE_DATA_FIRST = "data-first"
CHOICE_MERGE_DEFAULT = "merge-default"
CHOICES = (CHOICE_DATA_FIRST, CHOICE_MERGE_DEFAULT)
CHOICE_FILE = "choice.json"
PLAN_FILE = "plan.json"
APPLY_FILE = "apply.json"
GROUP_CHANGES_FILE = "group-changes.md"
CONFLICTS_FILE = "conflicts.md"
DIFF_FILE = "diff.md"

DEFAULT_GROUP_NAME = "默认工作区"

# Workspace-root entries that belong to the runtime, not to the user.
_SYSTEM_ENTRIES = frozenset(
    {
        "AGENTS.md",
        "SOUL.md",
        "IDENTITY.md",
        "MEMORY.md",
        "USER.md",
        ".octop",
        ".octop-auth",
        "skills",
        "sessions",
        "conversation_history",
        "checkpoints.sqlite",
        "checkpoints.sqlite-wal",
        "checkpoints.sqlite-shm",
        "memory.sqlite",
        "memory.sqlite-wal",
        "memory.sqlite-shm",
    }
)
_PLUGIN_MARKERS = ("plugin.yaml", "plugin.yml")

_DEFAULT_NAMES = {"zh": DEFAULT_GROUP_NAME, "en": "Default workspace"}


class UpgradeError(RuntimeError):
    """The upgrade cannot proceed; ``code`` is stable for the CLI/wizard."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class UpgradeChoiceRequired(UpgradeError):
    def __init__(self, options: tuple[str, ...] = CHOICES) -> None:
        super().__init__(
            "choice_required",
            "This install has user files in a default workspace. Choose "
            f"{' or '.join(options)} before applying; no choice is applied silently.",
        )
        self.options = options


def default_project_name(locale: str = "zh") -> str:
    return _DEFAULT_NAMES.get(locale, DEFAULT_GROUP_NAME)


def _norm(path: str | Path) -> str:
    return os.path.normcase(os.path.abspath(os.path.expanduser(str(path))))


def _posix(path: str | Path) -> str:
    return Path(path).as_posix()


@dataclass(frozen=True)
class WorkspaceAsset:
    """One on-disk workspace directory shared by one or more experts."""

    path: str
    kind: str  # "explicit" | "default" | "scoped"
    agent_ids: tuple[str, ...]
    exists: bool
    user_entries: tuple[str, ...] = ()
    has_history: bool = False

    @property
    def has_user_files(self) -> bool:
        return bool(self.user_entries)

    @property
    def project_name(self) -> str:
        return Path(self.path).name or self.path


@dataclass(frozen=True)
class GroupChange:
    thread_id: str
    agent_id: str
    title: str
    before: str
    after_data_first: str
    after_merge_default: str

    @property
    def changes_under_data_first(self) -> bool:
        return self.before != self.after_data_first


@dataclass(frozen=True)
class UpgradeItem:
    section: str
    name: str
    action: str  # "migrate" | "keep" | "conflict" | "skip"
    source: str = ""
    target: str = ""
    reason: str = ""
    detail: str = ""

    def to_dict(self) -> dict[str, str]:
        return {
            "section": self.section,
            "name": self.name,
            "action": self.action,
            "source": self.source,
            "target": self.target,
            "reason": self.reason,
            "detail": self.detail,
        }


@dataclass
class UpgradePlan:
    home: Path
    report_dir: Path
    locale: str = "zh"
    items: list[UpgradeItem] = field(default_factory=list)
    workspaces: list[WorkspaceAsset] = field(default_factory=list)
    group_changes: list[GroupChange] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)
    agent_count: int = 0
    thread_count: int = 0
    choice: str | None = None

    @property
    def requires_choice(self) -> bool:
        return any(
            asset.kind == "default" and asset.has_user_files for asset in self.workspaces
        )

    @property
    def group_change_count(self) -> int:
        return sum(1 for change in self.group_changes if change.changes_under_data_first)

    def add(self, item: UpgradeItem) -> None:
        self.items.append(item)

    def to_dict(self) -> dict[str, Any]:
        return {
            "home": str(self.home),
            "report_dir": str(self.report_dir),
            "locale": self.locale,
            "agent_count": self.agent_count,
            "thread_count": self.thread_count,
            "requires_choice": self.requires_choice,
            "choice": self.choice,
            "items": [item.to_dict() for item in self.items],
            "workspaces": [
                {
                    "path": asset.path,
                    "kind": asset.kind,
                    "agent_ids": list(asset.agent_ids),
                    "exists": asset.exists,
                    "user_entries": list(asset.user_entries),
                    "has_history": asset.has_history,
                }
                for asset in self.workspaces
            ],
            "group_changes": [
                {
                    "thread_id": change.thread_id,
                    "agent_id": change.agent_id,
                    "title": change.title,
                    "before": change.before,
                    "after_data_first": change.after_data_first,
                    "after_merge_default": change.after_merge_default,
                }
                for change in self.group_changes
            ],
            "conflicts": self.conflicts,
        }


@dataclass
class UpgradeReport:
    plan: UpgradePlan
    choice: str | None
    dry_run: bool
    items: list[UpgradeItem] = field(default_factory=list)
    copied_files: list[dict[str, Any]] = field(default_factory=list)
    backup: str = ""
    failures: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.failures

    def add(self, item: UpgradeItem) -> None:
        self.items.append(item)

    def to_dict(self) -> dict[str, Any]:
        return {
            "home": str(self.plan.home),
            "report_dir": str(self.plan.report_dir),
            "choice": self.choice,
            "dry_run": self.dry_run,
            "backup": self.backup,
            "ok": self.ok,
            "items": [item.to_dict() for item in self.items],
            "copied_files": self.copied_files,
            "failures": self.failures,
        }


def _workspace_dir_from_config(config_json: str | None, paths_agents: Path, agent_id: str) -> Path:
    default = paths_agents / agent_id
    if not config_json:
        return default
    try:
        parsed = json.loads(config_json)
    except (TypeError, ValueError):
        return default
    if not isinstance(parsed, dict):
        return default
    raw = parsed.get("workspace_dir")
    if not isinstance(raw, str) or not raw.strip():
        return default
    try:
        return Path(raw).expanduser()
    except (OSError, ValueError):
        return default


def _classify(path: Path, *, home: Path, agent_id: str) -> str:
    normalized = _norm(path)
    if normalized == _norm(home / "agents" / agent_id):
        return "default"
    if ".octop/workspaces/" in _posix(normalized):
        return "scoped"
    return "explicit"


def _user_entries(root: Path) -> tuple[str, ...]:
    if not root.is_dir():
        return ()
    out: list[str] = []
    for entry in sorted(root.iterdir(), key=lambda p: p.name):
        if entry.name in _SYSTEM_ENTRIES:
            continue
        out.append(entry.name)
    return tuple(out)


def _has_history(root: Path) -> bool:
    sessions = root / "sessions"
    if sessions.is_dir() and any(p.is_file() for p in sessions.rglob("*")):
        return True
    if (root / "conversation_history").is_dir():
        return True
    return (root / "checkpoints.sqlite").is_file()


def _agent_rows(services: SharedServices) -> list[Any]:
    return services.agent_repo.list_all()


def scan_install(
    *,
    services: SharedServices,
    locale: str = "zh",
    report_dir: Path | None = None,
) -> UpgradePlan:
    """Read-only scan of an existing install; writes no files."""
    home = Path(services.paths.root)
    stamp = _report_stamp()
    out_dir = report_dir or (home / "migration-reports" / f"octop-to-happyclaw-{stamp}")
    plan = UpgradePlan(home=home, report_dir=out_dir, locale=locale)

    agents = _agent_rows(services)
    plan.agent_count = len(agents)
    agent_by_id = {str(row.agent_id): row for row in agents}

    grouped: dict[str, list[str]] = {}
    for row in agents:
        path = _workspace_dir_from_config(row.config_json, services.paths.agents_dir, row.agent_id)
        grouped.setdefault(_norm(path), []).append(str(row.agent_id))

    for normalized, agent_ids in sorted(grouped.items()):
        first = agent_by_id[agent_ids[0]]
        raw_path = _workspace_dir_from_config(
            first.config_json, services.paths.agents_dir, first.agent_id
        )
        kind = _classify(raw_path, home=home, agent_id=first.agent_id)
        asset = WorkspaceAsset(
            path=str(raw_path),
            kind=kind,
            agent_ids=tuple(agent_ids),
            exists=raw_path.is_dir(),
            user_entries=_user_entries(raw_path),
            has_history=_has_history(raw_path),
        )
        plan.workspaces.append(asset)
        if len(agent_ids) > 1:
            plan.conflicts.append(
                f"共享工作区 {asset.path}：{', '.join(agent_ids)}；用户文件无法细分，"
                "归属记在该项目下，不做猜测。"
            )
        action = "keep" if not asset.exists else "migrate"
        target = "project" if kind in {"explicit", "scoped"} else "default-project"
        if kind == "default" and asset.has_user_files:
            action = "conflict"
            target = "user-choice"
        plan.add(
            UpgradeItem(
                section="workspace",
                name=asset.path,
                action=action,
                source=asset.path,
                target=target,
                reason=(
                    "default_with_user_files"
                    if kind == "default" and asset.has_user_files
                    else kind
                ),
                detail=", ".join(asset.user_entries[:5]),
            )
        )
        for agent_id in agent_ids:
            plan.add(
                UpgradeItem(
                    section="agent-config",
                    name=agent_id,
                    action="migrate",
                    source=asset.path,
                    target=str(services.paths.agent_workspace(agent_id)),
                    reason="copy-config-and-memory",
                )
            )

    threads = services.thread_repo.list_all()
    plan.thread_count = len(threads)
    for thread in threads:
        agent_id = thread.agent_id
        row = agent_by_id.get(agent_id)
        if row is None:
            plan.add(
                UpgradeItem(
                    section="thread",
                    name=thread.thread_id,
                    action="skip",
                    reason="agent-missing",
                )
            )
            continue
        workspace = _workspace_dir_from_config(
            row.config_json, services.paths.agents_dir, agent_id
        )
        kind = _classify(workspace, home=home, agent_id=agent_id)
        before = DEFAULT_GROUP_NAME if kind == "default" else workspace.name
        asset = next(
            (a for a in plan.workspaces if _norm(a.path) == _norm(workspace)), None
        )
        independent = asset is not None and asset.kind == "default" and asset.has_user_files
        after_data_first = (asset.project_name if independent else before) or before
        after_merge = before
        plan.group_changes.append(
            GroupChange(
                thread_id=thread.thread_id,
                agent_id=agent_id,
                title=thread.title or "",
                before=before,
                after_data_first=after_data_first,
                after_merge_default=after_merge,
            )
        )
        if thread.project_id or thread.workspace_dir:
            plan.add(
                UpgradeItem(
                    section="thread",
                    name=thread.thread_id,
                    action="skip",
                    reason="already-migrated",
                    target=thread.project_id or "",
                )
            )
        else:
            plan.add(
                UpgradeItem(
                    section="thread",
                    name=thread.thread_id,
                    action="migrate",
                    source=before,
                    target=after_data_first,
                    reason=kind,
                )
            )

    _scan_global_state(plan, services)
    return plan


def _scan_global_state(plan: UpgradePlan, services: SharedServices) -> None:
    config_file = services.paths.config
    if config_file.is_file():
        try:
            json.loads(config_file.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            plan.conflicts.append(f"config.json 无法解析：{exc}")
            plan.add(
                UpgradeItem(
                    section="config",
                    name=str(config_file),
                    action="conflict",
                    source=str(config_file),
                    reason="invalid-json",
                    detail=str(exc),
                )
            )
        else:
            plan.add(
                UpgradeItem(
                    section="config",
                    name=str(config_file),
                    action="keep",
                    source=str(config_file),
                    reason="global-state-unchanged",
                )
            )

    plugins_dir = services.paths.plugins_dir
    if plugins_dir.is_dir():
        for entry in sorted(plugins_dir.iterdir()):
            if not entry.is_dir():
                continue
            markers = [entry / name for name in _PLUGIN_MARKERS]
            ok = any(path.is_file() for path in markers)
            plan.add(
                UpgradeItem(
                    section="plugins",
                    name=entry.name,
                    action="keep" if ok else "conflict",
                    source=str(entry),
                    reason="installed" if ok else "manifest-missing",
                )
            )

    device_dir = Path(services.paths.root) / "device-link"
    for name in ("settings.json", "credentials.json"):
        path = device_dir / name
        if not path.is_file():
            continue
        try:
            json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            plan.add(
                UpgradeItem(
                    section="device-link",
                    name=name,
                    action="conflict",
                    source=str(path),
                    reason="invalid-json",
                    detail=str(exc),
                )
            )
        else:
            plan.add(
                UpgradeItem(
                    section="device-link",
                    name=name,
                    action="keep",
                    source=str(path),
                    reason="credentials-kept-no-auto-reconnect",
                )
            )

    dsh = {key: value for key, value in os.environ.items() if key.startswith("OCTOP_DSH_")}
    if dsh:
        plan.add(
            UpgradeItem(
                section="dsh",
                name="env",
                action="keep",
                reason="env-snapshot",
                detail=", ".join(sorted(dsh)),
            )
        )


def _report_stamp() -> str:
    return time.strftime("%Y%m%d-%H%M%S")


def write_plan_reports(plan: UpgradePlan) -> Path:
    """Write ``plan.json``, ``group-changes.md`` and ``conflicts.md``."""
    plan.report_dir.mkdir(parents=True, exist_ok=True)
    (plan.report_dir / PLAN_FILE).write_text(
        json.dumps(plan.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8"
    )
    (plan.report_dir / GROUP_CHANGES_FILE).write_text(_group_changes_md(plan), encoding="utf-8")
    (plan.report_dir / CONFLICTS_FILE).write_text(_conflicts_md(plan), encoding="utf-8")
    return plan.report_dir


def _group_changes_md(plan: UpgradePlan) -> str:
    lines = [
        "# 会话分组变化",
        "",
        "升级前请确认侧栏分组影响。两种选择下的结果并列如下：",
        "",
        "- 数据优先：文件与历史零移动，上表「数据优先后」一列是升级后的分组。",
        "- 合并进默认项目：分组保持「迁移前」一列，但文件会复制一份、路径变化，"
        "checkpoint 无法合并。",
        "",
        "| 会话 | 专家 | 标题 | 迁移前 | 数据优先后 | 合并进默认项目后 |",
        "|---|---|---|---|---|---|",
    ]
    for change in plan.group_changes:
        lines.append(
            "| {tid} | {aid} | {title} | {before} | {df} | {md} |".format(
                tid=change.thread_id,
                aid=change.agent_id,
                title=(change.title or "").replace("|", "\\|")[:40],
                before=change.before,
                df=change.after_data_first,
                md=change.after_merge_default,
            )
        )
    changed = [c for c in plan.group_changes if c.changes_under_data_first]
    lines.extend(
        [
            "",
            f"共 {len(plan.group_changes)} 个会话；选择数据优先时其中 "
            f"{len(changed)} 个会话的分组会变化。",
            "",
        ]
    )
    return "\n".join(lines)


def _conflicts_md(plan: UpgradePlan) -> str:
    lines = ["# 升级冲突与保留项", ""]
    lines.extend(f"- {item}" for item in plan.conflicts)
    copies = [i for i in plan.items if i.section == "agent-config"]
    if copies:
        lines.extend(
            [
                "",
                "## 专家配置副本",
                "",
                "以下提示词/技能只复制一份到专家私有目录，原始文件保留在旧工作区：",
                "",
            ]
        )
        lines.extend(f"- {item.name}: {item.source} → {item.target}" for item in copies)
    lines.append("")
    return "\n".join(lines)


def _specific_file_entries() -> tuple[str, ...]:
    return ("AGENTS.md", "SOUL.md", "IDENTITY.md", "MEMORY.md", "USER.md")


def _copy_private_config(
    asset: WorkspaceAsset, target: Path, report: UpgradeReport
) -> None:
    """Copy expert prompt files into the private directory; never delete originals."""
    if not Path(asset.path).is_dir():
        report.failures.append(f"workspace missing: {asset.path}")
        return
    target.mkdir(parents=True, exist_ok=True)
    for name in _specific_file_entries():
        source = Path(asset.path) / name
        if not source.is_file():
            continue
        try:
            shutil.copy2(source, target / name)
        except OSError as exc:
            report.failures.append(f"copy {source} -> {target / name}: {exc}")
            continue
        report.add(
            UpgradeItem(
                section="agent-config",
                name=name,
                action="migrate",
                source=str(source),
                target=str(target / name),
                reason="copy-kept-original",
            )
        )
    source_skills = Path(asset.path) / "skills"
    if source_skills.is_dir():
        try:
            shutil.copytree(source_skills, target / "skills", dirs_exist_ok=True)
        except OSError as exc:
            report.failures.append(f"copy skills {source_skills}: {exc}")
        else:
            report.add(
                UpgradeItem(
                    section="agent-config",
                    name="skills",
                    action="migrate",
                    source=str(source_skills),
                    target=str(target / "skills"),
                    reason="copy-kept-original",
                )
            )


def _copy_tree(source: Path, target: Path, report: UpgradeReport) -> None:
    """Copy a default workspace into the merged default project, hashing files."""
    for path in sorted(source.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(source)
        if rel.parts and rel.parts[0] in {".octop", ".octop-auth"}:
            continue
        dest = target / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            data = path.read_bytes()
            dest.write_bytes(data)
        except OSError as exc:
            report.failures.append(f"copy {path} -> {dest}: {exc}")
            continue
        report.copied_files.append(
            {
                "source": str(path),
                "target": str(dest),
                "sha256": hashlib.sha256(data).hexdigest(),
                "size": len(data),
            }
        )


def _project_by_root(services: SharedServices, user_id: int, root_dir: str) -> Any:
    return services.project_repo.find_by_root_dir(user_id, root_dir)


def _ensure_project(
    services: SharedServices,
    *,
    user_id: int,
    name: str,
    root_dir: str,
    origin: str,
    report: UpgradeReport,
) -> Any:
    existing = _project_by_root(services, user_id, root_dir)
    if existing is not None:
        report.add(
            UpgradeItem(
                section="project",
                name=existing.project_id,
                action="skip",
                target=existing.root_dir or "",
                reason="exists",
            )
        )
        return existing
    project_id = f"prj_{new_ulid()}"
    row = services.project_repo.create(
        project_id=project_id,
        user_id=user_id,
        name=name,
        root_dir=root_dir,
        origin=origin,
    )
    report.add(
        UpgradeItem(
            section="project",
            name=project_id,
            action="migrate",
            target=root_dir,
            reason=origin,
        )
    )
    return row


def apply_upgrade(
    plan: UpgradePlan,
    *,
    services: SharedServices,
    choice: str | None,
    operator: str = "cli",
    dry_run: bool = False,
    backup: bool = True,
) -> UpgradeReport:
    """Apply the plan. Refuses to run when the conflict choice is missing."""
    if plan.requires_choice and choice not in CHOICES:
        raise UpgradeChoiceRequired()
    if choice is not None and choice not in CHOICES:
        raise UpgradeError("invalid_choice", f"unknown choice: {choice}")

    report = UpgradeReport(plan=plan, choice=choice, dry_run=dry_run)
    if dry_run:
        for item in plan.items:
            report.add(item)
        return report

    if backup:
        report.backup = _backup(services, plan)
    if choice is not None:
        _write_choice(plan, choice=choice, operator=operator)

    # Copy expert prompts/skills once per workspace, before binding threads.
    for asset in plan.workspaces:
        if not asset.exists:
            continue
        for agent_id in asset.agent_ids:
            _copy_private_config(asset, services.paths.agent_workspace(agent_id), report)

    agents = {str(row.agent_id): row for row in services.agent_repo.list_all()}
    default_projects: dict[int, Any] = {}
    for thread in services.thread_repo.list_all():
        if thread.project_id or thread.workspace_dir:
            continue
        row = agents.get(thread.agent_id)
        if row is None or row.user_id is None:
            report.add(
                UpgradeItem(
                    section="thread",
                    name=thread.thread_id,
                    action="skip",
                    reason="agent-missing",
                )
            )
            continue
        user_id = int(row.user_id)
        workspace = _workspace_dir_from_config(
            row.config_json, services.paths.agents_dir, row.agent_id
        )
        kind = _classify(workspace, home=plan.home, agent_id=row.agent_id)
        asset = next(
            (a for a in plan.workspaces if _norm(a.path) == _norm(workspace)), None
        )
        independent = asset is not None and asset.kind == "default" and asset.has_user_files

        if kind == "default" and not independent:
            project = _default_project(
                services, default_projects, user_id=user_id, locale=plan.locale
            )
            project_id = project.project_id
            snapshot = str(workspace)
        elif kind == "default" and independent and choice == CHOICE_MERGE_DEFAULT:
            project = _default_project(
                services, default_projects, user_id=user_id, locale=plan.locale
            )
            merged_root = (
                services.paths.project_root("default") / "legacy" / row.agent_id
            )
            if asset is not None:
                _copy_tree(Path(asset.path), merged_root, report)
            if project.root_dir is None:
                services.project_repo.update(
                    project.project_id,
                    root_dir=str(services.paths.project_root("default")),
                )
            project_id = project.project_id
            snapshot = str(merged_root)
        else:
            target_name = asset.project_name if asset is not None else workspace.name
            project = _ensure_project(
                services,
                user_id=user_id,
                name=target_name,
                root_dir=str(workspace),
                origin="upgraded" if kind == "default" else "migrated",
                report=report,
            )
            project_id = project.project_id
            snapshot = str(workspace)

        try:
            services.thread_repo.set_workspace(
                thread.thread_id,
                project_id=project_id,
                workspace_kind="project",
                workspace_dir=snapshot,
            )
        except Exception as exc:  # noqa: BLE001 - report and continue
            report.failures.append(f"thread {thread.thread_id}: {exc}")
            continue
        report.add(
            UpgradeItem(
                section="thread",
                name=thread.thread_id,
                action="migrate",
                target=project_id,
                reason=snapshot,
            )
        )

    _write_apply_report(report)
    return report


def _default_project(
    services: SharedServices,
    cache: dict[int, Any],
    *,
    user_id: int,
    locale: str,
) -> Any:
    cached = cache.get(user_id)
    if cached is not None:
        return cached
    row = services.project_repo.ensure_default(
        project_id=f"prj_{new_ulid()}",
        user_id=user_id,
        name=default_project_name(locale),
    )
    cache[user_id] = row
    return row


def _backup(services: SharedServices, plan: UpgradePlan) -> str:
    stamp = _report_stamp()
    dest = services.paths.backups_dir / f"pre-upgrade-{stamp}.tar.gz"
    services.paths.backups_dir.mkdir(parents=True, exist_ok=True)
    create_system_backup(
        paths=services.paths,
        agent_rows=services.agent_repo.list_all(),
        pool=services.db,
        db_config=services.config.database,
        dest=dest,
    )
    plan.add(
        UpgradeItem(
            section="backup",
            name=dest.name,
            action="keep",
            source=str(dest),
            reason="pre-upgrade",
        )
    )
    return str(dest)


def _write_choice(plan: UpgradePlan, *, choice: str, operator: str) -> None:
    plan.report_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "mode": choice,
        "operator": operator,
        "created_at": _report_stamp(),
        "requires_choice": plan.requires_choice,
        "affected_workspaces": [
            asset.path
            for asset in plan.workspaces
            if asset.kind == "default" and asset.has_user_files
        ],
        "group_changes": [
            {
                "thread_id": change.thread_id,
                "before": change.before,
                "after": (
                    change.after_data_first
                    if choice == CHOICE_DATA_FIRST
                    else change.after_merge_default
                ),
            }
            for change in plan.group_changes
        ],
    }
    (plan.report_dir / CHOICE_FILE).write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def _write_apply_report(report: UpgradeReport) -> None:
    report.plan.report_dir.mkdir(parents=True, exist_ok=True)
    (report.plan.report_dir / APPLY_FILE).write_text(
        json.dumps(report.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8"
    )


def verify_upgrade(
    plan: UpgradePlan, *, services: SharedServices, report: UpgradeReport | None = None
) -> list[str]:
    """Return human-readable failures; an empty list means verification passed."""
    failures: list[str] = []
    threads = services.thread_repo.list_all()
    for thread in threads:
        if not thread.project_id and not thread.workspace_dir:
            failures.append(f"thread {thread.thread_id} has no project/workspace binding")
            continue
        project = services.project_repo.get(thread.project_id) if thread.project_id else None
        if thread.project_id and project is None:
            failures.append(f"thread {thread.thread_id} points at missing project")
    for project in services.project_repo.list_for_user(_owner_id(services)):
        if project.root_dir and not Path(project.root_dir).exists():
            failures.append(f"project {project.project_id} root missing: {project.root_dir}")
    if report is not None:
        for entry in report.copied_files:
            target = Path(str(entry["target"]))
            if not target.is_file():
                failures.append(f"copied file missing: {target}")
                continue
            digest = hashlib.sha256(target.read_bytes()).hexdigest()
            if digest != entry["sha256"]:
                failures.append(f"checksum mismatch: {target}")
    if plan.thread_count and len(threads) != plan.thread_count:
        failures.append(
            f"thread count changed: {plan.thread_count} -> {len(threads)}"
        )
    _write_diff(plan, services, failures)
    return failures


def _owner_id(services: SharedServices) -> int:
    return int(services.owner.owner_id())


def _write_diff(plan: UpgradePlan, services: SharedServices, failures: list[str]) -> None:
    projects = services.project_repo.list_for_user(_owner_id(services))
    threads = services.thread_repo.list_all()
    bound = sum(1 for t in threads if t.project_id or t.workspace_dir)
    lines = [
        "# 升级前 / 升级后对照",
        "",
        "| 指标 | 升级前 | 升级后 |",
        "|---|---|---|",
        f"| 专家 | {plan.agent_count} | {len(services.agent_repo.list_all())} |",
        f"| 项目 | 0 | {len(projects)} |",
        f"| 会话 | {plan.thread_count} | {len(threads)} |",
        f"| 已绑定会话 | 0 | {bound} |",
        f"| 工作区目录 | {len(plan.workspaces)} | {len(plan.workspaces)}（原地保留） |",
        f"| 迁移项 | - | {len(plan.items)} |",
        "",
    ]
    if failures:
        lines.extend(["## 未通过项", ""] + [f"- {item}" for item in failures] + [""])
    else:
        lines.extend(["## 结果", "", "全部检查通过，未发现未迁移资产。", ""])
    plan.report_dir.mkdir(parents=True, exist_ok=True)
    (plan.report_dir / DIFF_FILE).write_text("\n".join(lines), encoding="utf-8")


def rollback_upgrade(*, services: SharedServices, report_dir: Path) -> list[str]:
    """Undo the recorded upgrade using the choice that was made at apply time."""
    apply_path = Path(report_dir) / APPLY_FILE
    if not apply_path.is_file():
        raise UpgradeError("no_ledger", f"missing {APPLY_FILE} in {report_dir}")
    ledger = json.loads(apply_path.read_text(encoding="utf-8"))
    failures: list[str] = []
    thread_targets = {
        item["name"]: item.get("target", "")
        for item in ledger.get("items", [])
        if item.get("section") == "thread" and item.get("action") == "migrate"
    }
    for thread_id, project_id in thread_targets.items():
        thread = services.thread_repo.get(thread_id)
        if thread is None:
            continue
        if thread.project_id and project_id and thread.project_id != project_id:
            failures.append(f"thread {thread_id} moved since upgrade; skipped")
            continue
        services.thread_repo.set_workspace(
            thread_id, project_id=None, workspace_kind=None, workspace_dir=None
        )

    mode = str(ledger.get("choice") or "")
    if mode == CHOICE_MERGE_DEFAULT:
        for entry in ledger.get("copied_files", []):
            target = Path(str(entry.get("target", "")))
            if not target.is_file():
                continue
            try:
                target.unlink()
            except OSError as exc:
                failures.append(f"remove {target}: {exc}")
    for project in services.project_repo.list_for_user(_owner_id(services)):
        if project.origin not in {"migrated", "upgraded"}:
            continue
        if services.thread_repo.list_by_project(project_id=project.project_id, limit=1):
            continue
        services.project_repo.delete(project.project_id)
    result = {"mode": mode, "failures": failures, "created_at": _report_stamp()}
    (Path(report_dir) / "rollback.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return failures
