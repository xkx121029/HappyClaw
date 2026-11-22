"""Catalog sources for the plugin market pipeline."""

from happyclaw.infra.plugins.market.sources.dsh import DshSource
from happyclaw.infra.plugins.market.sources.octop import HappyclawSource

__all__ = ["DshSource", "HappyclawSource"]
