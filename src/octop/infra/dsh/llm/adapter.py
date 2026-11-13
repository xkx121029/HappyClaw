"""Adapter seams: transport, canonical chunk stream, and the route factory.

An adapter owns exactly two translations: canonical request to provider wire
payload, and provider wire chunks to canonical stream chunks. Networking stays
behind ``Transport`` so tests never need a socket and deployments can plug in
their existing HTTP stack.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from typing import Any, Protocol, runtime_checkable

from octop.infra.dsh.llm.types import LlmRequest, StreamChunk

__all__ = [
    "ChunkStream",
    "ProviderAdapter",
    "RawChunkStream",
    "Transport",
    "adapter_for",
]


@runtime_checkable
class RawChunkStream(Protocol):
    """One provider response as decoded JSON objects."""

    def __aiter__(self) -> AsyncIterator[Mapping[str, Any]]: ...

    async def aclose(self) -> None: ...


@runtime_checkable
class ChunkStream(Protocol):
    """One canonical response stream."""

    def __aiter__(self) -> AsyncIterator[StreamChunk]: ...

    async def aclose(self) -> None: ...


@runtime_checkable
class Transport(Protocol):
    """Sends a wire payload and yields decoded frames, including SSE data lines."""

    def stream(self, request: Mapping[str, Any]) -> RawChunkStream: ...


@runtime_checkable
class ProviderAdapter(Protocol):
    """Provider-specific translation bound to one route."""

    name: str

    def start(self, request: LlmRequest) -> ChunkStream: ...


def adapter_for(kind: str, transport: Transport) -> ProviderAdapter:
    """Build the adapter for an Octop provider kind.

    Unknown kinds fall back to the OpenAI-compatible protocol, which is what
    Octop's ``KIND_TO_PROTOCOL`` map does for self-hosted gateways.
    """
    normalized = str(kind or "").strip().lower()
    if normalized in {"anthropic", "claude"}:
        from octop.infra.dsh.llm.anthropic import AnthropicAdapter

        return AnthropicAdapter(transport)
    from octop.infra.dsh.llm.openai_compat import OpenAICompatibleAdapter

    return OpenAICompatibleAdapter(transport, name=normalized or "openai")
