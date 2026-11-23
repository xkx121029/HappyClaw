"""Ref-scoped installation of the DSH LangChain model adapter (S8).

Design constraints enforced here:

* **Off by default, off per ref.** Nothing is replaced unless
  ``HAPPYCLAW_DSH_RUNTIME`` + ``HAPPYCLAW_DSH_LLM`` are on *and* the ref appears in
  ``HAPPYCLAW_DSH_LLM_REFS``. Every other ref is served by the original harness
  factory unchanged.
* **Per-ref failure isolation.** If one ref cannot build an adapter (missing
  transport, unsupported protocol, bad config) that ref falls back to the
  harness factory; sibling refs keep using the adapter.
* **No structural surprises.** ``HarnessAgentManager._shared_factory`` is a
  private attribute with no version contract. It is read and written through
  guarded helpers; a missing attribute or wrong type logs an explicit error and
  leaves the original factory in place instead of breaking model calls.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from happyclaw_harness.llm.factory import ChatModelFactory

from happyclaw.infra.dsh.llm.langchain_model import (
    REQUIRED_HARNESS_VERSION,
    DshChatModel,
    DshModelError,
    build_dsh_chat_model,
    harness_version_warning,
    installed_harness_version,
)
from happyclaw.infra.dsh.switches import llm_enabled, llm_ref_enabled, llm_refs

__all__ = [
    "DshInstallError",
    "DshModelFactory",
    "InstallOutcome",
    "InstallResult",
    "LlmInstallStatus",
    "describe_installation",
    "install_dsh_model_factory",
]

logger = logging.getLogger(__name__)

_SHARED_FACTORY = "_shared_factory"

TransportFactory = Callable[[Any, Any], Any]


class DshInstallError(RuntimeError):
    """The harness manager does not expose the seam this adapter depends on."""


class InstallOutcome(StrEnum):
    """Three distinguishable install outcomes reported by the status query."""

    INSTALLED = "installed"
    SKIPPED = "skipped"
    FAILED = "failed"


@dataclass(frozen=True)
class InstallResult:
    """Outcome of one installation attempt; never raises by itself."""

    applied: bool
    reason: str
    version_warning: str | None = None
    outcome: str = InstallOutcome.SKIPPED


@dataclass(frozen=True)
class LlmInstallStatus:
    """Read-only snapshot answering "which refs use the DSH adapter, and why"."""

    outcome: str
    applied: bool
    reason: str
    refs: tuple[str, ...]
    version_warning: str | None
    required_harness_version: str
    harness_version: str | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "outcome": str(self.outcome),
            "applied": self.applied,
            "reason": self.reason,
            "refs": list(self.refs),
            "version_warning": self.version_warning,
            "required_harness_version": self.required_harness_version,
            "harness_version": self.harness_version,
        }


def _read_shared_factory(manager: Any) -> ChatModelFactory | None:
    try:
        current = getattr(manager, _SHARED_FACTORY)
    except Exception as exc:  # pragma: no cover - defensive, structure changed
        raise DshInstallError(
            f"cannot read HarnessAgentManager.{_SHARED_FACTORY}: {exc!r}"
        ) from exc
    if current is None:
        return None
    if not isinstance(current, ChatModelFactory):
        raise DshInstallError(
            f"HarnessAgentManager.{_SHARED_FACTORY} is "
            f"{type(current).__name__}, expected ChatModelFactory"
        )
    return current


class DshModelFactory(ChatModelFactory):
    """``ChatModelFactory`` that serves allow-listed refs through ``LlmRuntime``.

    The provider index and model cache are the *same objects* as the wrapped
    factory, because ``HarnessAgentManager.add_provider`` / ``remove_provider``
    mutate ``_providers`` in place.
    """

    def __init__(
        self,
        original: ChatModelFactory,
        *,
        refs: Iterable[str],
        transport_factory: TransportFactory,
    ) -> None:
        # Intentionally no super().__init__: sharing state is the contract.
        self._providers = original._providers
        self._cache = original._cache
        self._agent_config = getattr(original, "_agent_config", None)
        self._get_protocol = getattr(original, "_get_protocol", None)
        self._dsh_refs = frozenset(refs)
        self._transport_factory = transport_factory
        self._dsh_cache: dict[Any, DshChatModel] = {}

    def get_chat_model(self, model_ref: str, *, max_retries: int | None = None) -> Any:
        if not llm_ref_enabled(model_ref) or model_ref not in self._dsh_refs:
            return super().get_chat_model(model_ref, max_retries=max_retries)
        key = model_ref if max_retries is None else (model_ref, max_retries)
        cached = self._dsh_cache.get(key)
        if cached is not None:
            return cached
        try:
            model = self._build_dsh(model_ref, max_retries=max_retries)
        except Exception as exc:
            # Per-ref rollback: this ref keeps working through the harness
            # factory even if its adapter cannot be built.
            logger.warning("DSH LLM ref %s fell back to harness factory: %s", model_ref, exc)
            return super().get_chat_model(model_ref, max_retries=max_retries)
        self._dsh_cache[key] = model
        return model

    def _build_dsh(self, model_ref: str, *, max_retries: int | None) -> DshChatModel:
        provider_key, _, model_id = model_ref.partition("/")
        provider = self._providers.get(provider_key)
        if provider is None:
            raise DshModelError(f"unknown provider {provider_key!r} in {model_ref!r}")
        model = provider.get_model(model_id)
        if model is None or not model.enabled:
            raise DshModelError(f"model {model_ref!r} not found or disabled")
        transport = self._transport_factory(provider, model)
        if transport is None:
            raise DshModelError(f"no DSH transport configured for {model_ref!r}")
        return build_dsh_chat_model(
            provider,
            model,
            transport,
            max_attempts=(max_retries + 1) if max_retries is not None else 1,
        )

    def pop_cached(self, model_ref: str) -> None:
        super().pop_cached(model_ref)
        for key in list(self._dsh_cache):
            if key == model_ref or (isinstance(key, tuple) and key[0] == model_ref):
                self._dsh_cache.pop(key, None)

    def clear_provider_cache(self, provider_id: str) -> None:
        refs = {key[0] if isinstance(key, tuple) else key for key in self._dsh_cache}
        for ref in refs:
            if ref.startswith(f"{provider_id}/"):
                self.pop_cached(ref)
        super().clear_provider_cache(provider_id)

    def close(self) -> None:
        self._dsh_cache.clear()
        super().close()

    async def aclose(self) -> None:
        self._dsh_cache.clear()
        await super().aclose()


def install_dsh_model_factory(
    manager: Any,
    *,
    transport_factory: TransportFactory | None = None,
) -> InstallResult:
    """Install the adapter wrapper when the switches allow it.

    Returns a structured result instead of raising so a deployment can keep
    booting with the original factory. Failures are always logged at ERROR.
    """
    if not llm_enabled():
        return InstallResult(False, "HAPPYCLAW_DSH_LLM is off", outcome=InstallOutcome.SKIPPED)
    # The version warning comes first so a mismatched harness is always visible
    # in the startup log, even when a later check skips the install.
    warning = harness_version_warning()
    if warning:
        logger.warning("DSH LLM adapter: %s", warning)
    refs = llm_refs()
    if not refs:
        return InstallResult(
            False, "HAPPYCLAW_DSH_LLM_REFS is empty", warning, InstallOutcome.SKIPPED
        )

    try:
        original = _read_shared_factory(manager)
    except DshInstallError as exc:
        logger.error("DSH LLM adapter not installed, keeping original factory: %s", exc)
        return InstallResult(False, str(exc), warning, InstallOutcome.FAILED)
    if original is None:
        logger.error(
            "DSH LLM adapter not installed: %s is None (no providers yet)",
            _SHARED_FACTORY,
        )
        return InstallResult(
            False, f"{_SHARED_FACTORY} is None", warning, InstallOutcome.FAILED
        )
    if isinstance(original, DshModelFactory):
        return InstallResult(True, "already installed", warning, InstallOutcome.INSTALLED)
    if transport_factory is None:
        return InstallResult(
            False, "no transport factory supplied", warning, InstallOutcome.SKIPPED
        )

    wrapper = DshModelFactory(
        original,
        refs=refs,
        transport_factory=transport_factory,
    )
    try:
        setattr(manager, _SHARED_FACTORY, wrapper)
        if getattr(manager, _SHARED_FACTORY) is not wrapper:
            raise DshInstallError(f"{_SHARED_FACTORY} assignment did not stick")
    except Exception as exc:
        logger.error("DSH LLM adapter not installed, keeping original factory: %s", exc)
        try:
            setattr(manager, _SHARED_FACTORY, original)
        except Exception:  # pragma: no cover - restore is best effort
            logger.exception("failed to restore original shared factory")
        return InstallResult(False, str(exc), warning, InstallOutcome.FAILED)
    return InstallResult(True, "installed", warning, InstallOutcome.INSTALLED)


def describe_installation(
    manager: Any | None,
    *,
    result: InstallResult | None = None,
) -> LlmInstallStatus:
    """Report the current S8 wiring without changing it.

    ``refs`` are the refs that would use the adapter *right now*: the wrapper
    must still be installed and the switches must still allow each ref, so
    turning ``HAPPYCLAW_DSH_LLM`` off is reflected immediately.
    """
    current: Any = None
    if manager is not None:
        try:
            current = getattr(manager, _SHARED_FACTORY)
        except Exception:
            current = None
    active: tuple[str, ...] = ()
    if isinstance(current, DshModelFactory):
        active = tuple(sorted(ref for ref in current._dsh_refs if llm_ref_enabled(ref)))
        if result is None:
            result = InstallResult(
                True, "installed (no boot record)", outcome=InstallOutcome.INSTALLED
            )
    if result is None:
        result = InstallResult(
            False, "installer has not run", outcome=InstallOutcome.SKIPPED
        )
    return LlmInstallStatus(
        outcome=str(result.outcome),
        applied=result.applied,
        reason=result.reason,
        refs=active,
        version_warning=result.version_warning,
        required_harness_version=REQUIRED_HARNESS_VERSION,
        harness_version=installed_harness_version(),
    )
