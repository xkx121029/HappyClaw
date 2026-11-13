"""Setup wizard database step API tests."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from octop.config import DatabaseConfig, OctopConfig, load_config
from octop.infra.db.factory import open_database
from octop.infra.db.migrate import run_migrations
from octop.infra.db.repos.users import UserRepo
from octop.infra.utils.paths import PathLayout
from tests.support.app import octop_client
from tests.support.auth import bootstrap_admin


def _seed_occupied_sqlite(home, *, relative_path: str = "occupied.db") -> None:
    """Create a sibling SQLite control-plane DB that already has one user."""
    paths = PathLayout(home)
    cfg = OctopConfig(
        database=DatabaseConfig(driver="sqlite", sqlite_path=relative_path),
        database_in_file=True,
    )
    db = open_database(cfg, paths)
    try:
        run_migrations(db)
        UserRepo(db).create(username="existing", password_hash="x", role="admin")
    finally:
        db.close()


@pytest.mark.asyncio
async def test_setup_database_sqlite_bind(patched_app_client) -> None:
    """The read-only probe stays; the wizard rebind step is retired."""
    client, srv, home = patched_app_client
    before = load_config(home / "config.json")

    r = await client.post(
        "/api/setup/test-database",
        json={"driver": "sqlite", "sqlite_path": "data/wizard.db"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True

    r = await client.post(
        "/api/setup/database",
        json={"driver": "sqlite", "sqlite_path": "data/wizard.db"},
    )
    assert r.status_code == 400, r.text
    assert r.json()["error"]["code"] == "SINGLE_USER_UNSUPPORTED"

    after = load_config(home / "config.json")
    assert after.database.sqlite_path == before.database.sqlite_path
    assert not (home / "data" / "wizard.db").exists()

    status = await client.get("/api/setup/status")
    assert status.json()["database_driver"] == "sqlite"
    assert status.json()["database_bound"] is True

    # Runtime stores must still use the live pool.
    assert srv.app_runtime is not None
    list(srv.app_runtime.agent_registry.providers.iter_usable_rows())
    assert srv.services.db is srv.app_runtime.agent_registry._providers._provider_repo._db  # noqa: SLF001


@pytest.mark.asyncio
async def test_deferred_verify_password_then_bind(tmp_octop_home: Path) -> None:
    """Single-user boot always binds SQLite; there is no deferred wizard path."""
    async with octop_client(tmp_octop_home, bind_database=False) as (client, srv):
        assert srv.database_bound is True
        assert (tmp_octop_home / "octop.db").exists()

        status = await client.get("/api/setup/status")
        assert status.status_code == 200
        body = status.json()
        assert body["setup_required"] is False
        assert body["database_bound"] is True
        assert body["database_driver"] == "sqlite"

        health = await client.get("/api/health")
        assert health.status_code == 200
        assert health.json()["db"] is True

        verified = await client.post("/api/setup/verify-password", json={"password": "x"})
        assert verified.status_code == 400
        assert verified.json()["error"]["code"] == "SINGLE_USER_UNSUPPORTED"

        applied = await client.post(
            "/api/setup/database",
            json={"driver": "sqlite", "sqlite_path": "octop.db"},
        )
        assert applied.status_code == 400
        assert applied.json()["error"]["code"] == "SINGLE_USER_UNSUPPORTED"
        assert srv.database_bound is True


@pytest.mark.asyncio
async def test_setup_database_refuses_nonempty_target(patched_app_client) -> None:
    """The wizard never adopts a pre-filled control-plane DB; the route is retired."""
    client, srv, home = patched_app_client
    _seed_occupied_sqlite(home)
    before = load_config(home / "config.json")

    probed = await client.post(
        "/api/setup/test-database",
        json={"driver": "sqlite", "sqlite_path": "occupied.db"},
    )
    assert probed.status_code == 200, probed.text
    assert probed.json()["user_count"] == 1

    r = await client.post(
        "/api/setup/database",
        json={"driver": "sqlite", "sqlite_path": "occupied.db", "adopt_existing": True},
    )
    assert r.status_code == 400, r.text
    assert r.json()["error"]["code"] == "SINGLE_USER_UNSUPPORTED"

    after = load_config(home / "config.json")
    assert after.database.sqlite_path == before.database.sqlite_path

    created = await client.post(
        "/api/setup/initial-admin",
        json={"username": "admin", "password": "TestPass12"},
        headers={"Authorization": "Bearer local-owner"},
    )
    assert created.status_code == 400, created.text
    assert created.json()["error"]["code"] == "SINGLE_USER_UNSUPPORTED"
    assert srv.database_bound is True


@pytest.mark.asyncio
async def test_setup_database_refused_after_admin(patched_app_client) -> None:
    client, _srv, home = patched_app_client
    await bootstrap_admin(client, home)
    r = await client.post(
        "/api/setup/database",
        json={"driver": "sqlite", "sqlite_path": "octop.db"},
    )
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "SINGLE_USER_UNSUPPORTED"


_ADOPT_DB = "octop_wizard_adopt"
_DATABASE_ENV = (
    "OCTOP_DATABASE_URL",
    "OCTOP_DATABASE_DRIVER",
    "OCTOP_DATABASE_SQLITE_PATH",
    "OCTOP_DATABASE_HOST",
    "OCTOP_DATABASE_PORT",
    "OCTOP_DATABASE_NAME",
    "OCTOP_DATABASE_USER",
    "OCTOP_DATABASE_PASSWORD",
)


def _recreate_adopt_database(url: str) -> str:
    """Create a throwaway database on the same server. Does not touch ``url``'s database."""
    import psycopg
    from psycopg.conninfo import conninfo_to_dict, make_conninfo

    info = conninfo_to_dict(url)
    info["dbname"] = "postgres"
    with psycopg.connect(make_conninfo(**info), autocommit=True) as conn:
        conn.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            "WHERE datname = %s AND pid <> pg_backend_pid()",
            (_ADOPT_DB,),
        )
        conn.execute(f"DROP DATABASE IF EXISTS {_ADOPT_DB}")
        conn.execute(f"CREATE DATABASE {_ADOPT_DB}")
    info["dbname"] = _ADOPT_DB
    return make_conninfo(**info)


def _drop_adopt_database(url: str) -> None:
    import psycopg
    from psycopg.conninfo import conninfo_to_dict, make_conninfo

    info = conninfo_to_dict(url)
    info["dbname"] = "postgres"
    with psycopg.connect(make_conninfo(**info), autocommit=True) as conn:
        conn.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            "WHERE datname = %s AND pid <> pg_backend_pid()",
            (_ADOPT_DB,),
        )
        conn.execute(f"DROP DATABASE IF EXISTS {_ADOPT_DB}")


@pytest.mark.asyncio
@pytest.mark.postgresql
async def test_setup_postgresql_adopts_existing_users(tmp_octop_home: Path, monkeypatch) -> None:
    """PostgreSQL setup can keep an existing admin after confirmation. SQLite cannot."""
    url = os.environ.get("OCTOP_TEST_DATABASE_URL")
    if not url:
        pytest.skip("set OCTOP_TEST_DATABASE_URL to run PostgreSQL tests")
    for key in _DATABASE_ENV:
        monkeypatch.delenv(key, raising=False)

    from psycopg.conninfo import conninfo_to_dict

    from octop.infra.db.pool import PostgresPool
    from octop.infra.users.password import hash_password

    try:
        adopt_url = _recreate_adopt_database(url)
    except Exception as exc:
        pytest.skip(f"cannot create throwaway database {_ADOPT_DB}: {exc}")

    try:
        pool = PostgresPool(adopt_url)
        try:
            run_migrations(pool)
            UserRepo(pool).create(
                username="existing",
                password_hash=hash_password("TestPass12"),
                role="admin",
            )
        finally:
            pool.close()

        info = conninfo_to_dict(adopt_url)
        body = {
            "driver": "postgresql",
            "host": info.get("host") or "127.0.0.1",
            "port": int(info.get("port") or 5432),
            "database": info["dbname"],
            "user": info.get("user") or "postgres",
            "password": info.get("password") or "",
        }
        async with octop_client(tmp_octop_home) as (client, _srv):
            probed = await client.post("/api/setup/test-database", json=body)
            assert probed.status_code == 200, probed.text
            assert probed.json()["user_count"] == 1

            refused = await client.post("/api/setup/database", json=body)
            assert refused.status_code == 400, refused.text
            assert refused.json()["error"]["code"] == "SINGLE_USER_UNSUPPORTED"
            assert load_config(tmp_octop_home / "config.json").database.is_sqlite

            adopted = await client.post(
                "/api/setup/database",
                json={**body, "adopt_existing": True},
            )
            assert adopted.status_code == 400, adopted.text
            assert adopted.json()["error"]["code"] == "SINGLE_USER_UNSUPPORTED"

            status = await client.get("/api/setup/status")
            assert status.json()["setup_required"] is False
            assert status.json()["database_driver"] == "sqlite"

            login = await client.post(
                "/api/auth/login",
                json={"username": "existing", "password": "TestPass12"},
            )
            assert login.status_code != 500, login.text
    finally:
        _drop_adopt_database(url)
