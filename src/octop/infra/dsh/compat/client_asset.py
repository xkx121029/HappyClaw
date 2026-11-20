"""Resolve the browser half of a DSH bundle.

Client bundles observed in the market are pre-built ``__ModuleLoader__``
factories: they are not ESM and their ``require(\"react\")`` calls are resolved
by the host. Serving the file as-is therefore works as long as the Dashboard
installs a loader shim; bundles that ship bare top-level imports need a build
step and are reported as ``BUNDLE_UNSUPPORTED`` instead of being served broken.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from octop.infra.dsh.compat.errors import DshCompatCode
from octop.infra.dsh.compat.probe import StaticFacts, map_slot

_REACT_REQUIRES = {
    "react",
    "react-dom",
    "react-dom/client",
    "react/jsx-runtime",
    "react/jsx-dev-runtime",
}
_MAX_ASSET_BYTES = 8 * 1024 * 1024


@dataclass(frozen=True)
class ClientAsset:
    entry: str | None
    exists: bool
    shape: str
    requires: tuple[str, ...]
    unsupported_requires: tuple[str, ...]
    slots: tuple[str, ...]
    mapped_slots: tuple[str, ...]
    unsupported_slots: tuple[str, ...]
    code: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _shape(path: Path) -> str:
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            head = handle.read(_MAX_ASSET_BYTES)
    except OSError:
        return "missing"
    if "__ModuleLoader__" in head:
        return "module-loader"
    if "require(" in head:
        return "module-loader"
    return "esm"


def client_asset(facts: StaticFacts) -> ClientAsset:
    if not facts.client_exists or not facts.client_rel:
        return ClientAsset(
            entry=facts.client_rel,
            exists=False,
            shape="missing",
            requires=(),
            unsupported_requires=(),
            slots=(),
            mapped_slots=(),
            unsupported_slots=(),
            code=DshCompatCode.CLIENT_MISSING.value,
        )
    path = Path(facts.package_dir) / facts.client_rel
    shape = _shape(path)
    unsupported_requires = tuple(
        spec for spec in facts.client_requires if spec not in _REACT_REQUIRES
    )
    code = DshCompatCode.OK.value
    if shape != "module-loader":
        code = DshCompatCode.BUNDLE_UNSUPPORTED.value
    elif unsupported_requires:
        code = DshCompatCode.MISSING_API.value
    return ClientAsset(
        entry=facts.client_rel,
        exists=True,
        shape=shape,
        requires=facts.client_requires,
        unsupported_requires=unsupported_requires,
        slots=facts.ui_slots,
        mapped_slots=facts.mapped_slots,
        unsupported_slots=facts.unsupported_slots,
        code=code,
    )


def resolve_client_file(package_dir: str | Path, rel: str) -> Path | None:
    """Resolve ``rel`` inside ``package_dir``; ``None`` escapes the bundle."""

    root = Path(package_dir).expanduser().resolve()
    candidate = (root / rel).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    if not candidate.is_file() or candidate.suffix not in {".js", ".mjs", ".cjs"}:
        return None
    if candidate.stat().st_size > _MAX_ASSET_BYTES:
        return None
    return candidate


def slot_map() -> dict[str, str]:
    """Diagnostic helper: sample slot ids -> host slot."""

    samples = (
        "sidebar.footer.action",
        "sidebar.panellist",
        "shell.overlay",
        "conversation.header.leading",
        "conversation.input.left",
        "settings.section",
        "main",
    )
    return {slot: map_slot(slot) or "" for slot in samples}
