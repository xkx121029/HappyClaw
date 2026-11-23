"""Recovery code atomic single-spend."""

from __future__ import annotations

from pathlib import Path

import pytest

from happyclaw.infra.auth.mfa import recovery as recovery_mod
from happyclaw.infra.db.migrate import run_migrations
from happyclaw.infra.db.pool import SqlitePool
from happyclaw.infra.db.repos.user_recovery_codes import UserRecoveryCodeRepo
from happyclaw.infra.db.repos.users import UserRepo
from happyclaw.infra.users.password import hash_password


@pytest.fixture()
def repo(tmp_path: Path):
    pool = SqlitePool(tmp_path / "octop.db")
    run_migrations(pool)
    users = UserRepo(pool)
    uid = users.create(
        username="alice",
        password_hash=hash_password("Password1"),
        role="user",
    )
    return uid, UserRecoveryCodeRepo(pool)


def test_recovery_atomic_double_spend(repo) -> None:
    uid, codes_repo = repo
    plain = recovery_mod.issue_codes(codes_repo, uid)
    assert len(plain) == recovery_mod.RECOVERY_CODE_COUNT
    code = plain[0]
    assert recovery_mod.try_spend_code(codes_repo, uid, code)
    assert not recovery_mod.try_spend_code(codes_repo, uid, code)
    assert codes_repo.count_unused(uid) == recovery_mod.RECOVERY_CODE_COUNT - 1
