"""Run-history, retry, dedupe and downtime recovery for cron jobs.

These cover the behaviours the old ``last_*`` columns could not express:
one row per planned fire time, a bounded retry loop, and an explicit record
for every trigger the server was offline for.
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from octop.config import OctopConfig
from octop.infra.cron.delivery import CronDeliveryService
from octop.infra.cron.manager import CronManager
from octop.infra.db.migrate import run_migrations
from octop.infra.db.pool import SqlitePool
from octop.infra.db.services import build_shared_services
from octop.infra.gateway.threads import ThreadRegistry
from octop.infra.utils.paths import PathLayout
from octop.infra.utils.ulid import new_ulid


def _session_key(agent_id: str, cron_id: str) -> str:
    return ThreadRegistry.make_key(
        agent_id=agent_id,
        channel_type="cron",
        channel_subject_id=cron_id,
        channel_chat_type=ThreadRegistry.CHAT_TYPE_DM,
    )


def _make_services(tmp_path: Path):
    db = SqlitePool(tmp_path / "octop.db")
    run_migrations(db)
    return build_shared_services(db=db, paths=PathLayout(tmp_path), config=OctopConfig())


def _make_agent(services) -> tuple[str, int]:
    uid = services.repos.user_repo.create(
        username=f"u-{new_ulid()}", password_hash="x", role="user"
    )
    aid = new_ulid()
    services.repos.agent_repo.create(agent_id=aid, user_id=uid, name="cron-agent")
    return aid, uid


def _make_manager(services, *, timezone: str = "UTC") -> CronManager:
    gw = MagicMock()
    gw.send = AsyncMock()
    gw.thread_registry = MagicMock()
    mgr = CronManager(
        gateway=gw,
        delivery_service=CronDeliveryService(
            gateway=gw, agent_manager=MagicMock(), repos=services.repos
        ),
        repos=services.repos,
        timezone=timezone,
    )
    scheduler = MagicMock()
    scheduler.running = False
    scheduler.get_job = MagicMock(return_value=None)
    scheduler.get_jobs = MagicMock(return_value=[])
    mgr._scheduler = scheduler
    return mgr


def _create_job(services, aid: str, uid: str, **overrides) -> str:
    cid = new_ulid()
    kwargs = {
        "cron_id": cid,
        "agent_id": aid,
        "user_id": uid,
        "trigger": "interval:60",
        "prompt": "hello",
        "session_key": _session_key(aid, cid),
        "task_type": "text",
    }
    kwargs.update(overrides)
    services.repos.cron_repo.create(**kwargs)
    return cid


def _fake_job(results: list[bool], *, note: str | None = None) -> MagicMock:
    job = MagicMock()
    job.run = AsyncMock(side_effect=results)
    job.last_note = note
    return job


@pytest.mark.asyncio
async def test_failed_run_retries_then_records_ok(tmp_path: Path) -> None:
    services = _make_services(tmp_path)
    aid, uid = _make_agent(services)
    cid = _create_job(services, aid, uid, max_retries=2, retry_backoff_seconds=1)
    mgr = _make_manager(services)
    mgr._make_job = MagicMock(return_value=_fake_job([False, False, True]))

    run_id = await mgr.run_now(cid, wait=True)

    runs = services.repos.cron_run_repo.list_for_job(cid)
    assert len(runs) == 1
    assert runs[0].run_id == run_id
    assert runs[0].status == "ok"
    assert runs[0].attempt == 3


@pytest.mark.asyncio
async def test_retries_stop_at_configured_limit(tmp_path: Path) -> None:
    services = _make_services(tmp_path)
    aid, uid = _make_agent(services)
    cid = _create_job(services, aid, uid, max_retries=1, retry_backoff_seconds=1)
    mgr = _make_manager(services)
    fake = _fake_job([False, False, False])
    mgr._make_job = MagicMock(return_value=fake)

    await mgr.run_now(cid, wait=True)

    runs = services.repos.cron_run_repo.list_for_job(cid)
    assert len(runs) == 1
    assert runs[0].status == "error"
    assert fake.run.await_count == 2


@pytest.mark.asyncio
async def test_duplicate_slot_is_recorded_once(tmp_path: Path) -> None:
    services = _make_services(tmp_path)
    aid, uid = _make_agent(services)
    cid = _create_job(services, aid, uid)
    mgr = _make_manager(services)
    mgr._make_job = MagicMock(return_value=_fake_job([True, True]))
    slot = int(time.time())

    mgr._slots[cid] = slot
    await mgr._on_schedule(cid)
    await mgr._on_schedule(cid)
    await asyncio.gather(*list(mgr._inflight), return_exceptions=True)

    runs = services.repos.cron_run_repo.list_for_job(cid)
    assert [r.scheduled_for for r in runs] == [slot]
    assert runs[0].status == "ok"


@pytest.mark.asyncio
async def test_manual_run_returns_trackable_run_id(tmp_path: Path) -> None:
    services = _make_services(tmp_path)
    aid, uid = _make_agent(services)
    cid = _create_job(services, aid, uid)
    mgr = _make_manager(services)
    mgr._make_job = MagicMock(return_value=_fake_job([True]))

    run_id = await mgr.run_now(cid)

    assert run_id
    await asyncio.gather(*list(mgr._inflight), return_exceptions=True)
    run = services.repos.cron_run_repo.list_for_job(cid)[0]
    assert run.run_id == run_id
    assert run.trigger_kind == "manual"
    assert run.scheduled_for is None
    assert run.status == "ok"


@pytest.mark.asyncio
async def test_degraded_delivery_note_is_stored_on_run(tmp_path: Path) -> None:
    services = _make_services(tmp_path)
    aid, uid = _make_agent(services)
    cid = _create_job(services, aid, uid)
    mgr = _make_manager(services)
    note = "Reminder delivered, but no session history was written: no model is configured."
    mgr._make_job = MagicMock(return_value=_fake_job([True], note=note))

    run_id = await mgr.run_now(cid, wait=True)

    run = services.repos.cron_run_repo.list_for_job(cid)[0]
    assert run.run_id == run_id
    assert run.status == "ok"
    assert run.error is None
    assert run.note == note
    assert run.to_public_dict()["note"] == note


@pytest.mark.asyncio
async def test_downtime_slots_are_recorded_as_missed(tmp_path: Path) -> None:
    services = _make_services(tmp_path)
    aid, uid = _make_agent(services)
    reference = int(time.time()) - 180
    cid = _create_job(services, aid, uid, trigger="cron:* * * * *")
    mgr = _make_manager(services)
    mgr._make_job = MagicMock(return_value=_fake_job([True]))

    await mgr._recover_downtime({cid: reference})
    runs = services.repos.cron_run_repo.list_for_job(cid, limit=50)
    assert runs, "downtime must leave a visible trace"
    assert all(r.status == "missed" for r in runs)
    assert all(r.scheduled_for is not None and r.scheduled_for >= reference for r in runs)


@pytest.mark.asyncio
async def test_downtime_replays_only_the_budgeted_slots(tmp_path: Path) -> None:
    services = _make_services(tmp_path)
    aid, uid = _make_agent(services)
    reference = int(time.time()) - 180
    cid = _create_job(
        services, aid, uid, trigger="cron:* * * * *", catch_up_misses=1
    )
    mgr = _make_manager(services)
    mgr._make_job = MagicMock(return_value=_fake_job([True]))

    await mgr._recover_downtime({cid: reference})
    await asyncio.gather(*list(mgr._inflight), return_exceptions=True)

    runs = services.repos.cron_run_repo.list_for_job(cid, limit=50)
    catch_up = [r for r in runs if r.trigger_kind == "catchup"]
    missed = [r for r in runs if r.status == "missed"]
    assert len(catch_up) == 1
    assert catch_up[0].scheduled_for == max(
        r.scheduled_for for r in runs if r.scheduled_for is not None
    )
    assert missed, "slots beyond the catch-up budget stay visible as missed"


@pytest.mark.asyncio
async def test_recent_next_run_is_not_treated_as_missed(tmp_path: Path) -> None:
    services = _make_services(tmp_path)
    aid, uid = _make_agent(services)
    cid = _create_job(services, aid, uid, trigger="cron:* * * * *")
    mgr = _make_manager(services)
    mgr._make_job = MagicMock(return_value=_fake_job([True]))

    await mgr._recover_downtime({cid: int(time.time()) + 120})

    assert services.repos.cron_run_repo.list_for_job(cid) == []
