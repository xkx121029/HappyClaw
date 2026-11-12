"""Octop — smarter self-hosted AI assistant (multi-user, multi-agent)."""

from __future__ import annotations

import time as _time

# Captured before any heavy import so ``startup_timing`` can separate
# interpreter start-up from application work. Keep both lines at the top.
PROCESS_MONO_ORIGIN = _time.perf_counter()
PROCESS_EPOCH_ORIGIN = _time.time()

from octop.infra.utils.httpx_proxy import install_httpx_cidr_no_proxy

__version__ = "1.0.3b5"

# httpx 0.28 treats NO_PROXY CIDR as an exact IP (see issue #1347). Patch once
# at import so CLI, ``octop run``, and in-process harness clients all honor it.
install_httpx_cidr_no_proxy()
