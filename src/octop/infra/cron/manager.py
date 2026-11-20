"""CronManager — process-wide singleton that owns all user-defined scheduled CronJob instances."""

from __future__ import annotations

import asyncio
import datetime as dt
import logging
import random
import time
import uuid
from contextlib import suppress
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Any, Awaitable
from zoneinfo import ZoneInfo

from apscheduler.events import EVENT_JOB_MISSED, JobEvent
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.date import DateTrigger

from octop.i18n import tr
from octop.infra.connectors.crypto import decrypt_credentials
from octop.infra.connectors.gateway.adapters.agently_cli import read_auth_status
from octop.infra.connectors.gateway.agently_watch import AgentlyWatchManager
from octop.infra.cron.delivery import CronDeliveryService
from octop.infra.cron.job import CronJob
from octop.infra.cron.trigger import (
    ONE_SHOT_MISFIRE_GRACE_SECONDS,
    RECURRING_MISFIRE_GRACE_SECONDS,
    AgentlyMailTrigger,
    build_trigger,
    one_shot_disposition,
)
from octop.infra.db.lease import LEASE_SECONDS, RECONCILE_SECONDS, RENEW_SECONDS
from octop.infra.db.repos.audit import ACTOR_SYSTEM
from octop.infra.db.repos.cron_runs import (
    RUN_STATUS_ERROR,
    RUN_STATUS_SKIPPED,
    TRIGGER_KIND_CATCHUP,
    TRIGGER_KIND_MANUAL,
    TRIGGER_KIND_SCHEDULE,
)
from octop.infra.errors import ErrorCode, OctopError
from octop.infra.gateway.threads import ThreadRegistry
from octop.infra.utils.locale import resolve_user_locale

if TYPE_CHECKING:
    from octop.infra.db.repos.connectors import ConnectorRow
    from octop.infra.db.repos.cron import CronJobRow
    from octop.infra.db.services import RepoBundle
    from octop.infra.gateway.gateway import Gateway

from octop.infra.cron.task_type import normalize_cron_task_type, require_cron_name
from octop.infra.db.repos._base import UNSET

logger = logging.getLogger(__name__)


@dataclass
class CronCreateSpec:
    """Input spec for creating a new cron job."""

    cron_id: str
    agent_id: str
    user_id: int
    trigger: str
    prompt: str
    name: str | None = None
    session_key: str | None = None
    fresh_thread: bool = False
    model: str | None = None
    task_type: str = "agent"
    mcp_servers: list[str] = field(default_factory=list)
    enabled: bool = True
    timezone: str | None = None
    max_retries: int = 0
    retry_backoff_seconds: int = 60
    catch_up_misses: int = 0
    meta: dict[str, Any] = field(default_factory=dict)
    username: str | None = None


class CronManager:
    """Process-wide singleton: owns APScheduler + all CronJob instances."""

    def __init__(
        self,
        *,
        gateway: Gateway,
        delivery_service: CronDeliveryService,
        repos: RepoBundle,
        timezone: str = "Asia/Shanghai",
        instance_id: str | None = None,
    ) -> None:
        self._gateway = gateway
        self._delivery_service = delivery_service
        self._repos = repos
        self._timezone = timezone
        self._instance_id = instance_id or uuid.uuid4().hex
        self._scheduler: AsyncIOScheduler = AsyncIOScheduler(timezone=timezone)
        self._scheduler.add_listener(self._on_job_missed, EVENT_JOB_MISSED)
        self._lock = asyncio.Lock()
        self._mail_watch = AgentlyWatchManager()
        # Process-level jobs (e.g. TLS auto-renew) that must survive reload_from_db.
        self._system_job_ids: set[str] = set()
        self._scheduled_spec: dict[str, str] = {}
        self._reconcile_task: asyncio.Task[None] | None = None
        self._serve_background = True
        # Planned fire time per job id, captured when APScheduler advances it.
        self._slots: dict[str, int] = {}
        # Detached run tasks. Holding a reference keeps the event loop from
        # garbage-collecting a fire-and-forget run mid-flight.
        self._inflight: set[asyncio.Task[Any]] = set()

    def replace_repos(self, repos: RepoBundle) -> None:
        """Point cron persistence at a rebound control-plane pool."""
        self._repos = repos
        self._delivery_service.replace_repos(repos)

    async def boot(self, *, serve_background: bool = True) -> None:
        self._serve_background = serve_background
        self._scheduler.start()
        if not serve_background:
            logger.info("CronManager booted without background schedules")
            return
        # Capture the persisted next fire time before reconcile overwrites it;
        # it is the only reliable marker of where the previous process stopped.
        previous = {
            row.cron_id: row.next_run_at
            for row in self._repos.cron_repo.list_all(include_disabled=False)
        }
        # A run owned by a process that died can never finish; surface it instead
        # of leaving a permanent `running` row in the history.
        closed = self._repos.cron_run_repo.close_stale_running(older_than_seconds=LEASE_SECONDS)
        if closed:
            logger.warning("closed %d interrupted cron run(s)", closed)
        await self.reconcile_user_jobs()
        await self._recover_downtime(previous)
        self._reconcile_task = asyncio.create_task(self._reconcile_loop(), name="cron-reconcile")
        logger.info("CronManager booted; instance %s", self._instance_id)

    async def reload_from_db(self) -> None:
        """Drop user cron schedules and re-register enabled jobs from the DB.

        Used after backup/migration restore so APScheduler matches the replaced
        ``cron_jobs`` table without a process restart. System jobs registered via
        :meth:`schedule_system_job` are left in place.
        """
        async with self._lock:
            await self._mail_watch.close()
            self._scheduled_spec.clear()
        await self.reconcile_user_jobs()
        logger.info("CronManager reloaded from DB")

    async def shutdown(self) -> None:
        task = self._reconcile_task
        self._reconcile_task = None
        if task is not None:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        for run in list(self._inflight):
            run.cancel()
        if self._inflight:
            await asyncio.gather(*self._inflight, return_exceptions=True)
        await self._mail_watch.close()
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)
            logger.info("CronManager shut down")

    async def reconcile_user_jobs(self) -> None:
        """Match local schedules to enabled rows. Execution itself still claims a lease."""
        async with self._lock:
            rows = self._repos.cron_repo.list_all(include_disabled=False)
            wanted = {row.cron_id: row for row in rows}
            for job in self._scheduler_jobs():
                job_id = getattr(job, "id", None)
                if not isinstance(job_id, str) or job_id in self._system_job_ids:
                    continue
                if job_id not in wanted:
                    self._scheduled_spec.pop(job_id, None)
                    await self._mail_watch.unsubscribe(job_id)
                    self._scheduler.remove_job(job_id)
            for cron_id in list(self._scheduled_spec):
                if cron_id not in wanted and cron_id not in self._system_job_ids:
                    await self._unschedule(cron_id)
            for row in rows:
                if (
                    self._scheduled_spec.get(row.cron_id) == self._spec_key(row)
                    and self._schedule_is_attached(row)
                ):
                    continue
                await self._unschedule(row.cron_id)
                self._schedule(row)

    async def _reconcile_loop(self) -> None:
        while True:
            await asyncio.sleep(RECONCILE_SECONDS + random.uniform(0, 5))
            try:
                await self.reconcile_user_jobs()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("cron reconcile failed")

    def _scheduler_jobs(self) -> list[Any]:
        raw = self._scheduler.get_jobs()
        return raw if isinstance(raw, list) else []

    def _next_run_ts(self, cron_id: str) -> int | None:
        job = self._scheduler.get_job(cron_id)
        fire = getattr(job, "next_run_time", None)
        try:
            return int(fire.timestamp()) if fire is not None else None
        except (AttributeError, TypeError, ValueError):
            return None

    async def create(self, spec: CronCreateSpec | None = None, **kwargs: Any) -> CronJobRow:
        if spec is None:
            spec = CronCreateSpec(**kwargs)
        self._mail_source(spec.trigger, spec.user_id)
        session_key = spec.session_key or ThreadRegistry.dashboard_key(
            agent_id=spec.agent_id,
            user_id=spec.user_id,
        )
        await self._ensure_session(
            session_key,
            agent_id=spec.agent_id,
            user_id=spec.user_id,
        )
        async with self._lock:
            self._repos.cron_repo.create(
                cron_id=spec.cron_id,
                agent_id=spec.agent_id,
                user_id=spec.user_id,
                name=require_cron_name(spec.name, prompt=spec.prompt, cron_id=spec.cron_id),
                trigger=spec.trigger,
                prompt=spec.prompt,
                session_key=session_key,
                fresh_thread=spec.fresh_thread,
                model=(spec.model or "").strip() or None,
                task_type=normalize_cron_task_type(spec.task_type),
                mcp_servers=list(spec.mcp_servers or []),
                enabled=spec.enabled,
                timezone=spec.timezone or "",
                max_retries=spec.max_retries,
                retry_backoff_seconds=spec.retry_backoff_seconds,
                catch_up_misses=spec.catch_up_misses,
            )
            row = self._repos.cron_repo.get(spec.cron_id)
            assert row is not None
            if spec.enabled:
                self._schedule(row)
                row = self._repos.cron_repo.get(spec.cron_id)
                assert row is not None
            self._repos.audit_repo.write(
                actor=spec.username or str(spec.user_id),
                action="cron.create",
                target=spec.cron_id,
                payload=spec.prompt[:80],
            )
            logger.info("CronJob %s created for agent %s", spec.cron_id, spec.agent_id)
            return row

    def get(self, cron_id: str) -> CronJobRow | None:
        return self._repos.cron_repo.get(cron_id)

    def list_by_agent(
        self,
        agent_id: str,
        *,
        include_disabled: bool = True,
        user_id: int | None = None,
    ) -> list[CronJobRow]:
        return self._repos.cron_repo.list_by_agent(
            agent_id,
            include_disabled=include_disabled,
            user_id=user_id,
        )

    def list_all(self, *, include_disabled: bool = True) -> list[CronJobRow]:
        return self._repos.cron_repo.list_all(include_disabled=include_disabled)

    def list_runs(self, cron_id: str, *, limit: int = 20) -> list[dict[str, Any]]:
        return [
            run.to_public_dict()
            for run in self._repos.cron_run_repo.list_for_job(cron_id, limit=limit)
        ]

    async def update(
        self,
        cron_id: str,
        *,
        trigger: str | None = None,
        name: str | None = None,
        prompt: str | None = None,
        session_key: str | None = None,
        fresh_thread: bool | None = None,
        enabled: int | None = None,
        task_type: str | None = None,
        model: str | None | object = UNSET,
        mcp_servers: list[str] | None | object = UNSET,
        timezone: str | None = None,
        max_retries: int | None = None,
        retry_backoff_seconds: int | None = None,
        catch_up_misses: int | None = None,
    ) -> CronJobRow:
        enabled_bool: bool | None = bool(enabled) if enabled is not None else None
        async with self._lock:
            existing = self._repos.cron_repo.get(cron_id)
            if existing is None:
                raise OctopError(ErrorCode.NOT_FOUND, f"cron job {cron_id!r} not found")
            trigger_changed = trigger is not None and trigger != existing.trigger
            timezone_changed = timezone is not None and timezone != existing.timezone
            enabled_changed = enabled_bool is not None and enabled_bool != bool(existing.enabled)
            # Validate a new trigger, or a mailbox, before persisting. Echoing the
            # current trigger on a rename must not re-check authorization.
            if trigger_changed or (enabled_bool is True and not existing.enabled):
                self._mail_source(
                    trigger if trigger is not None else existing.trigger,
                    existing.user_id,
                )
            repo_kwargs: dict[str, Any] = {
                "trigger": trigger,
                "name": name,
                "prompt": prompt,
                "session_key": session_key,
                "fresh_thread": fresh_thread,
                "enabled": enabled_bool,
            }
            if task_type is not None:
                repo_kwargs["task_type"] = normalize_cron_task_type(task_type)
            if model is not UNSET:
                raw = model if isinstance(model, str) else None
                repo_kwargs["model"] = (raw or "").strip() or None
            if mcp_servers is not UNSET:
                repo_kwargs["mcp_servers"] = (
                    list(mcp_servers) if isinstance(mcp_servers, list) else []
                )
            if timezone is not None:
                repo_kwargs["timezone"] = timezone
            if max_retries is not None:
                repo_kwargs["max_retries"] = max_retries
            if retry_backoff_seconds is not None:
                repo_kwargs["retry_backoff_seconds"] = retry_backoff_seconds
            if catch_up_misses is not None:
                repo_kwargs["catch_up_misses"] = catch_up_misses
            self._repos.cron_repo.update(cron_id, **repo_kwargs)
            row = self._repos.cron_repo.get(cron_id)
            if row is None:
                raise OctopError(ErrorCode.NOT_FOUND, f"cron job {cron_id!r} not found")
            if self._schedule_needs_rebuild(
                existing,
                row,
                trigger_changed=trigger_changed or timezone_changed,
                enabled_changed=enabled_changed,
            ):
                await self._unschedule(cron_id)
                if row.enabled:
                    self._schedule(row)
                    row = self._repos.cron_repo.get(cron_id)
                    if row is None:
                        raise OctopError(ErrorCode.NOT_FOUND, f"cron job {cron_id!r} not found")
            logger.info("CronJob %s updated", cron_id)
            return row

    def _schedule_needs_rebuild(
        self,
        existing: Any,
        row: Any,
        *,
        trigger_changed: bool,
        enabled_changed: bool,
    ) -> bool:
        """Whether this update must drop and recreate the pending run.

        Name, prompt, model, and session edits keep an interval's deadline.
        A trigger or enabled change rebuilds it. An enabled job that is missing
        from the scheduler (or its mail watch) is attached again.
        """
        if not row.enabled:
            return bool(existing.enabled)
        if trigger_changed or enabled_changed:
            return True
        return not self._schedule_is_attached(row)

    def _schedule_is_attached(self, row: Any) -> bool:
        if str(row.trigger).startswith("agently:"):
            return self._mail_watch.has_job(row.cron_id)
        return self._scheduler.get_job(row.cron_id) is not None

    async def delete(self, cron_id: str) -> None:
        async with self._lock:
            await self._unschedule(cron_id)
            self._repos.cron_repo.delete(cron_id)
            self._repos.audit_repo.write(actor=ACTOR_SYSTEM, action="cron.delete", target=cron_id)
            logger.info("CronJob %s deleted", cron_id)

    async def run_now(self, cron_id: str, *, wait: bool = False) -> str:
        """Trigger a manual run and return its run id.

        ``wait`` keeps the CLI contract: the caller awaits the bookkeeping and
        sees failures. The HTTP path returns the run id immediately so the
        dashboard can follow the same record the worker writes.
        """
        row = self._repos.cron_repo.get(cron_id)
        if row is None:
            raise OctopError(ErrorCode.NOT_FOUND, f"cron job {cron_id!r} not found")
        logger.info("CronJob %s triggered manually", cron_id)
        run = self._repos.cron_run_repo.start(
            cron_id,
            trigger_kind=TRIGGER_KIND_MANUAL,
            scheduled_for=None,
        )
        assert run is not None
        if wait:
            return await self._execute_run(cron_id, run.run_id, raise_on_error=True, force=True)
        self._spawn(self._execute_run(cron_id, run.run_id, raise_on_error=False, force=True))
        return run.run_id

    def _spawn(self, coro: Awaitable[Any]) -> asyncio.Task[Any]:
        """Detach a run from the scheduler callback that triggered it."""
        task = asyncio.ensure_future(coro)
        self._inflight.add(task)

        def _finished(done: asyncio.Task[Any]) -> None:
            self._inflight.discard(done)
            if done.cancelled():
                return
            exc = done.exception()
            if exc is not None:
                logger.error("cron run task failed", exc_info=exc)

        task.add_done_callback(_finished)
        return task

    async def _on_schedule(self, cron_id: str) -> None:
        """Scheduler callback: record the slot, then hand execution to a task.

        Nothing here awaits the agent turn, so a slow run can never delay the
        next tick of any other job.
        """
        scheduled_for = self._slots.get(cron_id) or int(time.time())
        next_ts = self._next_run_ts(cron_id)
        if next_ts is not None:
            self._slots[cron_id] = next_ts
        with suppress(Exception):
            self._repos.cron_repo.update_schedule_state(cron_id, next_run_at=next_ts)
        run = self._repos.cron_run_repo.start(
            cron_id,
            trigger_kind=TRIGGER_KIND_SCHEDULE,
            scheduled_for=scheduled_for,
        )
        if run is None:
            logger.info("CronJob %s slot %s already recorded; skipping", cron_id, scheduled_for)
            return
        self._spawn(self._execute_run(cron_id, run.run_id, raise_on_error=False, force=False))

    async def _execute_run(
        self,
        cron_id: str,
        run_id: str,
        *,
        raise_on_error: bool,
        force: bool,
    ) -> str:
        """Execute one run record, retrying per the job's persisted policy."""
        row = self._repos.cron_repo.get(cron_id)
        max_attempts = max(0, row.max_retries) + 1 if row is not None else 1
        backoff = max(1, row.retry_backoff_seconds) if row is not None else 60
        token: str | None = None
        try:
            for attempt in range(1, max_attempts + 1):
                claimed = self._repos.cron_repo.claim_run(
                    cron_id,
                    owner=self._instance_id,
                    lease_seconds=LEASE_SECONDS,
                    force=force,
                )
                if claimed is None:
                    if attempt == 1:
                        self._repos.cron_run_repo.finish(
                            run_id,
                            status=RUN_STATUS_SKIPPED,
                            error="another run was already in progress",
                        )
                        if raise_on_error:
                            raise OctopError(
                                ErrorCode.CRON_ALREADY_RUNNING,
                                f"cron job {cron_id!r} is already running",
                            )
                        logger.info("CronJob %s skipped; run lease held elsewhere", cron_id)
                        return run_id
                    self._repos.cron_run_repo.finish(
                        run_id,
                        status=RUN_STATUS_ERROR,
                        error="run lease was unavailable before the retry",
                    )
                    return run_id
                token = str(claimed.run_lease_token or "")
                ok, note = await self._execute_claimed(
                    claimed, raise_on_error=raise_on_error, run_id=run_id
                )
                if not ok and token:
                    # CronJob.run() releases the lease when it records a result;
                    # release again so a retry is never blocked by a stale lease.
                    self._repos.cron_repo.release_run_lease(cron_id, token=token)
                token = None
                if ok:
                    self._repos.cron_run_repo.finish(run_id, status="ok", note=note)
                    return run_id
                latest = self._repos.cron_repo.get(cron_id)
                error = (latest.last_error if latest is not None else None) or "run failed"
                if attempt >= max_attempts:
                    self._repos.cron_run_repo.finish(run_id, status=RUN_STATUS_ERROR, error=error)
                    return run_id
                logger.warning(
                    "CronJob %s attempt %d/%d failed; retrying in %ds",
                    cron_id,
                    attempt,
                    max_attempts,
                    backoff * attempt,
                )
                self._repos.cron_run_repo.mark_attempt(
                    run_id, attempt=attempt + 1, error=error
                )
                await asyncio.sleep(backoff * attempt)
            return run_id
        except asyncio.CancelledError:
            self._repos.cron_run_repo.finish(
                run_id,
                status=RUN_STATUS_ERROR,
                error="run cancelled: the server is shutting down",
            )
            if token:
                self._repos.cron_repo.release_run_lease(cron_id, token=token)
            raise
        except BaseException as exc:
            self._repos.cron_run_repo.finish(run_id, status=RUN_STATUS_ERROR, error=str(exc))
            raise
        finally:
            await self._finish_one_shot(cron_id)
            with suppress(Exception):
                self._repos.cron_run_repo.prune(cron_id)

    async def _execute_claimed(
        self,
        row: Any,
        *,
        raise_on_error: bool,
        run_id: str,
    ) -> tuple[bool, str | None]:
        token = str(row.run_lease_token or "")
        if not token:
            return False, None
        stop = asyncio.Event()

        async def _renew() -> None:
            while True:
                try:
                    await asyncio.wait_for(stop.wait(), timeout=RENEW_SECONDS)
                    return
                except TimeoutError:
                    if self._repos.cron_repo.renew_run_lease(
                        row.cron_id,
                        token=token,
                        lease_seconds=LEASE_SECONDS,
                    ):
                        continue
                    self._repos.cron_repo.release_run_lease(row.cron_id, token=token)
                    return

        renew_task = asyncio.create_task(_renew())
        job = self._make_job(row)
        run_task = asyncio.create_task(
            job.run(
                raise_on_error=raise_on_error,
                lease_token=token,
            )
        )
        try:
            done, _pending = await asyncio.wait(
                {renew_task, run_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            if run_task not in done:
                run_task.cancel()
                with suppress(asyncio.CancelledError):
                    await run_task
                logger.warning("CronJob %s lost its run lease", row.cron_id)
                self._repos.cron_run_repo.finish(
                    run_id,
                    status=RUN_STATUS_ERROR,
                    error="run lease was lost while executing",
                )
                if raise_on_error:
                    raise OctopError(
                        ErrorCode.CRON_ALREADY_RUNNING,
                        f"cron job {row.cron_id!r} lost its run lease",
                    )
                return False, None
            stop.set()
            return bool(await run_task), job.last_note
        finally:
            # The run lives on its own task so the lease can be renewed beside it.
            # Cancelling the caller (CLI ``run-now --wait``) must cancel that run
            # too, and drop the lease when the result was never recorded.
            stop.set()
            renew_task.cancel()
            if not run_task.done():
                run_task.cancel()
            for task in (run_task, renew_task):
                with suppress(asyncio.CancelledError, Exception):
                    await task
            if run_task.cancelled():
                self._repos.cron_repo.release_run_lease(row.cron_id, token=token)

    async def _finish_one_shot(self, cron_id: str) -> None:
        """Disable a ``date:`` job after it runs, success or failure."""
        row = self._repos.cron_repo.get(cron_id)
        if row is None or not row.trigger.startswith("date:"):
            return
        if row.last_status not in {"ok", "error"}:
            return
        if row.enabled:
            self._repos.cron_repo.update(cron_id, enabled=False)
        await self._unschedule(cron_id)

    def _make_job(self, row: Any) -> CronJob:
        return CronJob.from_row(
            row,
            delivery_service=self._delivery_service,
            cron_repo=self._repos.cron_repo,
            audit_repo=self._repos.audit_repo,
        )

    def _on_job_missed(self, event: JobEvent) -> None:
        """A one-shot that the scheduler skipped after the grace window is finished."""
        job_id = event.job_id
        if not job_id or job_id in self._system_job_ids:
            return
        row = self._repos.cron_repo.get(job_id)
        if row is None or not row.trigger.startswith("date:"):
            return
        if row.last_status in {"ok", "error"} or row.last_run_at is not None:
            if row.enabled:
                self._repos.cron_repo.update(job_id, enabled=False)
            return
        slot = self._slots.pop(job_id, None)
        if slot is not None:
            self._repos.cron_run_repo.record_missed_slot(
                job_id,
                scheduled_for=slot,
                reason="missed the one-shot window while the server was unavailable",
            )
        if self._repos.cron_repo.mark_missed(job_id):
            logger.info("CronJob %s missed its one-shot window; disabling", job_id)

    def _job_timezone(self, row: Any) -> str:
        return (getattr(row, "timezone", "") or "").strip() or self._timezone

    def _spec_key(self, row: Any) -> str:
        """What a schedule depends on: the expression *and* its timezone."""
        return f"{self._job_timezone(row)}\x00{row.trigger}"

    def _schedule(self, row: Any) -> None:
        if not row.enabled:
            return
        tz_name = self._job_timezone(row)
        try:
            trigger = build_trigger(row.trigger, timezone=tz_name)
            source = self._mail_source(row.trigger, row.user_id)
        except OctopError:
            logger.warning(
                "CronJob %s has invalid trigger %r; skipping schedule",
                row.cron_id,
                row.trigger,
            )
            return
        if isinstance(trigger, AgentlyMailTrigger):
            assert source is not None
            assert source.credential_blob is not None
            creds = decrypt_credentials(self._repos.secret_repo, source.credential_blob)

            async def on_mail(message_id: str) -> None:
                await self._run_mail_event(row.cron_id, message_id)

            self._mail_watch.subscribe(source.instance_id, row.cron_id, creds, on_mail)
            self._scheduled_spec[row.cron_id] = self._spec_key(row)
            self._repos.cron_repo.update_schedule_state(
                row.cron_id, next_run_at=None, timezone=row.timezone or tz_name
            )
            return
        grace = RECURRING_MISFIRE_GRACE_SECONDS
        if isinstance(trigger, DateTrigger):
            run_at = trigger.run_date
            tzinfo = run_at.tzinfo or ZoneInfo(tz_name)
            if run_at.tzinfo is None:
                run_at = run_at.replace(tzinfo=tzinfo)
            action = one_shot_disposition(
                run_at,
                now=dt.datetime.now(tzinfo),
                last_run_at=row.last_run_at,
            )
            if action == "miss":
                self._repos.cron_run_repo.record_missed_slot(
                    row.cron_id,
                    scheduled_for=int(run_at.timestamp()),
                    reason="one-shot time passed while the server was unavailable",
                )
                if self._repos.cron_repo.mark_missed(row.cron_id):
                    logger.info("CronJob %s missed its one-shot time; disabling", row.cron_id)
                self._repos.cron_repo.update_schedule_state(row.cron_id, next_run_at=None)
                return
            if action == "close":
                self._repos.cron_repo.update(row.cron_id, enabled=False)
                self._repos.cron_repo.update_schedule_state(row.cron_id, next_run_at=None)
                logger.info("CronJob %s one-shot already ran; disabling", row.cron_id)
                return
            grace = ONE_SHOT_MISFIRE_GRACE_SECONDS
        if self._scheduler.get_job(row.cron_id):
            self._scheduler.remove_job(row.cron_id)
        self._scheduler.add_job(
            self._on_schedule,
            trigger=trigger,
            args=[row.cron_id],
            id=row.cron_id,
            replace_existing=True,
            misfire_grace_time=grace,
            coalesce=True,
            max_instances=1,
        )
        scheduled = self._scheduler.get_job(row.cron_id)
        next_fire = getattr(scheduled, "next_run_time", None)
        next_ts: int | None
        try:
            next_ts = int(next_fire.timestamp()) if next_fire is not None else None
        except (AttributeError, TypeError, ValueError):
            next_ts = None
        if next_ts is not None:
            self._slots[row.cron_id] = next_ts
        self._repos.cron_repo.update_schedule_state(
            row.cron_id, next_run_at=next_ts, timezone=row.timezone or tz_name
        )
        self._scheduled_spec[row.cron_id] = self._spec_key(row)

    def _missed_slots(self, row: Any, *, reference: int, now: dt.datetime) -> list[int]:
        """Fire times the job should have hit between ``reference`` and *now*."""
        tz = ZoneInfo(self._job_timezone(row))
        try:
            trigger = build_trigger(row.trigger, timezone=tz.key)
        except OctopError:
            return []
        if isinstance(trigger, (AgentlyMailTrigger, DateTrigger)):
            return []
        slots: list[int] = []
        cursor = dt.datetime.fromtimestamp(reference - 1, tz)
        for _ in range(500):
            fire = trigger.get_next_fire_time(cursor, cursor)
            if fire is None or fire > now:
                break
            slots.append(int(fire.timestamp()))
            cursor = fire
        return slots

    async def _recover_downtime(self, previous: dict[str, int | None]) -> None:
        """Turn the gap since the last persisted fire time into explicit records.

        Recurring jobs never replay silently: with ``catch_up_misses`` the last
        N slots run on boot, otherwise every missed slot is recorded as
        ``missed`` so the dashboard can explain the gap.
        """
        if not previous:
            return
        now = dt.datetime.now(dt.timezone.utc)
        for row in self._repos.cron_repo.list_all(include_disabled=False):
            reference = previous.get(row.cron_id) or row.last_run_at
            if reference is None:
                continue
            slots = self._missed_slots(row, reference=reference, now=now)
            if not slots:
                continue
            budget = max(0, row.catch_up_misses)
            replay = slots[-budget:] if budget else []
            for slot in slots[: len(slots) - len(replay)][:50]:
                self._repos.cron_run_repo.record_missed_slot(
                    row.cron_id,
                    scheduled_for=slot,
                    reason="scheduled time passed while the server was offline",
                )
            if replay:
                logger.info("CronJob %s catching up %d missed slot(s)", row.cron_id, len(replay))
                self._spawn(self._run_catch_up(row.cron_id, replay))

    async def _run_catch_up(self, cron_id: str, slots: list[int]) -> None:
        for slot in slots:
            run = self._repos.cron_run_repo.start(
                cron_id,
                trigger_kind=TRIGGER_KIND_CATCHUP,
                scheduled_for=slot,
            )
            if run is None:
                continue
            try:
                await self._execute_run(cron_id, run.run_id, raise_on_error=False, force=False)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("cron catch-up failed for %s at %s", cron_id, slot)
            await asyncio.sleep(0)

    async def _unschedule(self, cron_id: str) -> None:
        self._scheduled_spec.pop(cron_id, None)
        self._slots.pop(cron_id, None)
        await self._mail_watch.unsubscribe(cron_id)
        if self._scheduler.get_job(cron_id):
            self._scheduler.remove_job(cron_id)

    def _mailbox_authorized(self, source: ConnectorRow) -> bool:
        if source.credential_blob is None:
            return False
        creds = decrypt_credentials(self._repos.secret_repo, source.credential_blob)
        try:
            data = read_auth_status({**creds, "instance_id": source.instance_id})
        except (OSError, ValueError):
            return False
        return data.get("logged_in") is True and data.get("token_status") != "expired"

    def _mail_source(self, spec: str, user_id: int) -> ConnectorRow | None:
        trigger = build_trigger(spec)
        if not isinstance(trigger, AgentlyMailTrigger):
            return None
        source = self._repos.connector_repo.get(trigger.instance_id)
        if (
            source is None
            or source.kind != "agently-cli"
            or source.status != "active"
            or not source.has_credentials
        ):
            raise OctopError(ErrorCode.CRON_TRIGGER_INVALID, "Agent Mail source is unavailable")
        if source.user_id != user_id and not source.shared:
            raise OctopError(
                ErrorCode.FORBIDDEN, "Agent Mail source is not visible to the job owner"
            )
        if not self._mailbox_authorized(source):
            raise OctopError(ErrorCode.CRON_TRIGGER_INVALID, "Agent Mail mailbox is not authorized")
        return source

    async def _run_mail_event(self, cron_id: str, message_id: str) -> None:
        row = self._repos.cron_repo.get(cron_id)
        if row is None or not row.enabled:
            return
        # Recheck visibility after sharing, credentials, or the job has changed.
        source = self._mail_source(row.trigger, row.user_id)
        if source is None:
            return
        locale = resolve_user_locale(user_repo=self._repos.user_repo, user_id=row.user_id)
        prompt = (
            row.prompt
            + "\n\n"
            + tr(
                "connector.agently.new_mail_event",
                locale,
                tool=source.mcp_server_name + "_agently_read",
                message_id=message_id,
            )
        )
        # The mailbox stream is broadcast. Claiming here keeps a single delivery
        # even when every instance is watching the same mailbox.
        claimed = self._repos.cron_repo.claim_run(
            cron_id,
            owner=self._instance_id,
            lease_seconds=LEASE_SECONDS,
        )
        if claimed is None:
            logger.info("CronJob %s mail event skipped; run lease held elsewhere", cron_id)
            return
        run = self._repos.cron_run_repo.start(
            cron_id,
            trigger_kind="mail",
            scheduled_for=None,
        )
        if run is None:
            return
        event_row = replace(
            claimed,
            prompt=prompt,
            mcp_servers=list(dict.fromkeys([source.mcp_server_name, *claimed.mcp_servers])),
        )
        try:
            ok, _note = await self._execute_claimed(
                event_row, raise_on_error=False, run_id=run.run_id
            )
            self._repos.cron_run_repo.finish(
                run.run_id,
                status="ok" if ok else RUN_STATUS_ERROR,
                error=None if ok else "mail event delivery failed",
            )
        finally:
            with suppress(Exception):
                self._repos.cron_run_repo.prune(cron_id)

    async def reload_mail_watches(self) -> None:
        """Rebuild every mailbox watch after a full cron reload."""
        async with self._lock:
            await self._mail_watch.close()
            for row in self._repos.cron_repo.list_all(include_disabled=False):
                if row.trigger.startswith("agently:"):
                    self._schedule(row)

    async def sync_mail_watch(self, instance_id: str) -> None:
        """Start or stop watches for one mailbox without touching others."""
        async with self._lock:
            source = self._repos.connector_repo.get(instance_id)
            available = (
                source is not None
                and source.kind == "agently-cli"
                and source.status == "active"
                and source.has_credentials
                and self._mailbox_authorized(source)
            )
            if not available:
                await self._mail_watch.stop_instance(instance_id)
                return
            for row in self._repos.cron_repo.list_all(include_disabled=False):
                if row.trigger == f"agently:{instance_id}" and not self._mail_watch.has_job(
                    row.cron_id
                ):
                    self._schedule(row)

    async def stop_mail_watch(self, instance_id: str) -> None:
        await self._mail_watch.stop_instance(instance_id)

    async def resume_mail_watch(self, instance_id: str) -> None:
        await self.sync_mail_watch(instance_id)

    async def _ensure_session(self, session_key: str, *, agent_id: str, user_id: int) -> None:
        registry = self._gateway.thread_registry
        existing = registry.get_session(session_key)
        if existing is not None:
            if existing.agent_id != agent_id:
                msg = (
                    f"session {session_key!r} belongs to agent {existing.agent_id!r}, "
                    f"not {agent_id!r}"
                )
                raise ValueError(msg)
            if existing.user_id != user_id:
                msg = (
                    f"session {session_key!r} belongs to user {existing.user_id!r}, not {user_id!r}"
                )
                raise ValueError(msg)
            return
        parts = session_key.split(":", 3)
        channel_type = parts[1] if len(parts) >= 2 else "cron"
        chat_type = parts[3] if len(parts) >= 4 else ThreadRegistry.CHAT_TYPE_DM
        await registry.get_or_create_by_key(
            session_key=session_key,
            agent_id=agent_id,
            user_id=user_id,
            channel_type=channel_type,
            channel_chat_type=chat_type,
        )

    def schedule_system_job(self, job_id: str, *, trigger: str, func: Any) -> None:
        """Register a process-level job that is not stored in the cron DB."""
        built = build_trigger(trigger, timezone=self._timezone)
        if isinstance(built, AgentlyMailTrigger):
            raise OctopError(
                ErrorCode.CRON_TRIGGER_INVALID, "system jobs cannot use Agent Mail triggers"
            )
        self._system_job_ids.add(job_id)
        self._scheduler.add_job(
            func,
            trigger=built,
            id=job_id,
            replace_existing=True,
            misfire_grace_time=300,
        )

    def unschedule_system_job(self, job_id: str) -> None:
        """Remove a process-level job previously registered via :meth:`schedule_system_job`."""
        self._system_job_ids.discard(job_id)
        if self._scheduler.get_job(job_id):
            self._scheduler.remove_job(job_id)

    def has_system_job(self, job_id: str) -> bool:
        """True when a system job id is currently registered with the scheduler."""
        return self._scheduler.get_job(job_id) is not None
