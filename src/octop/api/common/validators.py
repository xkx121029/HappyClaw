"""Cross-router request validation helpers (no FastAPI route definitions)."""

from __future__ import annotations

from typing import Any

from octop.infra.errors import ErrorCode, OctopError
from octop.infra.gateway.process.turn_selection import (
    validate_chat_mcp_servers,
    validate_chat_skills,
)
from octop.infra.users.resource_policy import raise_if_backend_outside_user_root
from octop.infra.utils.host_dirs import assert_backend_root_dirs_allowed

__all__ = [
    "assert_user_backend_root_dirs",
    "validate_chat_mcp_servers",
    "validate_chat_skills",
]


def assert_user_backend_root_dirs(
    user: Any,
    backend: Any,
    *,
    policy_repo: Any | None = None,
) -> None:
    """Reject local backend ``root_dir`` values that fail denylist or user policy.

    When *policy_repo* is provided, explicit ``local_shell`` / ``filesystem``
    roots must stay under the user's ``workspace_root_dir`` (if set). A missing
    root or the host filesystem root is left for create/update to snap onto
    that directory. All authenticated users may otherwise select host paths
    outside home (UI still defaults to home). Sensitive pseudo-fs mounts remain
    blocked.
    """
    if backend is None:
        return
    if policy_repo is not None and user is not None:
        raise_if_backend_outside_user_root(policy_repo, int(user.id), backend)
        return
    try:
        assert_backend_root_dirs_allowed(backend, restrict_to_home=False)
    except ValueError as exc:
        raise OctopError(ErrorCode.WORKSPACE_OP_UNSUPPORTED, str(exc)) from exc
