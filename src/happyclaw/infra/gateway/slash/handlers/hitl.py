"""HITL slash command stubs (IM approval is handled in GlobalProcessor)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from happyclaw_harness.slash import SlashCommand, SlashSink

from happyclaw.i18n.domains.slash import tr
from happyclaw.infra.gateway.slash.ctx import SlashCtx, lang_of
from happyclaw.infra.gateway.slash.types import GatewayHandler

if TYPE_CHECKING:
    from happyclaw.infra.gateway.slash.dispatcher import SlashDispatcher


async def _dashboard_hint(
    d: SlashDispatcher, cmd: SlashCommand, ctx: SlashCtx, sink: SlashSink
) -> None:
    del d, cmd
    await sink.text(tr("hitl.dashboard_hint", lang_of(ctx)))


HITL_HANDLERS: dict[str, GatewayHandler] = {
    "approve": _dashboard_hint,
    "reject": _dashboard_hint,
    "pending": _dashboard_hint,
}
