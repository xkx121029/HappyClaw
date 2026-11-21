"""Protocol keys are read under both spellings and written under both.

The harness still writes the pre-rename ``octop_*`` names, so a message written
here has to carry the old spelling too, and a checkpoint written before the
rename has to stay readable.
"""

from __future__ import annotations

from octop.infra.agents import protocol_keys


def test_read_accepts_the_current_spelling() -> None:
    assert protocol_keys.read({"happyclaw_decision": {"kind": "decision"}}, "decision") == {"kind": "decision"}


def test_read_accepts_the_legacy_spelling() -> None:
    # Messages persisted before the rename carry only the old key.
    assert protocol_keys.read({"octop_decision": {"kind": "decision"}}, "decision") == {"kind": "decision"}


def test_read_prefers_the_current_spelling() -> None:
    payload = {"happyclaw_decision": "new", "octop_decision": "old"}
    assert protocol_keys.read(payload, "decision") == "new"


def test_read_returns_the_default_when_neither_spelling_is_present() -> None:
    assert protocol_keys.read({}, "decision") is None
    assert protocol_keys.read({}, "decision", "fallback") == "fallback"


def test_both_emits_both_spellings() -> None:
    assert protocol_keys.both("decision_followup", True) == {
        "happyclaw_decision_followup": True,
        "octop_decision_followup": True,
    }
