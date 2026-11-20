"""Backward-compatible import path for the usage Excel builder.

The implementation moved to :mod:`octop.infra.usage.xlsx` so that
``infra.usage.report`` no longer imports the API package.
"""

from __future__ import annotations

from octop.infra.usage.xlsx import build_usage_xlsx

__all__ = ["build_usage_xlsx"]
