"""Resolve agent ``backend`` config (named refs, composite routes)."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from happyclaw.infra.backend.adapter import row_to_backend_spec

logger = logging.getLogger(__name__)


def default_agent_backend_spec(workspace_dir: Path) -> dict[str, Any]:
    """Harness backend for agents with no explicit ``backend`` in config.

    On POSIX this matches harness ``DEFAULT_BACKEND_SPEC`` (host-rooted virtual
    paths). harness ``resolve_backend(..., workspace_dir=..., system_files_path=...)``
    wraps that host root in a composite whose ``artifacts_root`` is the agent
    workspace system-files prefix (Octop: ``.octop``), so deepagents conversation
    history stays with skills / sessions. On Windows ``root_dir='/'`` resolves to
    the process current-drive root, which often differs from the drive hosting
    ``workspace_dir`` — scope the default to the agent workspace instead.
    """
    from happyclaw_harness.backends import DEFAULT_BACKEND_SPEC  # noqa: PLC0415

    if os.name == "nt":
        return {
            "type": "local_shell",
            "root_dir": str(workspace_dir.resolve()),
            "virtual_mode": True,
        }
    return dict(DEFAULT_BACKEND_SPEC)


def windows_neutralize_host_root(
    spec: Any,
    *,
    workspace_dir: Path,
    agent_id: str | None = None,
) -> Any:
    """Windows: scope local backends so they can reach the agent workspace.

    Two shapes get rewritten to ``workspace_dir``:

    * ``root_dir: "/"`` — the dashboard's default for local backends. On
      Windows it resolves to the *current drive root* (often a different drive
      than the agent workspace), so deepagents virtual-path checks reject every
      workspace path with ``Path ... outside root directory``.
    * a bare drive root on a *different* drive than the workspace (e.g. a
      persisted ``C:/`` while ``OCTOP_HOME`` lives on ``E:``). Those were
      written by the old default-expert bootstrap and can never reach the
      workspace; the original value is logged before the rewrite.

    Only ``root_dir`` is rewritten so ``type`` / ``virtual_mode`` and other
    fields stay intact. Applies to top-level ``local_shell`` / ``filesystem``
    specs and to the ``default`` of composite specs (the default is what
    anchors the agent workspace). Route sub-backends are user-pinned and left
    untouched — a route root of ``/`` is the caller's explicit choice and
    harmless to loading.
    """
    if os.name != "nt":
        return spec
    if not isinstance(spec, dict):
        return spec
    kind = spec.get("type")
    if kind in ("local_shell", "filesystem") and _root_unreachable(
        spec.get("root_dir"), workspace_dir
    ):
        return {**spec, "root_dir": _scoped_root(spec, workspace_dir, agent_id)}
    if (
        kind == "composite"
        and isinstance(spec.get("default"), dict)
        and _root_unreachable(spec["default"].get("root_dir"), workspace_dir)
    ):
        default = spec["default"]
        return {
            **spec,
            "default": {
                **default,
                "root_dir": _scoped_root(default, workspace_dir, agent_id),
            },
        }
    return spec


def _scoped_root(spec: dict[str, Any], workspace_dir: Path, agent_id: str | None) -> str:
    scoped = str(workspace_dir.resolve())
    logger.warning(
        "agent %s backend root_dir %r cannot reach workspace %s on Windows; "
        "scoping the backend to the workspace",
        agent_id or "?",
        spec.get("root_dir"),
        scoped,
    )
    return scoped


def _root_unreachable(root: Any, workspace_dir: Path) -> bool:
    """True when a Windows local root can never contain *workspace_dir*."""
    if _is_host_root(root):
        return True
    drive = _drive_root(root)
    if not drive:
        return False
    return drive != _drive_of(workspace_dir)


def _drive_root(value: Any) -> str:
    """``"c:"`` for a bare drive root (``C:/``, ``C:\\``, ``C:``); else ``""``."""
    text = str(value or "").strip().replace("\\", "/")
    if len(text) in (2, 3) and text[0].isalpha() and text[1] == ":":
        if len(text) == 2 or text[2] == "/":
            return text[:2].lower()
    return ""


def _drive_of(value: Any) -> str:
    """``"e:"`` for anything on that drive (``E:/data``, ``E:\\x``)."""
    text = str(value or "").strip().replace("\\", "/")
    if len(text) >= 2 and text[0].isalpha() and text[1] == ":":
        return text[:2].lower()
    return ""


def _is_host_root(root: Any) -> bool:
    """True when *root* is an explicitly host-rooted local backend path.

    Only an *explicit* ``/``, ``\\`` or empty string counts (the dashboard's
    default). A missing ``root_dir`` is left alone — harness already falls back
    to ``workspace_dir`` for local backends, which is workspace-scoped by
    design.
    """
    return root is not None and str(root).strip() in ("/", "\\", "")


def resolve_agent_backend_spec(
    spec: Any,
    *,
    repo: Any | None,
) -> Any:
    """Expand ``named`` refs (and composite trees) into harness-ready specs."""
    if spec is None:
        return None
    if not isinstance(spec, dict):
        return spec

    kind = spec.get("type")
    if kind == "named":
        name = spec.get("name")
        if not repo or not name:
            raise ValueError("named backend requires a configured storage backend name")
        row = repo.get_by_name(str(name))
        if row is None:
            raise ValueError(f"storage backend {name!r} not found")
        inner = row_to_backend_spec(row)
        if inner is None:
            raise ValueError(f"storage backend {name!r} is incomplete")
        return resolve_agent_backend_spec(inner, repo=repo)

    if kind == "composite":
        default = spec.get("default")
        if default is None:
            raise ValueError("composite backend requires a default sub-spec")
        routes = spec.get("routes") or {}
        if not isinstance(routes, dict):
            raise ValueError("composite backend routes must be a dict")
        return {
            "type": "composite",
            "default": resolve_agent_backend_spec(default, repo=repo),
            "routes": {
                str(prefix): resolve_agent_backend_spec(sub, repo=repo)
                for prefix, sub in routes.items()
            },
        }

    cleaned = dict(spec)
    if kind not in ("named", "composite") and "name" in cleaned:
        del cleaned["name"]
    if kind == "postgres":
        from happyclaw.infra.backend.postgres_spec import normalize_postgres_spec

        return normalize_postgres_spec(cleaned)
    return cleaned


def collect_named_storage_backend_refs(spec: Any) -> set[str]:
    """Collect ``storage_backends.name`` values referenced by an agent backend spec tree."""
    if spec is None:
        return set()
    if isinstance(spec, str):
        if spec.startswith("named:"):
            return {spec.split(":", 1)[1]}
        return set()
    if not isinstance(spec, dict):
        return set()
    kind = spec.get("type")
    if kind == "named":
        name = spec.get("name")
        return {str(name)} if name else set()
    if kind == "composite":
        out: set[str] = set()
        out |= collect_named_storage_backend_refs(spec.get("default"))
        routes = spec.get("routes")
        if isinstance(routes, dict):
            for sub in routes.values():
                out |= collect_named_storage_backend_refs(sub)
        return out
    return set()


def rewrite_named_storage_backend_refs(spec: Any, *, old: str, new: str) -> Any:
    """Return a copy of *spec* with named storage refs rewritten from *old* → *new*."""
    if old == new:
        return spec
    if spec is None:
        return spec
    if isinstance(spec, str):
        if spec == f"named:{old}":
            return f"named:{new}"
        return spec
    if not isinstance(spec, dict):
        return spec
    kind = spec.get("type")
    if kind == "named":
        if spec.get("name") == old:
            return {**spec, "name": new}
        return spec
    if kind == "composite":
        out = dict(spec)
        if "default" in out:
            out["default"] = rewrite_named_storage_backend_refs(
                out.get("default"),
                old=old,
                new=new,
            )
        routes = out.get("routes")
        if isinstance(routes, dict):
            out["routes"] = {
                key: rewrite_named_storage_backend_refs(value, old=old, new=new)
                for key, value in routes.items()
            }
        return out
    return spec


def find_agents_using_storage_backend(
    *,
    agent_repo: Any,
    get_config: Any,
    backend_name: str,
) -> list[dict[str, str]]:
    """Return agents whose ``config.backend`` references *backend_name* (named / composite)."""
    refs: list[dict[str, str]] = []
    for row in agent_repo.list_all():
        cfg = get_config(row.agent_id)
        if not isinstance(cfg, dict):
            continue
        if backend_name in collect_named_storage_backend_refs(cfg.get("backend")):
            refs.append({"agent_id": row.agent_id, "name": row.name})
    return refs


def backend_spec_supports_execution(spec: Any) -> bool:
    """True when the backend spec resolves to a sandbox/shell backend.

    deepagents ``FilesystemMiddleware`` rejects filesystem ``permissions`` when
    the backend implements ``SandboxBackendProtocol`` (e.g. ``local_shell``).
    """
    if spec is None:
        return True
    if isinstance(spec, str):
        return spec in {"local_shell", "docker", "opensandbox"}
    if not isinstance(spec, dict):
        return False
    kind = spec.get("type")
    if kind in {"local_shell", "docker", "opensandbox"}:
        return True
    if kind == "composite":
        if backend_spec_supports_execution(spec.get("default")):
            return True
        routes = spec.get("routes")
        if isinstance(routes, dict):
            return any(backend_spec_supports_execution(route) for route in routes.values())
    return False
