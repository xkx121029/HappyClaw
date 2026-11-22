"""CLI in-process chat transport: connection hub + virtual IM channel."""

from happyclaw.infra.gateway.cli.cli_channel import CLI_CHANNEL_ID, CLI_CONNECTION_META, CliChannel
from happyclaw.infra.gateway.ws.ws_hub import WebSocketHub as CliHub

__all__ = [
    "CLI_CHANNEL_ID",
    "CLI_CONNECTION_META",
    "CliChannel",
    "CliHub",
]
