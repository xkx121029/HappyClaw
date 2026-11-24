"""ACL gate coverage: every route module is gated or explicitly exempt.

Discovery is automatic. Any module under ``api/routers`` that declares a route
(a ``@router.get/post/...`` decorator or a ``router.add_api_route`` call) must
appear in ``GATED_FILES`` — where it is asserted to call a permission check —
or in ``EXEMPT_FILES`` with a written reason. A route module registered in
neither fails the guard and is reported with the routes it declares, so a new
router file can no longer be skipped in silence.
"""

from __future__ import annotations

import ast
import pathlib

from happyclaw.infra.users.permissions import ALL_PERMISSION_KEYS

API_ROOT = pathlib.Path("src/happyclaw/api")
ROUTER_ROOT = API_ROOT / "routers"

ROUTE_METHODS = frozenset(
    {"get", "post", "put", "patch", "delete", "head", "options", "trace", "websocket", "api_route"}
)
ROUTE_REGISTRARS = frozenset({"add_api_route", "add_api_websocket_route"})

IDENTITY_MARKERS = (
    "current_user",
    "resolve_user_from_token",
    "verify_internal_token",
    "user.id",
    "owner_id",
    "require_admin",
    "user_has_permission",
    "is_admin",
    "_owned",
)

GATED_FILES = [
    "routers/users.py",
    "routers/admin.py",
    "routers/backup.py",
    "routers/security.py",
    "routers/providers.py",
    "routers/voice.py",
    "routers/storage_backends.py",
    "routers/envs.py",
    "routers/settings.py",
    "routers/observability.py",
    "routers/tls.py",
    "routers/update.py",
    "routers/search.py",
    "routers/ollama_models.py",
    "routers/onnx_models.py",
    "routers/connectors/cli_auth.py",
    "routers/bridge.py",
    "routers/knowledge_bases/bases.py",
    "routers/knowledge_bases/documents.py",
    "routers/knowledge_bases/feature.py",
    "routers/browser/uninstall.py",
    "routers/browser/env.py",
    "routers/desktop/install.py",
    "routers/desktop/uninstall.py",
    "routers/desktop/status.py",
    "routers/desktop/settings.py",
    "routers/desktop/stream.py",
    "routers/mobile/install.py",
    "routers/mobile/status.py",
    "routers/mobile/stream.py",
    "routers/mobile/shell_ws.py",
    "routers/plugins.py",
    "routers/agents.py",
    "routers/channels.py",
    "routers/skills/crud.py",
    "routers/skills/hub.py",
    "routers/skills/package_mounts.py",
    "routers/skills/transfer.py",
    "routers/skill_packages/crud.py",
    "routers/skill_packages/hub.py",
    "routers/skill_packages/skills.py",
    "routers/memory.py",
    "routers/memory_storage.py",
    "routers/memory_portable.py",
    "routers/mbti.py",
    "routers/agent_tools.py",
    "routers/agent_files.py",
    "routers/subagents.py",
    "routers/terminal.py",
    "routers/acp.py",
    "routers/decision.py",
    "routers/user_groups.py",
    "routers/media_generation.py",
]

EXEMPT_FILES = {
    # Answer before an identity exists (login, first-run setup, probes).
    "routers/health.py": "liveness and readiness probes, mounted pre-login with no user identity",
    "routers/i18n.py": "translation catalog for the login screen; read-only, holds no user state",
    "routers/runtime.py": "runtime/build banner needed by the dashboard shell before login",
    "routers/setup.py": "first-run setup wizard; must answer while no account exists yet",
    "routers/auth.py": "login and token endpoints establish identity, so they cannot require it",
    "routers/auth_device.py": "device pairing codes are authenticated by the pairing secret itself",
    # Authenticate without a module permission key (internal token, caller-owned data).
    "routers/internal_mcp.py": "internal MCP transport; every route verifies an instance token",
    "routers/agent_mcp.py": "per-user agent MCP config; all routes depend on current_user",
    "routers/browser/harness.py": "per-user browser harness sessions, scoped by user id and ownership",
    "routers/browser/record_replay.py": "per-user recordings; each route resolves the owning row first",
    "routers/browser/stream.py": "websocket stream; identity from resolve_user_from_token, scoped by user id",
    "routers/chat/history.py": "per-user chat history; routes depend on current_user and filter by user id",
    "routers/chat/notify_ws.py": "notification websocket bound to the caller's own sessions",
    "routers/chat/routes.py": "per-user chat route and model listing",
    "routers/chat/trajectory.py": "per-user turn trajectories; routes depend on current_user",
    "routers/chat/ws.py": "dashboard chat websocket; identity from resolve_user_from_token, threads filtered by user id",
    "routers/cloud.py": "per-user cloud task surface; every route depends on current_user",
    "routers/connectors/catalog.py": "read-only catalog of built-in connectors",
    "routers/connectors/credentials.py": "per-user connector credentials, current_user scoped",
    "routers/connectors/custom_mcp.py": "per-user custom MCP servers, scoped by the calling user id",
    "routers/connectors/instances.py": "per-user connector instances, scoped by owner id",
    "routers/connectors/oauth.py": "per-user OAuth start/callback for the caller's own connector",
    "routers/cron.py": "per-user scheduled jobs, current_user with user id scoping",
    "routers/experts.py": "expert templates and market; every mutation goes through *_owned helpers",
    "routers/filesystem.py": "per-user filesystem browsing; every route depends on current_user",
    "routers/preferences.py": "per-user UI preferences, written under the caller's user id",
    "routers/proactive_care.py": "per-user proactive-care settings",
    "routers/slash.py": "per-user slash-command listing",
    "routers/teams.py": "per-user teams, ownership enforced by _owned helpers",
    "routers/text_assist.py": "per-user text assist call",
    "routers/uploads.py": "per-user uploads, stored with the caller's owner id",
    "routers/usage.py": "per-user usage view; is_admin only widens to the local owner's data",
    "routers/workspace.py": "per-user workspace files; every route depends on current_user",
}

PUBLIC_ROUTER_FILES = frozenset(
    {
        "routers/health.py",
        "routers/i18n.py",
        "routers/runtime.py",
        "routers/setup.py",
        "routers/auth.py",
        "routers/auth_device.py",
    }
)


def _route_label(method: str, call: ast.AST) -> str:
    verb = "ROUTE" if method in ROUTE_REGISTRARS else method.upper()
    if (
        isinstance(call, ast.Call)
        and call.args
        and isinstance(call.args[0], ast.Constant)
        and isinstance(call.args[0].value, str)
    ):
        return f"{verb} {call.args[0].value}"
    return verb


def _route_declarations(tree: ast.AST) -> tuple[str, ...]:
    routes: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for decorator in node.decorator_list:
                target = decorator.func if isinstance(decorator, ast.Call) else decorator
                if isinstance(target, ast.Attribute) and target.attr in ROUTE_METHODS:
                    routes.add(_route_label(target.attr, decorator))
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in ROUTE_REGISTRARS
        ):
            routes.add(_route_label(node.func.attr, node))
    return tuple(sorted(routes))


def _discover_route_modules(root: pathlib.Path = ROUTER_ROOT) -> dict[str, tuple[str, ...]]:
    """Every module under ``root`` that declares a route, keyed as ``routers/<path>.py``."""
    discovered: dict[str, tuple[str, ...]] = {}
    for path in sorted(root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        routes = _route_declarations(tree)
        if routes:
            discovered[path.relative_to(root.parent).as_posix()] = routes
    return discovered


def _unregistered(discovered: dict[str, tuple[str, ...]]) -> list[str]:
    return sorted(set(discovered) - set(GATED_FILES) - set(EXEMPT_FILES))


def test_no_current_admin_symbol_remains() -> None:
    hits: list[str] = []
    for path in API_ROOT.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and node.id == "current_admin":
                hits.append(str(path))
    assert not hits, f"current_admin still referenced in: {hits}"


def test_every_route_module_is_gated_or_exempt() -> None:
    discovered = _discover_route_modules()
    missing = _unregistered(discovered)
    report = "\n".join(f"  {rel}: {', '.join(discovered[rel])}" for rel in missing)
    assert not missing, (
        f"{len(missing)} route module(s) are in neither GATED_FILES nor EXEMPT_FILES."
        " Gate the routes and add the module to GATED_FILES, or add it to EXEMPT_FILES"
        f" with a written reason:\n{report}"
    )


def test_discovery_flags_an_unregistered_route_module(tmp_path: pathlib.Path) -> None:
    """Negative control: a new route module nobody registered must be reported."""
    sample = tmp_path / "routers" / "brand_new.py"
    sample.parent.mkdir()
    sample.write_text(
        "from fastapi import APIRouter\n"
        "\n"
        "router = APIRouter()\n"
        "\n"
        "\n"
        "@router.post('/probe')\n"
        "async def probe() -> dict[str, str]:\n"
        "    return {}\n",
        encoding="utf-8",
    )
    discovered = _discover_route_modules(tmp_path / "routers")
    assert discovered == {"routers/brand_new.py": ("POST /probe",)}
    assert _unregistered(discovered) == ["routers/brand_new.py"]


def test_coverage_lists_are_current() -> None:
    discovered = _discover_route_modules()
    both = sorted(set(GATED_FILES) & set(EXEMPT_FILES))
    assert not both, f"listed as gated and exempt at once: {both}"
    stale = sorted(rel for rel in (*GATED_FILES, *EXEMPT_FILES) if rel not in discovered)
    assert not stale, f"listed but declares no route (renamed or deleted?): {stale}"
    thin = sorted(rel for rel, reason in EXEMPT_FILES.items() if len(reason.strip()) < 20)
    assert not thin, f"exemption without a real reason: {thin}"
    for rel in EXEMPT_FILES:
        if rel in PUBLIC_ROUTER_FILES:
            continue
        src = (API_ROOT / rel).read_text(encoding="utf-8")
        assert any(marker in src for marker in IDENTITY_MARKERS), (
            f"{rel}: exemption rests on caller identity, but the module shows no"
            " identity or authorization check"
        )


def test_gated_files_call_require_permission_with_known_keys() -> None:
    for rel in GATED_FILES:
        src = (API_ROOT / rel).read_text(encoding="utf-8")
        assert "current_admin" not in src
        assert (
            "require_permission(" in src or "user_has_permission(" in src or "require_admin(" in src
        )
        tree = ast.parse(src, filename=rel)
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "require_permission"
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)
            ):
                assert node.args[0].value in ALL_PERMISSION_KEYS, (
                    f"{rel}: unknown key {node.args[0].value!r}"
                )


def test_as_user_still_requires_admin() -> None:
    """Cross-user impersonation must not become a module permission."""
    agent = (API_ROOT / "common/agent.py").read_text(encoding="utf-8")
    usage = (API_ROOT / "routers/usage.py").read_text(encoding="utf-8")
    assert "as_user requires admin" in agent or "is_admin" in agent
    assert "as_user" in usage
