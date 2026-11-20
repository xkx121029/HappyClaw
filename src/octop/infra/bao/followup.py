"""Bao's follow-through on dispatched work.

A dispatch is not finished when the worker's turn ends — Bao must decide
whether the task actually completed, stalled (and deserves one more nudge), or
needs the user. Only three outcomes are pushed: done, needs decision, failed.
Everything else stays quiet.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from types import SimpleNamespace
from typing import Any

logger = logging.getLogger(__name__)

MAX_FOLLOWUPS = 2
FOLLOWUP_PROMPT = (
    "继续完成上一个任务，不要停在提问上；缺少资料时先用现有信息给出可交付的一版，"
    "并明确列出还缺什么。"
)
_STUCK_MARKERS = (
    "需要更多信息",
    "请提供",
    "无法继续",
    "缺少",
    "不能完成",
    "需要你确认",
    "请确认",
    "还需要资料",
    "请补充",
)


def _clip(value: str | None, limit: int) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else f"{text[:limit]}…"


class BaoFollowupService:
    """Evaluate a finished Bao task, nudge it forward, or notify the user."""

    def __init__(
        self,
        *,
        server: Any,
        gateway: Any,
        task_repo: Any | None = None,
        message_repo: Any | None = None,
        proactive_repo: Any | None = None,
        user_repo: Any | None = None,
    ) -> None:
        services = getattr(server, "services", None)
        self._server = server
        self._gateway = gateway
        self._task_repo = task_repo or services.bao_task_repo
        self._message_repo = message_repo or services.bao_message_repo
        self._proactive_repo = proactive_repo or services.bao_proactive_repo
        self._user_repo = user_repo or services.user_repo

    # ---------------------------------------------------------------- entry

    def on_turn_finished(
        self,
        *,
        thread_id: str,
        agent_id: str,
        status: str,
        result_text: str | None,
        error_text: str | None,
    ) -> None:
        """Sync callback from the WS channel; never raises into the turn."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:  # pragma: no cover - only outside a running loop
            return
        loop.create_task(
            self._evaluate(
                thread_id=thread_id,
                agent_id=agent_id,
                status=status,
                result_text=result_text,
                error_text=error_text,
            )
        )

    # ----------------------------------------------------------- evaluation

    @staticmethod
    def _classify(status: str, result_text: str | None, error_text: str | None) -> tuple[str, str]:
        """Return ``(outcome, eval_status)``.

        ``outcome`` is one of ``done`` / ``needs_decision`` / ``failed`` /
        ``stuck``. ``stuck`` is resolved into a follow-up or an escalation by
        :meth:`_evaluate`.
        """
        if status == "failed":
            return "failed", "failed"
        if status == "awaiting":
            return "needs_decision", "needs_decision"
        text = str(result_text or "").strip()
        error = str(error_text or "").strip()
        if error and text and len(text) < 20:
            return "failed", "failed"
        if _clip(text, 10_000) == "":
            return "stuck", "done_stuck"
        if len(text) < 20:
            return "stuck", "done_stuck"
        if any(marker in text for marker in _STUCK_MARKERS):
            return "stuck", "done_stuck"
        stripped = text.rstrip()
        if stripped.endswith(("?", "？")) or "是否" in text:
            return "needs_decision", "needs_decision"
        return "done", "done_ok"

    async def _evaluate(
        self,
        *,
        thread_id: str,
        agent_id: str,
        status: str,
        result_text: str | None,
        error_text: str | None,
    ) -> None:
        try:
            task = self._task_repo.latest_terminal_for_thread(thread_id, agent_id)
            if task is None:
                return
            outcome, eval_status = self._classify(status, result_text, error_text)
            if outcome == "stuck":
                if task.followup_count < MAX_FOLLOWUPS:
                    await self._nudge(task)
                    return
                outcome = "needs_decision"
                eval_status = "stuck_escalated"
            await self._push(task, outcome, eval_status, result_text, error_text)
            self._task_repo.mark_evaluated(task.id, eval_status)
        except Exception:  # noqa: BLE001 - a background nudge must stay quiet
            logger.exception("bao follow-up evaluation failed for %s", thread_id)

    async def _nudge(self, task: Any) -> None:
        reopened = self._task_repo.record_followup(task.id)
        if reopened is None:  # pragma: no cover - row disappeared
            return
        try:
            await self._wait_for_idle(task.thread_id)
            await self._redispatch(task)
        except Exception as exc:  # noqa: BLE001
            logger.warning("bao follow-up dispatch failed for %s: %s", task.id, exc)
            self._task_repo.complete_running(
                thread_id=task.thread_id,
                agent_id=task.agent_id,
                status="failed",
                error_text=f"follow-up dispatch failed: {exc}",
            )
            self._task_repo.mark_evaluated(task.id, "stuck_escalated")
            return
        self._message_repo.append(
            user_id=task.user_id,
            role="bao",
            text=f"「{task.agent_name}」停在提问上，我已追问一次，让它先给出可交付的一版。",
            intent="followup",
            refs={"task_id": task.id, "agent_id": task.agent_id, "thread_id": task.thread_id},
            task_id=task.id,
        )

    async def _wait_for_idle(self, thread_id: str, *, timeout: float = 5.0) -> None:
        hub = getattr(self._gateway, "ws_hub", None)
        deadline = time.monotonic() + timeout
        while hub is not None and hub.is_turn_active(thread_id):
            if time.monotonic() >= deadline:
                raise RuntimeError("conversation is still replying")
            await asyncio.sleep(0.2)

    async def _redispatch(self, task: Any) -> None:
        from octop.infra.gateway.process.dashboard_turn import (
            DashboardTurn as _DashboardTurn,
        )
        from octop.infra.gateway.process.dashboard_turn import (
            build_dashboard_inbound,
            prepare_dashboard_turn,
        )
        from octop.infra.gateway.threads import ThreadRegistry
        from octop.infra.gateway.ws.ws_channel import WS_CHANNEL_ID

        gateway = self._gateway
        registry = gateway.thread_registry
        thread = registry.get_thread(task.thread_id)
        if thread is None:
            raise RuntimeError("conversation no longer exists")
        user_row = self._user_repo.get(task.user_id)
        if user_row is None:
            raise RuntimeError("task owner no longer exists")
        user = SimpleNamespace(
            id=int(user_row.id),
            username=str(getattr(user_row, "username", "") or ""),
            role=str(getattr(user_row, "role", "user") or "user"),
            is_admin=str(getattr(user_row, "role", "") or "") == "admin",
            locale="zh",
        )
        turn = _DashboardTurn(
            text=FOLLOWUP_PROMPT,
            messages=[{"role": "user", "content": FOLLOWUP_PROMPT}],
            thread_id=task.thread_id,
            session_key=thread.session_key
            or ThreadRegistry.dashboard_key(agent_id=task.agent_id, user_id=user.id),
            conversation_mode=thread.conversation_mode or "craft",
        )
        prepared = await prepare_dashboard_turn(
            self._server,
            agent_id=task.agent_id,
            user=user,
            turn=turn,
        )
        inbound = build_dashboard_inbound(
            agent_id=task.agent_id,
            user_id=user.id,
            prepared=prepared,
            turn=turn,
            ws_connection_id=f"bao-followup:{task.thread_id}",
            user_is_admin=bool(user.is_admin),
        )
        manager = gateway.channel_manager
        if manager is None:
            raise RuntimeError("gateway is not ready")
        # Must use the registered dashboard channel id (``octop-dashboard``);
        # enqueuing under a made-up name silently drops the nudge.
        manager.enqueue(WS_CHANNEL_ID, inbound)

    # ------------------------------------------------------------- pushing

    def _prefs(self, user_id: int) -> dict[str, Any]:
        row = self._user_repo.get(user_id)
        raw = getattr(row, "preferences_json", None) if row is not None else None
        try:
            data = json.loads(raw) if isinstance(raw, str) and raw.strip() else {}
        except (TypeError, ValueError):
            data = {}
        section = data.get("bao") if isinstance(data, dict) else None
        return section if isinstance(section, dict) else {}

    def _muted(self, user_id: int) -> bool:
        return bool(self._prefs(user_id).get("proactive_muted"))

    def _bao_name(self, user_id: int) -> str:
        name = self._prefs(user_id).get("name")
        return name.strip() if isinstance(name, str) and name.strip() else "宝"

    async def _push(
        self,
        task: Any,
        outcome: str,
        eval_status: str,
        result_text: str | None,
        error_text: str | None,
    ) -> None:
        kind = "needs_decision" if outcome == "needs_decision" else outcome
        if kind not in ("done", "needs_decision", "failed"):
            return
        text = self._push_text(task, kind, eval_status, result_text, error_text)
        text = f"{self._bao_name(int(task.user_id))}：{text}"
        claimed, reason = self._proactive_repo.claim(
            user_id=int(task.user_id),
            task_id=task.id,
            kind=kind,
            muted=self._muted(int(task.user_id)),
        )
        if not claimed:
            logger.info("bao push suppressed task=%s kind=%s reason=%s", task.id, kind, reason)
            return
        frame = {
            "type": "dashboard_push",
            "agent_id": task.agent_id,
            "thread_id": task.thread_id,
            "agent_name": task.agent_name,
            "text": text,
        }
        await self._gateway.ws_hub.push_to_user(int(task.user_id), frame)
        # Mirror the notification into the conversation so the page shows the
        # same character speaking when the user comes back.
        self._message_repo.append(
            user_id=int(task.user_id),
            role="bao",
            text=text,
            intent=f"push_{kind}",
            refs={
                "task_id": task.id,
                "agent_id": task.agent_id,
                "thread_id": task.thread_id,
            },
            task_id=task.id,
        )
        logger.info("bao push delivered task=%s kind=%s", task.id, kind)

    @staticmethod
    def _push_text(
        task: Any,
        kind: str,
        eval_status: str,
        result_text: str | None,
        error_text: str | None,
    ) -> str:
        name = _clip(task.agent_name or task.agent_id, 24)
        what = _clip(task.task_text, 40)
        if kind == "done":
            return f"任务完成：{name}「{what}」——{_clip(result_text, 90)}"
        if kind == "failed":
            detail = _clip(error_text or result_text, 90) or "未知错误"
            return f"任务失败：{name}「{what}」——{detail}"
        if eval_status == "stuck_escalated":
            return (
                f"需要你决定：{name}「{what}」已经自动追问 {MAX_FOLLOWUPS} 次仍卡住，"
                f"{_clip(result_text, 80)}"
            )
        if str(task.status) == "awaiting":
            return f"等待你审批：{name}「{what}」停在一个需要确认的步骤。"
        return f"需要你决定：{name}「{what}」——{_clip(result_text, 80)}"


__all__ = ["BaoFollowupService", "FOLLOWUP_PROMPT", "MAX_FOLLOWUPS"]
