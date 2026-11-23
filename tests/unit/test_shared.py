"""tests/unit/test_shared.py"""

from __future__ import annotations

from pathlib import Path

from happyclaw.config import HappyclawConfig
from happyclaw.infra.db.migrate import run_migrations
from happyclaw.infra.db.pool import SqlitePool
from happyclaw.infra.db.repos.sso import SsoRepo
from happyclaw.infra.db.services import SharedServices, build_shared_services
from happyclaw.infra.utils.paths import PathLayout


def test_build_shared_services(tmp_path: Path):
    cfg = HappyclawConfig()
    paths = PathLayout(tmp_path / ".octop")
    paths.ensure_root()
    db = SqlitePool(paths.db)
    run_migrations(db)
    services = build_shared_services(db=db, paths=paths, config=cfg)
    assert isinstance(services, SharedServices)
    assert services.db is db
    assert services.paths is paths
    assert services.config is cfg
    # all repos resolved
    assert services.user_repo.count() == 0
    assert isinstance(services.sso_repo, SsoRepo)
