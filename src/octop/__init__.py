"""Octop — smarter self-hosted AI assistant (multi-user, multi-agent)."""

from __future__ import annotations

import time as _time

# Captured before any heavy import so ``startup_timing`` can separate
# interpreter start-up from application work. Keep both lines at the top.
PROCESS_MONO_ORIGIN = _time.perf_counter()
PROCESS_EPOCH_ORIGIN = _time.time()

from octop.infra.utils.httpx_proxy import install_lazy_httpx_proxy_patch

__version__ = "1.0.3b6"

# httpx 0.28 treats NO_PROXY CIDR as an exact IP (see issue #1347). Register a
# one-shot import hook so the patch is applied the moment httpx first loads —
# every client still honors it, but CLI meta-commands and imports that never
# touch the network no longer pay httpx's ~1s import cost up front.
install_lazy_httpx_proxy_patch()
