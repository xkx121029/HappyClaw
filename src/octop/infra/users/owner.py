"""Single-user (local owner) identity resolution.

HappyClaw is a single-user local tool: there is no login, no account switch and
no multi-tenant isolation. Every local request — regardless of browser tab or
port — is served as the one local owner.

``OwnerIdentityService`` is the single place that maps "the user" to a real
``users`` row so that legacy ``user_id`` columns and foreign keys stay valid:

1. ``local_owner`` row (written by migration 026 / first boot);
2. otherwise adopt an existing active admin (lowest id);
3. otherwise adopt the lowest active user;
4. otherwise create ``local-owner`` (no password, role ``admin``).

No row is ever deleted or rewritten by this service, so old multi-account data
survives the transition untouched.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from octop.infra.errors import ErrorCode, OctopError
from octop.infra.users.identity import Role, User
from octop.infra.users.permissions import PERMISSIONS

if TYPE_CHECKING:
    from octop.infra.db.services import SharedServices

logger = logging.getLogger(__name__)

OWNER_USERNAME = "local-owner"
OWNER_DISPLAY_NAME = "本机使用者"
LOCAL_OWNER_TABLE = "local_owner"


class OwnerIdentityService:
    """Resolve and cache the one local owner of this installation."""

    def __init__(self, services: SharedServices) -> None:
        self._services = services
        self._cached: User | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def owner(self) -> User:
        """Return the local owner, resolving it once per services instance."""
        if self._cached is None:
            self._cached = self._resolve()
        return self._cached

    def owner_id(self) -> int:
        return self.owner().id

    def reset_cache(self) -> None:
        """Drop the cached owner (call after swapping the control-plane DB)."""
        self._cached = None

    def ensure(self) -> User:
        """Resolve the owner eagerly; used by server startup."""
        return self.owner()

    # ------------------------------------------------------------------
    # Resolution
    # ------------------------------------------------------------------
    def _resolve(self) -> User:
        try:
            row = self._adopt_or_create()
        except OctopError:
            raise
        except Exception as exc:  # pragma: no cover - defensive boundary
            logger.exception("single-user owner resolution failed")
            raise OctopError(
                ErrorCode.SINGLE_USER_INIT_FAILED,
                "single-user owner initialization failed; existing data was preserved",
            ) from exc

        display = row.display_name or OWNER_DISPLAY_NAME
        user = User(
            id=row.id,
            username=row.username,
            role=Role.ADMIN,
            display_name=display,
            locale=row.locale or "zh",
            # Module permissions are not enforced in single-user mode, but the
            # dashboard reads this list for feature flags.
            permissions=sorted(PERMISSIONS),
        )
        logger.info(
            "single-user owner resolved: id=%s username=%s source=%s",
            user.id,
            user.username,
            getattr(row, "source", "users"),
        )
        return user

    def _adopt_or_create(self) -> Any:
        recorded = self._recorded_owner_id()
        if recorded is not None:
            row = self._services.user_repo.get(recorded)
            if row is not None and not row.disabled:
                return row
            logger.warning(
                "local_owner points at missing or disabled user %s; re-adopting", recorded
            )

        adopted = self._first_active_user()
        if adopted is None:
            adopted = self._create_owner()
        self._record_owner(adopted.id, source="adopted")
        return adopted

    def _recorded_owner_id(self) -> int | None:
        try:
            with self._services.db.connect() as conn:
                row = conn.execute(
                    f"SELECT user_id FROM {LOCAL_OWNER_TABLE} ORDER BY adopted_at ASC, user_id ASC "
                    "LIMIT 1"
                ).fetchone()
        except Exception:
            # Table missing on very old databases before migration 026 runs.
            return None
        return int(row["user_id"]) if row is not None else None

    def _first_active_user(self) -> Any:
        repo = self._services.user_repo
        admins = [r for r in repo.list() if r.role == Role.ADMIN]
        if admins:
            return admins[0]
        rows = repo.list()
        return rows[0] if rows else None

    def _create_owner(self) -> Any:
        repo = self._services.user_repo
        user_id = repo.create(
            username=OWNER_USERNAME,
            password_hash=None,
            role=Role.ADMIN,
            display_name=OWNER_DISPLAY_NAME,
            locale="zh",
            permissions=sorted(PERMISSIONS),
        )
        logger.info("created local owner user id=%s username=%s", user_id, OWNER_USERNAME)
        row = repo.get(user_id)
        if row is None:  # pragma: no cover - defensive
            raise RuntimeError("failed to create local owner user")
        return row

    def _record_owner(self, user_id: int, *, source: str) -> None:
        from octop.infra.db.repos._base import now_ts  # noqa: PLC0415

        try:
            with self._services.db.transaction() as conn:
                existing = conn.execute(
                    f"SELECT user_id FROM {LOCAL_OWNER_TABLE} LIMIT 1"
                ).fetchone()
                if existing is not None and int(existing["user_id"]) == user_id:
                    return
                if existing is not None:
                    conn.execute(
                        f"UPDATE {LOCAL_OWNER_TABLE} SET user_id = ?, adopted_at = ?, source = ?",
                        (user_id, now_ts(), source),
                    )
                    return
                conn.execute(
                    f"INSERT INTO {LOCAL_OWNER_TABLE}(user_id, adopted_at, source) "
                    "VALUES (?, ?, ?)",
                    (user_id, now_ts(), source),
                )
        except Exception:
            # Migration owns the table on old databases; never fail a request
            # because the marker could not be written.
            logger.exception("failed to persist local_owner marker for user %s", user_id)
