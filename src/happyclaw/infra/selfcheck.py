"""Startup self-check service.

Produces a human-readable Chinese summary of the runtime environment so the
user can tell at a glance whether the service is healthy: database, home
directory, configured model providers (credentials masked), and free disk
space.  Exposed at ``GET /api/health/selfcheck``.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from happyclaw.infra.db.pool import DatabasePool
    from happyclaw.infra.utils.paths import PathLayout


@dataclass(slots=True)
class SelfCheckItem:
    name: str
    ok: bool
    detail: str = ""


@dataclass(slots=True)
class SelfCheckReport:
    ok: bool
    items: list[SelfCheckItem] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "items": [{"name": i.name, "ok": i.ok, "detail": i.detail} for i in self.items],
            "summary": self.summary,
        }

    @property
    def summary(self) -> str:
        passed = sum(1 for i in self.items if i.ok)
        total = len(self.items)
        failed = [i.name for i in self.items if not i.ok]
        if not failed:
            return f"启动自检通过（{passed}/{total}）"
        return f"启动自检 {passed}/{total} 通过，异常项：{', '.join(failed)}"


def _mask_secret(value: str | None) -> str:
    if not value:
        return "未配置"
    if len(value) <= 8:
        return value[:2] + "***"
    return value[:4] + "***" + value[-4:]


class StartupSelfCheck:
    """Run a series of non-destructive checks and report in Chinese."""

    def __init__(
        self,
        *,
        paths: "PathLayout",
        db_pool: "DatabasePool",
        providers_provider: Any,
    ) -> None:
        self._paths = paths
        self._pool = db_pool
        self._providers = providers_provider

    def run(self) -> SelfCheckReport:
        items: list[SelfCheckItem] = []
        items.append(self._check_database())
        items.append(self._check_home_dir())
        items.append(self._check_backup_dir())
        items.append(self._check_model_providers())
        items.append(self._check_disk_space())
        return SelfCheckReport(ok=all(i.ok for i in items), items=items)

    # -- checks -----------------------------------------------------------

    def _check_database(self) -> SelfCheckItem:
        try:
            with self._pool.connection() as conn:
                conn.execute("SELECT 1")
            return SelfCheckItem(name="数据库", ok=True, detail="连接正常")
        except Exception as exc:
            return SelfCheckItem(
                name="数据库",
                ok=False,
                detail=f"连接失败：{type(exc).__name__}: {exc}",
            )

    def _check_home_dir(self) -> SelfCheckItem:
        home = Path(self._paths.home)
        if home.is_dir():
            return SelfCheckItem(name="主目录", ok=True, detail=str(home))
        return SelfCheckItem(name="主目录", ok=False, detail=f"目录不存在：{home}")

    def _check_backup_dir(self) -> SelfCheckItem:
        backups = Path(self._paths.backups_dir)
        if backups.is_dir():
            count = len(list(backups.glob("*.tar.gz")))
            return SelfCheckItem(
                name="备份目录",
                ok=True,
                detail=f"{backups}（{count} 个备份）",
            )
        return SelfCheckItem(name="备份目录", ok=False, detail=f"目录不存在：{backups}")

    def _check_model_providers(self) -> SelfCheckItem:
        try:
            rows = list(self._providers.list_all())
        except Exception as exc:
            return SelfCheckItem(
                name="模型配置",
                ok=False,
                detail=f"读取失败：{type(exc).__name__}: {exc}",
            )
        if not rows:
            return SelfCheckItem(name="模型配置", ok=False, detail="未配置任何模型")
        names = []
        for row in rows:
            api_key = getattr(row, "api_key", None) or getattr(row, "credentials", None)
            names.append(
                f"{getattr(row, 'name', getattr(row, 'provider_id', '?'))}"
                f"（密钥：{_mask_secret(api_key)}）"
            )
        return SelfCheckItem(
            name="模型配置",
            ok=True,
            detail=f"{len(rows)} 个：" + "；".join(names),
        )

    def _check_disk_space(self) -> SelfCheckItem:
        home = Path(self._paths.home)
        try:
            usage = shutil.disk_usage(home)
            free_gb = usage.free / (1024**3)
            if free_gb < 1:
                return SelfCheckItem(
                    name="磁盘空间",
                    ok=False,
                    detail=f"剩余 {free_gb:.1f} GB，不足 1 GB",
                )
            return SelfCheckItem(
                name="磁盘空间",
                ok=True,
                detail=f"剩余 {free_gb:.1f} GB（共 {usage.total / (1024**3):.1f} GB）",
            )
        except Exception as exc:
            return SelfCheckItem(
                name="磁盘空间",
                ok=False,
                detail=f"检测失败：{type(exc).__name__}: {exc}",
            )


__all__ = ["SelfCheckItem", "SelfCheckReport", "StartupSelfCheck"]
