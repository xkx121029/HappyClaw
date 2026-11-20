"""SSO, invites, user roles and role seeding repairs."""

from __future__ import annotations

import json
import time

from octop.infra.db.migrate.introspect import (
    _drop_column,
    _ensure_column,
    _table_columns,
    _table_exists,
)
from octop.infra.db.pool import DatabasePool


def _ensure_sso_oidc_schema(db: DatabasePool) -> None:
    """Apply OIDC SSO tables and nullable password_hash (SQLite users rebuild)."""
    if _table_exists(db, "sso_providers"):
        return
    with db.connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS sso_providers (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              enabled INTEGER NOT NULL DEFAULT 0,
              display_name TEXT NOT NULL DEFAULT '',
              issuer TEXT NOT NULL DEFAULT '',
              client_id TEXT NOT NULL DEFAULT '',
              client_secret_enc BLOB,
              scopes TEXT NOT NULL DEFAULT 'openid profile email',
              dashboard_origin TEXT,
              kind TEXT NOT NULL DEFAULT 'oidc',
              extra TEXT NOT NULL DEFAULT '{}',
              created_at INTEGER NOT NULL,
              updated_at INTEGER NOT NULL
            );
            CREATE UNIQUE INDEX IF NOT EXISTS idx_sso_providers_kind ON sso_providers(kind);

            CREATE TABLE IF NOT EXISTS sso_login_states (
              state TEXT PRIMARY KEY,
              provider_id INTEGER NOT NULL REFERENCES sso_providers(id) ON DELETE CASCADE,
              nonce TEXT NOT NULL,
              code_verifier TEXT NOT NULL,
              redirect_after TEXT NOT NULL DEFAULT '/chat',
              login_code TEXT,
              user_id INTEGER,
              expires_at INTEGER NOT NULL,
              consumed_at INTEGER,
              created_at INTEGER NOT NULL
            );

            CREATE UNIQUE INDEX IF NOT EXISTS idx_sso_login_states_login_code
              ON sso_login_states(login_code) WHERE login_code IS NOT NULL;

            PRAGMA foreign_keys = OFF;

            CREATE TABLE users_new (
              id                  INTEGER PRIMARY KEY AUTOINCREMENT,
              username            TEXT NOT NULL,
              password_hash       TEXT,
              role                TEXT NOT NULL,
              display_name        TEXT,
              disabled            INTEGER NOT NULL DEFAULT 0,
              locale              TEXT NOT NULL DEFAULT 'zh',
              created_at          INTEGER NOT NULL,
              login_failed_count  INTEGER NOT NULL DEFAULT 0,
              login_locked_until  INTEGER NOT NULL DEFAULT 0,
              preferences_json    TEXT NOT NULL DEFAULT '{}',
              email               TEXT,
              sso_provider_id     INTEGER REFERENCES sso_providers(id),
              sso_subject         TEXT,
              permissions         TEXT NOT NULL DEFAULT '[]'
            );

            INSERT INTO users_new (
              id,
              username,
              password_hash,
              role,
              display_name,
              disabled,
              locale,
              created_at,
              login_failed_count,
              login_locked_until,
              preferences_json,
              permissions
            )
            SELECT
              id,
              username,
              password_hash,
              role,
              display_name,
              disabled,
              locale,
              created_at,
              login_failed_count,
              login_locked_until,
              preferences_json,
              '[]'
            FROM users;

            DROP TABLE users;
            ALTER TABLE users_new RENAME TO users;

            CREATE UNIQUE INDEX IF NOT EXISTS idx_users_username ON users(username);
            CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email
              ON users(email) WHERE email IS NOT NULL AND email != '';
            CREATE UNIQUE INDEX IF NOT EXISTS idx_users_sso
              ON users(sso_provider_id, sso_subject)
              WHERE sso_provider_id IS NOT NULL AND sso_subject IS NOT NULL;

            PRAGMA foreign_keys = ON;
            """
        )


def _ensure_sso_provider_kind_schema(db: DatabasePool) -> None:
    """Add kind/extra columns and unique-kind index on existing SSO provider tables."""
    if not _table_exists(db, "sso_providers"):
        return
    _ensure_column(db, "sso_providers", "kind", "TEXT NOT NULL DEFAULT 'oidc'")
    _ensure_column(db, "sso_providers", "extra", "TEXT NOT NULL DEFAULT '{}'")
    with db.connect() as conn:
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_sso_providers_kind ON sso_providers(kind)"
        )
    _ensure_user_sso_identities_schema(db)


def _ensure_user_sso_identities_schema(db: DatabasePool) -> None:
    """Create ``user_sso_identities`` and backfill from legacy ``users.sso_*`` slots."""
    if not _table_exists(db, "users") or not _table_exists(db, "sso_providers"):
        return
    if db.dialect == "postgresql":
        with db.connect() as conn, conn.transaction():
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS user_sso_identities (
                  id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
                  user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                  provider_id BIGINT NOT NULL REFERENCES sso_providers(id) ON DELETE CASCADE,
                  subject TEXT NOT NULL,
                  created_at BIGINT NOT NULL,
                  UNIQUE(user_id, provider_id),
                  UNIQUE(provider_id, subject)
                )
                """
            )
            conn.execute(
                """
                INSERT INTO user_sso_identities (user_id, provider_id, subject, created_at)
                SELECT id, sso_provider_id, sso_subject, created_at
                FROM users
                WHERE sso_provider_id IS NOT NULL AND sso_subject IS NOT NULL
                ON CONFLICT DO NOTHING
                """
            )
        return
    with db.connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS user_sso_identities (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
              provider_id INTEGER NOT NULL REFERENCES sso_providers(id) ON DELETE CASCADE,
              subject TEXT NOT NULL,
              created_at INTEGER NOT NULL,
              UNIQUE(user_id, provider_id),
              UNIQUE(provider_id, subject)
            );
            INSERT OR IGNORE INTO user_sso_identities
              (user_id, provider_id, subject, created_at)
            SELECT id, sso_provider_id, sso_subject, created_at
            FROM users
            WHERE sso_provider_id IS NOT NULL AND sso_subject IS NOT NULL;
            """
        )


def _ensure_user_invites_schema(db: DatabasePool) -> None:
    """Create ``user_invites`` when missing (clamp / repair paths)."""
    if _table_exists(db, "user_invites") or not _table_exists(db, "users"):
        return
    if db.dialect == "postgresql":
        with db.connect() as conn, conn.transaction():
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS user_invites (
                  id                BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
                  code              TEXT NOT NULL UNIQUE,
                  created_by        BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                  note              TEXT,
                  created_at        BIGINT NOT NULL,
                  expires_at        BIGINT NOT NULL,
                  used_at           BIGINT,
                  used_by_user_id   BIGINT REFERENCES users(id) ON DELETE SET NULL,
                  revoked_at        BIGINT
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_user_invites_created_at "
                "ON user_invites(created_at DESC)"
            )
        return
    with db.connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS user_invites (
              id                INTEGER PRIMARY KEY AUTOINCREMENT,
              code              TEXT NOT NULL UNIQUE,
              created_by        INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
              note              TEXT,
              created_at        INTEGER NOT NULL,
              expires_at        INTEGER NOT NULL,
              used_at           INTEGER,
              used_by_user_id   INTEGER REFERENCES users(id) ON DELETE SET NULL,
              revoked_at        INTEGER
            );
            CREATE INDEX IF NOT EXISTS idx_user_invites_created_at
              ON user_invites(created_at DESC);
            """
        )


def _ensure_user_role_schema(db: DatabasePool) -> None:
    """Role templates; users.role / user_invites.role store the template id (v18)."""
    if not _table_exists(db, "users"):
        return
    _ensure_column(db, "users", "role_name", "TEXT")
    _ensure_column(db, "users", "avatar_icon", "TEXT")
    _fold_users_user_role_id_into_role(db)
    if _table_exists(db, "user_invites"):
        _ensure_column(db, "user_invites", "role_name", "TEXT")
        _ensure_column(db, "user_invites", "role", "TEXT")
        _fold_invites_user_role_id_into_role(db)
        for column in (
            "system_role",
            "permissions",
            "workspace_root_dir",
            "token_quota",
            "max_agents",
            "user_role_id",
        ):
            _drop_column(db, "user_invites", column)
    if _table_exists(db, "access_roles"):
        with db.connect() as conn:
            conn.execute("DROP TABLE access_roles")
    if not _table_exists(db, "user_role"):
        _create_user_role_table(db)
    _ensure_column(db, "user_role", "description", "TEXT")
    _ensure_column(db, "user_role", "avatar_icon", "TEXT")
    _seed_user_roles(db)


def _fold_users_user_role_id_into_role(db: DatabasePool) -> None:
    """Promote legacy users.user_role_id into users.role, then drop the column.

    Custom template ids overwrite role; admin/user ids already match the privilege
    strings used before this fold.
    """
    if "user_role_id" not in _table_columns(db, "users"):
        return
    with db.transaction() as conn:
        conn.execute(
            "UPDATE users SET role = user_role_id "
            "WHERE user_role_id IS NOT NULL AND TRIM(user_role_id) != ''"
        )
    _drop_column(db, "users", "user_role_id")


def _fold_invites_user_role_id_into_role(db: DatabasePool) -> None:
    """Copy legacy user_invites.user_role_id into user_invites.role when empty."""
    cols = _table_columns(db, "user_invites")
    if "user_role_id" not in cols or "role" not in cols:
        return
    with db.transaction() as conn:
        conn.execute(
            "UPDATE user_invites SET role = user_role_id "
            "WHERE (role IS NULL OR TRIM(role) = '') "
            "AND user_role_id IS NOT NULL AND TRIM(user_role_id) != ''"
        )


def _create_user_role_table(db: DatabasePool) -> None:
    if db.dialect == "postgresql":
        with db.connect() as conn, conn.transaction():
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS user_role (
                  id              BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
                  user_role_id    TEXT NOT NULL UNIQUE,
                  user_role_name  TEXT NOT NULL UNIQUE,
                  description     TEXT,
                  permissions     TEXT NOT NULL DEFAULT '[]',
                  policies        TEXT NOT NULL DEFAULT '[]',
                  avatar_icon     TEXT,
                  created_at      BIGINT NOT NULL,
                  updated_at      BIGINT NOT NULL
                )
                """
            )
        return
    with db.connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS user_role (
              id              INTEGER PRIMARY KEY AUTOINCREMENT,
              user_role_id    TEXT NOT NULL UNIQUE,
              user_role_name  TEXT NOT NULL UNIQUE,
              description     TEXT,
              permissions     TEXT NOT NULL DEFAULT '[]',
              policies        TEXT NOT NULL DEFAULT '[]',
              avatar_icon     TEXT,
              created_at      INTEGER NOT NULL,
              updated_at      INTEGER NOT NULL
            );
            """
        )


def _seed_user_roles(db: DatabasePool) -> None:
    """Ensure locked built-in admin and user role templates exist.

    Both ids are immutable product constants matching ``users.role`` values.
    Existing users are never rewritten.
    """
    if not _table_exists(db, "user_role"):
        return
    from octop.infra.users.permissions import BASELINE_PERMISSIONS

    ts = int(time.time())
    with db.connect() as conn:
        admin = conn.execute(
            "SELECT id FROM user_role WHERE user_role_id = ?",
            ("admin",),
        ).fetchone()
    if admin is None:
        with db.transaction() as conn:
            conn.execute(
                "INSERT INTO user_role("
                "user_role_id, user_role_name, permissions, policies, created_at, updated_at"
                ") VALUES ('admin', ?, '[]', '[]', ?, ?)",
                ("管理员", ts, ts),
            )
    with db.connect() as conn:
        user = conn.execute(
            "SELECT id FROM user_role WHERE user_role_id = ?",
            ("user",),
        ).fetchone()
    if user is None:
        payload = json.dumps(sorted(BASELINE_PERMISSIONS), ensure_ascii=False)
        with db.transaction() as conn:
            conn.execute(
                "INSERT INTO user_role("
                "user_role_id, user_role_name, permissions, policies, created_at, updated_at"
                ") VALUES ('user', ?, ?, '[]', ?, ?)",
                ("用户", payload, ts, ts),
            )
