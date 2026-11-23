"""TOTP enroll / verify / replay protection."""

from __future__ import annotations

from pathlib import Path

import pyotp
import pytest

from happyclaw.infra.auth.mfa import totp as totp_mod
from happyclaw.infra.db.migrate import run_migrations
from happyclaw.infra.db.pool import SqlitePool
from happyclaw.infra.db.repos.secrets import SecretRepo
from happyclaw.infra.db.repos.user_totp import UserTotpRepo
from happyclaw.infra.db.repos.users import UserRepo
from happyclaw.infra.users.password import hash_password


@pytest.fixture()
def services(tmp_path: Path):
    pool = SqlitePool(tmp_path / "octop.db")
    run_migrations(pool)
    users = UserRepo(pool)
    uid = users.create(
        username="alice",
        password_hash=hash_password("Password1"),
        role="user",
    )
    return {
        "pool": pool,
        "user_id": uid,
        "totp": UserTotpRepo(pool),
        "secrets": SecretRepo(pool),
    }


def test_totp_enroll_confirm_and_replay(services) -> None:
    totp_repo = services["totp"]
    secrets = services["secrets"]
    uid = services["user_id"]
    begun = totp_mod.begin_enroll(totp_repo, secrets, uid, username="alice")
    secret = str(begun["secret"])
    code = pyotp.TOTP(secret).now()
    assert totp_mod.confirm_enroll(totp_repo, secrets, uid, code)
    row = totp_repo.get_by_user(uid)
    assert row is not None and row.is_verified
    # Enroll does not consume the step — first login may reuse the same code.
    assert totp_mod.verify_for_user(totp_repo, secrets, uid, code)
    # Login verify consumes the step; same code must not work again.
    assert not totp_mod.verify_for_user(totp_repo, secrets, uid, code)
    # Pending TOTP does not count as verified before confirm.
    totp_repo.delete(uid)
    totp_mod.begin_enroll(totp_repo, secrets, uid, username="alice")
    pending = totp_repo.get_by_user(uid)
    assert pending is not None and not pending.is_verified
