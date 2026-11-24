"""Keep loopback endpoints off the system HTTP proxy.

Local model servers (Ollama, LM Studio, vLLM, the QA mock) listen on
``127.0.0.1`` / ``localhost`` / ``::1``. When the machine has ``HTTP_PROXY`` /
``HTTPS_PROXY`` set, ``httpx`` (used by ``langchain-openai``) routes those
requests through the proxy and the local server never sees them — the turn then
fails with an opaque model error.

Adding the loopback hosts to ``NO_PROXY`` is the mechanism httpx honours, so we
merge them into the existing value at startup and leave everything else alone.
"""

from __future__ import annotations

import os
from collections.abc import MutableMapping

LOOPBACK_HOSTS: tuple[str, ...] = ("127.0.0.1", "localhost", "::1")

_PROXY_VARS = ("NO_PROXY", "no_proxy")


def skip_loopback_proxy(
    env: MutableMapping[str, str] | None = None,
    hosts: tuple[str, ...] = LOOPBACK_HOSTS,
) -> MutableMapping[str, str]:
    """Return *env* with loopback hosts merged into ``NO_PROXY``.

    Pure helper (no ``os.environ`` writes) so it can be unit-tested; merge order
    is preserved and duplicates are dropped.
    """
    target = os.environ if env is None else env
    for key in _PROXY_VARS:
        current = target.get(key, "")
        parts = [item.strip() for item in current.split(",") if item.strip()]
        merged = list(parts)
        for host in hosts:
            if host not in merged:
                merged.append(host)
        if merged != parts:
            target[key] = ",".join(merged)
    return target


def ensure_loopback_no_proxy() -> None:
    """Apply :func:`skip_loopback_proxy` to the live process environment."""
    skip_loopback_proxy()
