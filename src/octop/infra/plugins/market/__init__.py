"""Unified plugin market: octop + DSH catalogs, one install pipeline."""

import os
from pathlib import Path

from octop.infra.plugins.market.envelope import ENVELOPE_FILENAME
from octop.infra.plugins.market.errors import (
    CapabilityExpansionError,
    ChecksumMismatchError,
    ConfigSchemaChangedError,
    DependencyConstraintError,
    DependencyInUseError,
    IndexFormatError,
    IndexUnusableError,
    InstallConflictError,
    MarketError,
    MarketErrorCode,
    PayloadError,
    ReleaseNotFound,
    SourceUnreachableError,
    UnsupportedSourceError,
)
from octop.infra.plugins.market.models import (
    Artifact,
    MarketEntry,
    PluginRelease,
    RejectedEntry,
)
from octop.infra.plugins.market.pipeline import (
    DependencyImpact,
    IndexConflict,
    InstallResult,
    MarketplaceIndex,
    PlanResult,
    UninstallResult,
    UpgradeResult,
    install_entry,
    plugin_dir_name,
    uninstall,
    verify_install,
)
from octop.infra.plugins.market.source import InstalledPayload, Source
from octop.infra.plugins.market.sources import DshSource, OctopSource
from octop.infra.plugins.runtime.contract import (
    CapabilityKind,
    PluginKind,
    PluginRequirement,
)

def default_market_root() -> Path:
    """Catalog install root shared by the API and the DSH tool discovery.

    ``OCTOP_DSH_MARKET_ROOT`` overrides it; otherwise ``~/.octop/market``
    (``$OCTOP_HOME/market``) is used. Never created here — a missing root is a
    readable skip, not an error.
    """

    raw = os.environ.get("OCTOP_DSH_MARKET_ROOT", "").strip()
    if raw:
        return Path(raw).expanduser()
    from octop.infra.utils.paths import PathLayout

    return PathLayout.from_env().market_dir


__all__ = [
    "Artifact",
    "CapabilityExpansionError",
    "CapabilityKind",
    "ChecksumMismatchError",
    "ConfigSchemaChangedError",
    "DependencyConstraintError",
    "DependencyImpact",
    "DependencyInUseError",
    "DshSource",
    "ENVELOPE_FILENAME",
    "IndexConflict",
    "IndexFormatError",
    "IndexUnusableError",
    "InstallConflictError",
    "InstallResult",
    "InstalledPayload",
    "MarketEntry",
    "MarketError",
    "MarketErrorCode",
    "MarketplaceIndex",
    "OctopSource",
    "PayloadError",
    "PlanResult",
    "PluginKind",
    "PluginRelease",
    "PluginRequirement",
    "RejectedEntry",
    "ReleaseNotFound",
    "Source",
    "SourceUnreachableError",
    "UninstallResult",
    "UnsupportedSourceError",
    "UpgradeResult",
    "default_market_root",
    "install_entry",
    "plugin_dir_name",
    "uninstall",
    "verify_install",
]
