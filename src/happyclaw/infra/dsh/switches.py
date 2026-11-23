"""DSH integration stage switches.

Every switch is a process-level environment variable and is evaluated from
memory only: no file, database or network access. Callers must check the
switch *before* importing any DSH implementation module so that a disabled
stage costs nothing beyond one dictionary lookup.

``HAPPYCLAW_DSH_RUNTIME`` is the master gate. When it is off (the default) every
stage is off, regardless of the per-stage variables.
"""

from __future__ import annotations

import os

from happyclaw.infra.utils.env_alias import CURRENT_PREFIX, env_get

_TRUTHY = frozenset({"1", "true", "yes", "on"})
_MASTER = "HAPPYCLAW_DSH_RUNTIME"
_STAGE_PREFIX = "HAPPYCLAW_DSH_"
_LLM_REFS = "HAPPYCLAW_DSH_LLM_REFS"


def _flag(name: str) -> bool:
    suffix = name[len(CURRENT_PREFIX):] if name.startswith(CURRENT_PREFIX) else name
    return (env_get(suffix) or "").strip().lower() in _TRUTHY


def runtime_enabled() -> bool:
    """Return whether the DSH master switch is on. Defaults to off."""
    return _flag(_MASTER)


def stage_enabled(stage: str) -> bool:
    """Return whether *stage* may run.

    ``stage`` is the bare name (``"tools"``, ``"hitl"``, ...); the environment
    variable is ``HAPPYCLAW_DSH_<STAGE>``. The master switch always wins.
    """
    if not runtime_enabled():
        return False
    return _flag(f"{_STAGE_PREFIX}{stage.upper()}")


def shadow_enabled() -> bool:
    """Switch for the session shadow writer (stage ``shadow``).

    Compatibility carve-out: when ``HAPPYCLAW_DSH_RUNTIME`` is not set at all the
    legacy ``HAPPYCLAW_DSH_SHADOW`` variable alone keeps working, so introducing
    the master switch does not change existing behaviour. Once the master
    variable is present, it gates the stage like every other switch.
    """
    if (env_get("DSH_RUNTIME") or "").strip() == "":
        return _flag(f"{_STAGE_PREFIX}SHADOW")
    return stage_enabled("shadow")


def llm_enabled() -> bool:
    """Switch for the S8 LangChain model adapter (stage ``llm``)."""
    return stage_enabled("llm")


def llm_refs() -> frozenset[str]:
    """Explicit ``provider/model`` refs allowed to use the DSH adapter.

    S8 is opt-in per ref, never global: an empty allow-list means "use the
    harness factory for everything", even when ``HAPPYCLAW_DSH_LLM`` is on.
    """
    raw = os.environ.get(_LLM_REFS, "")
    return frozenset(part.strip() for part in raw.split(",") if part.strip())


def llm_ref_enabled(model_ref: str) -> bool:
    """Return whether exactly *model_ref* may bypass the harness factory."""
    return llm_enabled() and model_ref.strip() in llm_refs()


__all__ = [
    "llm_enabled",
    "llm_ref_enabled",
    "llm_refs",
    "runtime_enabled",
    "shadow_enabled",
    "stage_enabled",
]
