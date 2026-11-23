"""Tests for three-stage compaction, budgets, and traceability."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from happyclaw.infra.dsh.session import (
    BlobStore,
    CompactionConfig,
    CompactionEngine,
    EventType,
    SessionLog,
    measure_units,
    project,
    surface_json,
    surface_units,
    trim_head,
)


def _clock() -> str:
    return "2026-11-12T00:00:00.000Z"


def _config() -> CompactionConfig:
    return CompactionConfig(
        max_context_units=500,
        l1_tool_result_units=100,
        l1_head_units=20,
        l1_tail_units=5,
        l2_block_units=100,
        l2_preview_units=10,
        l3_target_units=120,
        l3_retain_recent_nodes=2,
        l3_point_units=10,
        l3_item_units=8,
    )


def _build_log(root: Path) -> SessionLog:
    log = SessionLog(root, clock=_clock)
    log.append(EventType.SESSION_START, {"session_id": "s-compact"})
    log.append(EventType.USER_MESSAGE, {"text": "开始"})
    log.append(EventType.ASSISTANT_MESSAGE, {"text": "调用工具，决定采用磁盘扫描"})
    log.append(EventType.TOOL_CALL, {"call_id": "c1", "name": "disk_usage", "arguments": {}})
    log.append(
        EventType.TOOL_RESULT,
        {"call_id": "c1", "content": "工" * 500, "is_error": False, "name": "disk_usage"},
    )
    log.append(EventType.ASSISTANT_MESSAGE, {"text": "结果很大"})
    log.append(EventType.USER_MESSAGE, {"text": "大" * 200})
    for index in range(24):
        event = EventType.USER_MESSAGE if index % 2 == 0 else EventType.ASSISTANT_MESSAGE
        text = f"短{index}" + "字" * 24
        log.append(event, {"text": text})
    log.append(EventType.SESSION_END, {})
    return log


def test_three_levels_fire_in_order_until_under_budget(tmp_path: Path) -> None:
    log = _build_log(tmp_path / "session")
    engine = CompactionEngine(log, config=_config())

    report = engine.run_turn(7)

    assert [step.level for step in report.steps] == [1, 2, 3]
    assert report.initial_units > 500
    assert report.final_units <= 500
    assert report.within_budget is True
    assert all(step.before_units >= step.after_units for step in report.steps)
    assert [step.level for step in report.steps] == sorted(step.level for step in report.steps)


def test_compaction_events_are_traceable_to_turn_and_sources(tmp_path: Path) -> None:
    log = _build_log(tmp_path / "session")
    engine = CompactionEngine(log, config=_config())
    report = engine.run_turn(9)

    records = log.load()
    compaction = [
        record for record in records if record.type.startswith("compaction/")
    ]
    assert [record.type for record in compaction] == [
        "compaction/l1",
        "compaction/l2",
        "compaction/l3",
    ]
    assert [record.seq for record in compaction] == [step.event_seq for step in report.steps]

    l1, l2, l3 = compaction
    assert l1.data["turn"] == 9
    assert 4 in l1.data["source_seqs"]
    assert l1.data["targets"]["4"]["summary"]
    assert l1.data["targets"]["4"]["kept_fields"] == {}

    assert l2.data["turn"] == 9
    assert 6 in l2.data["source_seqs"]
    target = l2.data["targets"][0]
    assert target["path"] == "text"
    assert target["ref"].startswith("blob://")
    assert BlobStore(log.root / "blobs").read(target["ref"]) == ("大" * 200).encode("utf-8")

    assert l3.data["turn"] == 9
    assert set(l3.data["summary"]) == {"decisions", "pending", "points"}
    assert l3.data["summary"]["decisions"]
    assert "### 决策" in l3.data["rendered"]
    assert "### 未完成事项" in l3.data["rendered"]
    assert l3.data["summary_units"] <= 120
    assert 6 < max(l3.data["source_seqs"]) < l3.seq


def test_projection_after_compaction_is_deterministic_and_hides_offloaded_bodies(
    tmp_path: Path,
) -> None:
    log = _build_log(tmp_path / "session")
    CompactionEngine(log, config=_config()).run_turn(3)

    nodes = project(log.load())
    rendered = surface_json(nodes)

    assert rendered == surface_json(project(log.load()))
    assert rendered == surface_json(project(SessionLog(log.root, clock=_clock).load()))
    assert "大" * 200 not in rendered
    assert "工" * 500 not in rendered
    assert any(node.kind == "summary" for node in nodes)
    assert surface_units(nodes, _config().weights) <= 500


def test_l1_alone_prunes_oversized_tool_results(tmp_path: Path) -> None:
    log = _build_log(tmp_path / "session")
    engine = CompactionEngine(log, config=replace(_config(), max_context_units=900))

    report = engine.run_turn(1)

    assert [step.level for step in report.steps] == [1]
    tool_result = next(node for node in project(log.load()) if node.kind == "tool_result")
    assert tool_result.payload["pruned"] is True
    assert "已裁剪" in str(tool_result.payload["content"])
    assert "工" * 500 not in str(tool_result.payload["content"])


def test_weighted_budget_counts_cjk_per_char_and_english_per_word() -> None:
    assert measure_units("你好世界") == 4.0
    assert measure_units("hello world") == 3.0
    assert measure_units("hello world") < len("hello world")
    assert trim_head("你好世界", 2.0) == "你好"
    assert trim_head("hello world", 1.5) == "hello"

    chinese = "决策 " + "很长的中文说明" * 20
    english = "decision " + "a long english explanation " * 20
    assert measure_units(english) < len(english)
    assert measure_units(chinese) > measure_units("decision")
