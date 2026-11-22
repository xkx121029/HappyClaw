"""Wiring tests for the opt-in DSH skill/prompt integration.

The flag is off by default. When off, the assembled system prompt and the
prepared stream request must match the pre-integration output byte for byte and
must not touch the skills tree at all. When on, assembly is deterministic and
skill-set changes surface as incremental text.
"""

from __future__ import annotations

import json
import logging
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from happyclaw.config import OctopConfig
from happyclaw.infra.agents.manager import AgentManager
from happyclaw.infra.db.migrate import run_migrations
from happyclaw.infra.db.pool import SqlitePool
from happyclaw.infra.db.repos.agents import AgentRow
from happyclaw.infra.db.services import build_shared_services
from happyclaw.infra.dsh.integration import (
    DSH_SKILLS_PROMPTS_ENV,
    DSH_SKILLS_STRICT_ENV,
    DshPromptSessionStore,
    compose_system_prompt,
)
from happyclaw.infra.dsh.prompts.skills_injection import (
    SkillPromptEntry,
    SkillPromptSnapshot,
)
from happyclaw.infra.dsh.skills import DshSkillPathError
from happyclaw.infra.utils.paths import PathLayout

# Captured from the pre-integration implementation. These literals are the
# baseline: any byte change on the flag-off path fails the test.
PRE_CHANGE_SYSTEM_PROMPT = "MBTI persona prompt"
PRE_CHANGE_REQUEST: dict[str, Any] = {
    "thread_id": "t1",
    "messages": [],
    "agent_id": "AGT_OFF",
}


@pytest.fixture
def manager(tmp_path: Path) -> AgentManager:
    paths = PathLayout(tmp_path / ".octop")
    paths.ensure_root()
    db = SqlitePool(paths.db)
    run_migrations(db)
    services = build_shared_services(db=db, paths=paths, config=OctopConfig())
    return AgentManager(repos=services.repos, paths=services.paths)


def _row(*, agent_id: str, workspace: Path, system_prompt: str | None) -> AgentRow:
    return AgentRow(
        id=1,
        agent_id=agent_id,
        user_id=None,
        name="bot",
        description=None,
        persona_mbti=None,
        default_model=None,
        system_prompt=system_prompt,
        enabled=1,
        config_json=json.dumps(
            {
                "backend": {
                    "type": "filesystem",
                    "root_dir": str(workspace),
                    "virtual_mode": False,
                }
            }
        ),
        last_state=None,
        last_error=None,
        created_at=0,
        updated_at=0,
    )


def _bootstrapped_workspace(manager: AgentManager, agent_id: str) -> Path:
    ws = manager._paths.ensure_agent_workspace(agent_id)
    (ws / ".bootstrapped").write_text("", encoding="utf-8")
    return ws


def _snapshot(*names: str) -> SkillPromptSnapshot:
    return SkillPromptSnapshot.build(
        SkillPromptEntry(name=name, description=f"{name} does things", path=f"skills/{name}")
        for name in names
    )


def test_disabled_matches_previous_output_and_does_no_io(
    manager: AgentManager,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(DSH_SKILLS_PROMPTS_ENV, raising=False)
    agent_id = "AGT_OFF"
    ws = _bootstrapped_workspace(manager, agent_id)
    row = replace(_row(agent_id=agent_id, workspace=ws, system_prompt=PRE_CHANGE_SYSTEM_PROMPT))

    baseline = manager._build_harness_config(row).system_prompt
    assert baseline is not None
    assert baseline.encode("utf-8") == PRE_CHANGE_SYSTEM_PROMPT.encode("utf-8")

    def _boom(*_: Any, **__: Any) -> Any:
        raise AssertionError("flag-off path must not read the skills tree")

    monkeypatch.setattr("happyclaw.infra.dsh.integration.discover_skill_root", _boom)
    again = manager._build_harness_config(row).system_prompt
    assert again is not None
    assert again.encode("utf-8") == PRE_CHANGE_SYSTEM_PROMPT.encode("utf-8")

    monkeypatch.setattr(manager, "get_config", lambda _: {})
    prepared = manager._prepare_stream_request(agent_id, {"thread_id": "t1", "messages": []})
    assert prepared == PRE_CHANGE_REQUEST
    assert "dsh_skills_delta" not in (prepared.get("configurable") or {})


def test_compose_system_prompt_is_byte_identical() -> None:
    snapshot = _snapshot("alpha", "beta")

    first = compose_system_prompt("base persona", snapshot)
    second = compose_system_prompt("base persona", snapshot)

    assert first is not None and second is not None
    assert first.encode("utf-8") == second.encode("utf-8")
    assert "## DSH Skills" in first
    assert first.index("base persona") < first.index("## DSH Skills")
    assert compose_system_prompt("base persona", SkillPromptSnapshot()) == "base persona"


def test_incremental_delta_non_empty_only_after_skills_change() -> None:
    store = DshPromptSessionStore()
    base = _snapshot("alpha")

    assert store.advance("AGT", "t1", base) == ""
    assert store.advance("AGT", "t1", base) == ""
    assert store.session_count() == 1

    changed = store.advance("AGT", "t1", _snapshot("alpha", "beta"))
    assert changed != ""
    assert "beta" in changed

    # A different thread keeps its own cursor.
    assert store.advance("AGT", "t2", base) == ""

    store.discard("AGT", "t1")
    assert store.session_count() == 1
    store.discard_agent("AGT")
    assert store.session_count() == 0


def test_out_of_root_skill_is_rejected_not_silently_skipped(
    manager: AgentManager,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setenv(DSH_SKILLS_PROMPTS_ENV, "1")
    monkeypatch.delenv(DSH_SKILLS_STRICT_ENV, raising=False)
    agent_id = "AGT_ESCAPE"
    ws = _bootstrapped_workspace(manager, agent_id)
    skill_dir = ws / "skills" / "evil"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: evil\ndescription: escapes the root\n---\n"
        "See `references/../../outside.md` for details.\n",
        encoding="utf-8",
    )
    row = _row(agent_id=agent_id, workspace=ws, system_prompt=PRE_CHANGE_SYSTEM_PROMPT)

    with caplog.at_level(logging.WARNING, logger="happyclaw.infra.dsh.integration"):
        cfg = manager._build_harness_config(row)

    assert cfg.system_prompt == PRE_CHANGE_SYSTEM_PROMPT
    assert any(
        "DSH skill discovery failed" in record.getMessage()
        and "DSH_SKILL_PATH_OUTSIDE_ROOT" in record.getMessage()
        for record in caplog.records
    )

    monkeypatch.setenv(DSH_SKILLS_STRICT_ENV, "1")
    with pytest.raises(DshSkillPathError) as excinfo:
        manager._build_harness_config(row)
    assert excinfo.value.code.value == "DSH_SKILL_PATH_OUTSIDE_ROOT"
