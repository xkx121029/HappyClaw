"""Slash command parsing and dispatch."""

from happyclaw_harness.slash import BufferSink, SlashCommand, SlashSink

from happyclaw.infra.gateway.slash.ctx import SlashCtx, build_slash_ctx
from happyclaw.infra.gateway.slash.dispatcher import SlashDispatcher, build_default_dispatcher
from happyclaw.infra.gateway.slash.parser import parse_slash

__all__ = [
    "BufferSink",
    "SlashCommand",
    "SlashCtx",
    "SlashDispatcher",
    "SlashSink",
    "build_default_dispatcher",
    "build_slash_ctx",
    "parse_slash",
]
