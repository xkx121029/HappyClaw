"""Turn persistence and thread titles: history rows, usage and shadow history."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from typing import (
    TYPE_CHECKING,
    Any,
)

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
)

from happyclaw.infra.gateway.process.usage_record import record_turn_usage
from happyclaw.infra.gateway.slash.catalog import spec_for
from happyclaw.infra.gateway.slash.parser import parse_slash
from happyclaw.infra.history.projection import (
    TurnHistoryTracker,
    message_inputs,
)
from happyclaw.infra.utils.locale import resolve_user_locale
from happyclaw.infra.utils.ulid import new_ulid

if TYPE_CHECKING:
    from happyclaw.infra.db.repos.thread_messages import ThreadMessageInput

from happyclaw.infra.gateway.process.processor_base import GlobalProcessorBase, logger


class ProcessorHistoryMixin(GlobalProcessorBase):
    """回合落库与线程标题：历史条目、用量与影子历史。"""

    def _touch_thread_after_turn(self, thread_id: str, title_source: str | None) -> None:
        self._thread_registry.touch_last_active(thread_id)
        # An in-flight AI title must not be overwritten by the raw question.
        if title_source and thread_id not in self._title_inflight:
            self._thread_registry.set_title_if_null(thread_id, title_source)

    def _plain_title(self, thread_id: str) -> str | None:
        """Stored title, or ``None`` when the thread is still untitled.

        Non-string titles (test doubles) count as already set so a mocked
        registry does not start a model call.
        """
        try:
            row = self._thread_registry.get_thread(thread_id)
        except Exception:
            return "set"
        if row is None:
            return ""
        title = getattr(row, "title", None)
        if title is None:
            return None
        if isinstance(title, str):
            return title
        return "set"

    def _schedule_auto_thread_title(
        self, thread_id: str, source: str | None, *, user_id: int
    ) -> None:
        from happyclaw.infra.gateway.process.thread_title import should_autotitle  # noqa: PLC0415

        text = (source or "").strip()
        if thread_id in self._title_inflight or not should_autotitle(
            text, self._plain_title(thread_id)
        ):
            return
        from happyclaw.infra.db.repos.threads import clip_thread_title  # noqa: PLC0415

        # The list is read as soon as the turn ends. Keep the question visible
        # while the model title is still running, and let that task replace it.
        fallback = clip_thread_title(text)
        if fallback:
            self._thread_registry.set_title_if_null(thread_id, fallback)
        self._title_inflight.add(thread_id)

        async def _run() -> None:
            try:
                await self._generate_thread_title(thread_id, text, user_id=user_id)
            finally:
                self._title_inflight.discard(thread_id)

        try:
            asyncio.get_running_loop().create_task(_run())
        except RuntimeError:
            self._title_inflight.discard(thread_id)

    async def _generate_thread_title(self, thread_id: str, source: str, *, user_id: int) -> None:
        from happyclaw.infra.db.repos.threads import clip_thread_title  # noqa: PLC0415
        from happyclaw.infra.gateway.process.thread_title import (  # noqa: PLC0415
            clean_generated_title,
            clip_title_source,
        )
        from happyclaw.infra.text_assist import run_text_assist  # noqa: PLC0415

        fallback = clip_thread_title(source)
        current = self._plain_title(thread_id)
        if current and current != fallback:
            return
        title = source
        try:
            locale = resolve_user_locale(user_repo=self._user_repo, user_id=user_id)
            generated = await run_text_assist(
                models=self._agent_manager.host_models,
                kind="chat.thread_title",
                text=clip_title_source(source),
                locale=locale,
            )
            cleaned = clean_generated_title(generated)
            if cleaned:
                title = cleaned
        except Exception:
            logger.warning("thread title generation failed thread=%s", thread_id, exc_info=True)
            title = source
        final = clip_thread_title(title) or fallback
        if not final:
            return
        latest = self._plain_title(thread_id)
        if latest and latest != fallback:
            return
        if latest != final:
            if latest:
                self._thread_registry.update_title(thread_id, final)
            else:
                self._thread_registry.set_title_if_null(thread_id, final)
        stored = self._plain_title(thread_id)
        if isinstance(stored, str) and stored.strip() and stored != "set":
            await self._push_thread_title(thread_id, stored)

    def _thread_agent_id(self, thread_id: str) -> str:
        try:
            row = self._thread_registry.get_thread(thread_id)
        except Exception:
            return ""
        agent_id = getattr(row, "agent_id", None)
        return agent_id.strip() if isinstance(agent_id, str) else ""

    async def _push_thread_title(self, thread_id: str, title: str) -> None:
        hub = getattr(self._gateway, "ws_hub", None) if self._gateway is not None else None
        push = getattr(hub, "push_to_thread", None)
        if not callable(push):
            return
        frame: dict[str, Any] = {"type": "thread_title", "thread_id": thread_id, "title": title}
        agent_id = self._thread_agent_id(thread_id)
        if agent_id:
            frame["agent_id"] = agent_id
        try:
            await push(thread_id, frame)
        except Exception:
            logger.debug("thread title push failed thread=%s", thread_id, exc_info=True)

    def _record_turn_usage(
        self,
        *,
        agent_id: str,
        user_id: int,
        thread_id: str,
        usage: dict[str, Any] | None,
    ) -> None:
        if self._usage_repo is None or not usage:
            return
        record_turn_usage(
            self._usage_repo,
            agent_id=agent_id,
            user_id=user_id,
            thread_id=thread_id,
            usage=usage,
        )

    async def _persist_incomplete_turn(
        self,
        thread_id: str,
        tracker: TurnHistoryTracker,
        *,
        title_source: str | None,
    ) -> None:
        """Keep partial tokens (and any error) when a turn is stopped or fails."""
        self._touch_thread_after_turn(thread_id, title_source)
        await self._record_turn_history(thread_id, tracker)

    async def _record_turn_history(self, thread_id: str, tracker: TurnHistoryTracker) -> None:
        if self._thread_message_repo is None:
            return
        items = tuple(tracker.inputs)
        try:
            self._thread_message_repo.append_if_ready(thread_id, items)
        except Exception:
            # History projection is a read optimization and must never turn a
            # successful model response into a failed chat turn.
            logger.warning(
                "failed to append thread history projection for thread=%s",
                thread_id,
                exc_info=True,
            )
        self._write_shadow_history(thread_id, items)

    async def _append_slash_checkpoint(
        self,
        *,
        agent_id: str,
        thread_id: str,
        command: str,
        response_lines: list[str],
        user_id: int = 0,
    ) -> None:
        """Save slash history, honoring the command's checkpoint persistence policy."""
        from happyclaw.infra.gateway.process.message_keys import AUTHOR_USER_ID_KEY  # noqa: PLC0415

        turn_id = new_ulid()
        response = "\n".join(response_lines).strip()
        kwargs = {AUTHOR_USER_ID_KEY: user_id} if user_id > 0 else {}
        canonical: list[HumanMessage | AIMessage] = [
            HumanMessage(
                content=command,
                id=f"slash:{turn_id}:human",
                additional_kwargs=kwargs,
            ),
        ]
        if response:
            canonical.append(AIMessage(content=response, id=f"slash:{turn_id}:assistant"))
        parsed = parse_slash(command)
        spec = spec_for(parsed.name) if parsed is not None else None
        if spec is not None and not spec.persist_checkpoint:
            appended: list[BaseMessage] = list(canonical)
        else:
            try:
                harness = self._agent_manager.get_agent(agent_id)
                appended = await harness.aappend_messages(thread_id, canonical)
            except Exception:
                logger.warning(
                    "failed to append slash checkpoint for thread=%s",
                    thread_id,
                    exc_info=True,
                )
                return
        if self._thread_message_repo is None:
            return
        items = tuple(message_inputs(appended, dedupe_missing_ids=True))
        try:
            self._thread_message_repo.append_if_ready(thread_id, items)
        except Exception:
            logger.warning(
                "failed to append slash history projection for thread=%s",
                thread_id,
                exc_info=True,
            )
        self._write_shadow_history(thread_id, items)

    @staticmethod
    def _write_shadow_history(thread_id: str, items: Sequence[ThreadMessageInput]) -> None:
        """Mirror a turn into the DSH shadow log when the switch is on.

        Default-off: the switch is checked before the session module is
        imported, so a disabled stage performs no DSH import and no I/O. When
        on, :func:`write_shadow_turn` swallows every failure so a shadow
        problem can only produce a warning, never a failed chat turn.
        """
        from happyclaw.infra.dsh.switches import shadow_enabled  # noqa: PLC0415

        if not shadow_enabled():
            return
        from happyclaw.infra.dsh.session.shadow import write_shadow_turn  # noqa: PLC0415

        write_shadow_turn(thread_id, items)
