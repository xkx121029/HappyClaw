"""DSH 总开关与分阶段开关（进程级环境变量，零 I/O）。"""

from __future__ import annotations

import sys

from octop.infra.dsh import switches


def test_master_switch_defaults_to_off(monkeypatch) -> None:
    monkeypatch.delenv("OCTOP_DSH_RUNTIME", raising=False)
    monkeypatch.setenv("OCTOP_DSH_TOOLS", "1")

    assert switches.runtime_enabled() is False
    assert switches.stage_enabled("tools") is False


def test_stage_requires_master_and_itself(monkeypatch) -> None:
    monkeypatch.setenv("OCTOP_DSH_RUNTIME", "1")
    monkeypatch.delenv("OCTOP_DSH_TOOLS", raising=False)
    assert switches.stage_enabled("tools") is False

    monkeypatch.setenv("OCTOP_DSH_TOOLS", "true")
    assert switches.stage_enabled("tools") is True


def test_shadow_keeps_legacy_variable_when_master_is_absent(monkeypatch) -> None:
    monkeypatch.delenv("OCTOP_DSH_RUNTIME", raising=False)
    monkeypatch.setenv("OCTOP_DSH_SHADOW", "on")
    assert switches.shadow_enabled() is True

    monkeypatch.setenv("OCTOP_DSH_RUNTIME", "0")
    assert switches.shadow_enabled() is False


def test_shadow_stage_is_gated_by_master_when_present(monkeypatch) -> None:
    monkeypatch.setenv("OCTOP_DSH_RUNTIME", "1")
    monkeypatch.setenv("OCTOP_DSH_SHADOW", "1")
    assert switches.shadow_enabled() is True


def test_processor_hook_does_not_import_session_module_when_off(monkeypatch) -> None:
    from octop.infra.gateway.process.processor import GlobalProcessor

    monkeypatch.delenv("OCTOP_DSH_RUNTIME", raising=False)
    monkeypatch.delenv("OCTOP_DSH_SHADOW", raising=False)
    name = "octop.infra.dsh.session.shadow"
    original = sys.modules.pop(name, None)
    try:
        GlobalProcessor._write_shadow_history("thread-1", [])
        assert name not in sys.modules
    finally:
        # 还原模块身份，避免影响其它测试对 write_shadow_turn 的 monkeypatch。
        if original is not None:
            sys.modules[name] = original


def test_llm_switch_is_ref_scoped(monkeypatch) -> None:
    monkeypatch.setenv("OCTOP_DSH_RUNTIME", "1")
    monkeypatch.setenv("OCTOP_DSH_LLM", "1")
    monkeypatch.setenv("OCTOP_DSH_LLM_REFS", "p/m, q/n")

    assert switches.llm_enabled() is True
    assert switches.llm_refs() == frozenset({"p/m", "q/n"})
    assert switches.llm_ref_enabled("p/m") is True
    assert switches.llm_ref_enabled("p/other") is False


def test_llm_refs_require_both_master_and_stage(monkeypatch) -> None:
    monkeypatch.setenv("OCTOP_DSH_LLM", "1")
    monkeypatch.setenv("OCTOP_DSH_LLM_REFS", "p/m")
    monkeypatch.delenv("OCTOP_DSH_RUNTIME", raising=False)
    assert switches.llm_ref_enabled("p/m") is False

    monkeypatch.setenv("OCTOP_DSH_RUNTIME", "1")
    monkeypatch.delenv("OCTOP_DSH_LLM", raising=False)
    assert switches.llm_ref_enabled("p/m") is False
