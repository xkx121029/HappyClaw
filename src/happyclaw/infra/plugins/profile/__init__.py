"""Plugin profile composition: named bundles, atomic switching, lazy loading."""

from happyclaw.infra.plugins.profile.errors import ProfileNotFoundError
from happyclaw.infra.plugins.profile.market_source import InstalledSlot, MarketInstallSource
from happyclaw.infra.plugins.profile.model import (
    LoadMode,
    Profile,
    ProfileEntry,
    validate_profile_name,
)
from happyclaw.infra.plugins.profile.runtime import (
    LoadTiming,
    PluginFailure,
    PluginState,
    PluginStatus,
    ProfileRuntime,
    RefreshResult,
    SwitchResult,
)
from happyclaw.infra.plugins.profile.solver import ResolvedProfile, resolve_profile
from happyclaw.infra.plugins.profile.store import ActiveProfile, ProfileStore

__all__ = [
    "ActiveProfile",
    "InstalledSlot",
    "LoadMode",
    "LoadTiming",
    "MarketInstallSource",
    "PluginFailure",
    "PluginState",
    "PluginStatus",
    "Profile",
    "ProfileEntry",
    "ProfileNotFoundError",
    "ProfileRuntime",
    "ProfileStore",
    "RefreshResult",
    "ResolvedProfile",
    "SwitchResult",
    "resolve_profile",
    "validate_profile_name",
]
