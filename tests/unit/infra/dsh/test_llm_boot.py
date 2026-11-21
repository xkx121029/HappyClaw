"""S8 boot wiring: zero import when off, safe failures, and status reporting."""

from __future__ import annotations

import logging
import sys
from typing import Any

import pytest
from happyclaw_harness.config import ModelConfig, ProviderConfig
from happyclaw_harness.llm.factory import ChatModelFactory

from octop.infra.agents.manager import AgentManager

ADAPTER_MODULES = (
    "octop.infra.dsh.llm",
    "octop.infra.dsh.llm.factory",
    "octop.infra.dsh.llm.langchain_model",
)


class _FakeManager:
    def __init__(self, factory: Any) -> None:
        self._shared_factory = factory


def _providers() -> list[ProviderConfig]:
    return [
        ProviderConfig(
            id="p",
            base_url="https://example.invalid/v1",
            api_key="k",
            models=[ModelConfig(id="m")],
        )
    ]


def _factory() -> ChatModelFactory:
    return ChatModelFactory(_providers())


def _enable(monkeypatch: pytest.MonkeyPatch, refs: str = "p/m") -> None:
    monkeypatch.setenv("OCTOP_DSH_RUNTIME", "1")
    monkeypatch.setenv("OCTOP_DSH_LLM", "1")
    monkeypatch.setenv("OCTOP_DSH_LLM_REFS", refs)


def _transport_factory():
    def build(_provider: Any, _model: Any) -> Any:
        return object()

    return build


def _agent_manager_for(manager: Any) -> AgentManager:
    """Minimal AgentManager carrying only the state the boot hook touches."""
    agent_manager = object.__new__(AgentManager)
    agent_manager._harness_manager = manager
    agent_manager._dsh_transport_factory = _transport_factory()
    agent_manager._dsh_llm_install = None
    return agent_manager


def test_boot_install_is_zero_import_when_switches_are_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OCTOP_DSH_RUNTIME", raising=False)
    monkeypatch.delenv("OCTOP_DSH_LLM", raising=False)
    saved = {name: sys.modules.pop(name, None) for name in ADAPTER_MODULES}
    try:
        # No _harness_manager / transport on purpose: touching either would raise.
        agent_manager = object.__new__(AgentManager)
        AgentManager._install_dsh_llm(agent_manager)

        assert getattr(agent_manager, "_dsh_llm_install", None) is None
        for name in ADAPTER_MODULES:
            assert name not in sys.modules, f"boot imported {name} while the stage is off"
    finally:
        for name, module in saved.items():
            if module is not None:
                sys.modules[name] = module


def test_boot_structure_mismatch_logs_error_and_keeps_the_factory(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    _enable(monkeypatch)
    original = object()
    manager = _FakeManager(original)
    agent_manager = _agent_manager_for(manager)

    with caplog.at_level(logging.ERROR):
        AgentManager._install_dsh_llm(agent_manager)  # must not raise

    assert manager._shared_factory is original
    result = agent_manager._dsh_llm_install
    assert result.applied is False
    assert result.outcome == "failed"
    assert "expected ChatModelFactory" in result.reason
    assert any("expected ChatModelFactory" in record.message for record in caplog.records)


def test_status_query_distinguishes_installed_skipped_and_failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from octop.infra.dsh.llm.factory import describe_installation, install_dsh_model_factory

    monkeypatch.delenv("OCTOP_DSH_RUNTIME", raising=False)
    monkeypatch.delenv("OCTOP_DSH_LLM", raising=False)
    off_manager = _FakeManager(_factory())
    off_result = install_dsh_model_factory(
        off_manager, transport_factory=_transport_factory()
    )
    skipped = describe_installation(off_manager, result=off_result).as_dict()
    assert skipped["outcome"] == "skipped"
    assert skipped["applied"] is False
    assert skipped["refs"] == []
    assert "off" in skipped["reason"]

    _enable(monkeypatch)
    bad_manager = _FakeManager(object())
    bad_result = install_dsh_model_factory(
        bad_manager, transport_factory=_transport_factory()
    )
    failed = describe_installation(bad_manager, result=bad_result).as_dict()
    assert failed["outcome"] == "failed"
    assert failed["applied"] is False
    assert failed["refs"] == []
    assert "expected ChatModelFactory" in failed["reason"]

    good_manager = _FakeManager(_factory())
    good_result = install_dsh_model_factory(
        good_manager, transport_factory=_transport_factory()
    )
    installed = describe_installation(good_manager, result=good_result).as_dict()
    assert installed["outcome"] == "installed"
    assert installed["applied"] is True
    assert installed["refs"] == ["p/m"]
    assert installed["required_harness_version"] == "1.0.9"


def test_version_warning_reaches_the_startup_log(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    _enable(monkeypatch)
    monkeypatch.setattr(
        "octop.infra.dsh.llm.langchain_model.version", lambda _name: "9.9.9"
    )
    agent_manager = _agent_manager_for(_FakeManager(_factory()))

    with caplog.at_level(logging.WARNING):
        AgentManager._install_dsh_llm(agent_manager)

    messages = [record.message for record in caplog.records]
    assert any("9.9.9" in message and "1.0.9" in message for message in messages)
    assert agent_manager._dsh_llm_install.version_warning is not None
