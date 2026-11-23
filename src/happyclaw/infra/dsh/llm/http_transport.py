"""httpx-backed streaming transports for the DSH LLM seam.

One instance is bound to one provider route; :func:`build_http_transport` is
the factory handed to :func:`happyclaw.infra.dsh.llm.factory.install_dsh_model_factory`.
Two wire protocols are implemented:

* ``openai``    -> ``POST {base}/chat/completions`` (SSE ``data:`` frames)
* ``anthropic`` -> ``POST {base}/v1/messages``     (SSE ``data:`` frames)

Deliberate boundaries:

* **No retries here.** ``httpx`` is built without transport-level retries and
  this module never loops. Transient failures are raised as ``ProviderFailure``
  and replayed only by :class:`~happyclaw.infra.dsh.llm.runtime.LlmRuntime` at the
  assistant-step boundary, so a request is never duplicated by two layers.
* **Explicit timeouts.** Connect and read timeouts are always supplied; the
  read timeout is a stall timeout between stream frames, not a total budget.
* **Deterministic teardown.** Each request owns its ``AsyncClient`` for the
  lifetime of the stream. Closing the stream (normal end, provider error,
  cancellation, or caller ``aclose()``) closes the response and the socket.
* **Loopback bypasses proxies.** Requests to ``127.0.0.1`` / ``localhost`` /
  ``::1`` use ``trust_env=False`` so a machine-wide ``HTTP_PROXY`` can never
  intercept a local model server. Non-loopback routes keep ``trust_env=True``
  and rely on the existing ``NO_PROXY`` handling in
  :mod:`happyclaw.infra.utils.proxy_env`.
"""

from __future__ import annotations

import ipaddress
import json
from collections.abc import AsyncGenerator, AsyncIterator, Mapping
from typing import Any

import httpx

from happyclaw.infra.dsh.llm.errors import FailureCode, ProviderFailure, TransportError

__all__ = [
    "DEFAULT_CONNECT_TIMEOUT_S",
    "DEFAULT_READ_TIMEOUT_S",
    "HttpStreamTransport",
    "build_http_transport",
    "is_loopback_url",
]

DEFAULT_CONNECT_TIMEOUT_S = 10.0
DEFAULT_READ_TIMEOUT_S = 180.0

_ANTHROPIC_VERSION = "2023-06-01"


def is_loopback_url(url: str) -> bool:
    """Return whether *url* points at the local machine."""
    try:
        host = httpx.URL(url).host or ""
    except (TypeError, ValueError):
        return False
    if host in {"localhost", "::1"} or host.startswith("127."):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _endpoint(protocol: str, base_url: str) -> str:
    base = base_url.strip().rstrip("/")
    if protocol == "anthropic":
        if base.endswith("/messages"):
            return base
        if base.endswith("/v1"):
            return f"{base}/messages"
        return f"{base}/v1/messages"
    if base.endswith("/chat/completions"):
        return base
    return f"{base}/chat/completions"


def _headers(protocol: str, api_key: str, extra: Mapping[str, str]) -> dict[str, str]:
    if protocol == "anthropic":
        headers = {
            "x-api-key": api_key,
            "anthropic-version": _ANTHROPIC_VERSION,
            "content-type": "application/json",
            "accept": "text/event-stream",
        }
    else:
        headers = {
            "authorization": f"Bearer {api_key}",
            "content-type": "application/json",
            "accept": "text/event-stream",
        }
    headers.update({str(key): str(value) for key, value in extra.items()})
    return headers


def _retry_after(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return max(float(value), 0.0)
    except ValueError:
        return None


class HttpStreamTransport:
    """One provider route over ``httpx``; ``stream()`` performs no I/O yet."""

    def __init__(
        self,
        *,
        protocol: str,
        base_url: str,
        api_key: str,
        extra_headers: Mapping[str, str] | None = None,
        connect_timeout_s: float = DEFAULT_CONNECT_TIMEOUT_S,
        read_timeout_s: float = DEFAULT_READ_TIMEOUT_S,
    ) -> None:
        normalized = protocol.strip().lower()
        if normalized not in {"openai", "anthropic"}:
            raise ValueError(f"unsupported transport protocol: {protocol!r}")
        if not base_url.strip():
            raise ValueError("base_url is required")
        self._protocol = normalized
        self._url = _endpoint(normalized, base_url)
        self._headers = _headers(normalized, api_key, extra_headers or {})
        self._timeout = httpx.Timeout(
            connect=connect_timeout_s,
            read=read_timeout_s,
            write=connect_timeout_s,
            pool=connect_timeout_s,
        )
        self._trust_env = not is_loopback_url(base_url)

    def stream(self, request: Mapping[str, Any]) -> _HttpStream:
        return _HttpStream(
            url=self._url,
            headers=self._headers,
            payload=dict(request),
            timeout=self._timeout,
            trust_env=self._trust_env,
            protocol=self._protocol,
        )


class _HttpStream:
    """One SSE response; closes its client on every exit path."""

    def __init__(
        self,
        *,
        url: str,
        headers: Mapping[str, str],
        payload: Mapping[str, Any],
        timeout: httpx.Timeout,
        trust_env: bool,
        protocol: str,
    ) -> None:
        self._url = url
        self._headers = dict(headers)
        self._payload = dict(payload)
        self._timeout = timeout
        self._trust_env = trust_env
        self._protocol = protocol
        self._generator: AsyncGenerator[Mapping[str, Any], None] = self._run()
        self._closed = False

    @property
    def closed(self) -> bool:
        return self._closed

    def __aiter__(self) -> AsyncIterator[Mapping[str, Any]]:
        return self

    async def __anext__(self) -> Mapping[str, Any]:
        return await self._generator.__anext__()

    async def aclose(self) -> None:
        if self._closed:
            return
        self._closed = True
        await self._generator.aclose()

    async def _run(self) -> AsyncGenerator[Mapping[str, Any], None]:
        try:
            # Loopback gets an explicit transport with retries=0 and
            # trust_env=False, so a machine-wide proxy cannot intercept it.
            # Remote routes keep httpx's default environment handling (also
            # retries=0); replay belongs to LlmRuntime only.
            transport = (
                None if self._trust_env else httpx.AsyncHTTPTransport(retries=0)
            )
            client = httpx.AsyncClient(
                timeout=self._timeout,
                transport=transport,
                trust_env=self._trust_env,
                follow_redirects=False,
            )
            async with client:
                async with client.stream(
                    "POST", self._url, json=self._payload, headers=self._headers
                ) as response:
                    if response.status_code >= 400:
                        body = (await response.aread()).decode("utf-8", "replace")
                        raise TransportError(
                            f"{self._protocol} request failed with HTTP {response.status_code}",
                            status=response.status_code,
                            retry_after_s=_retry_after(response.headers.get("retry-after")),
                            request_id=response.headers.get("x-request-id"),
                            body=body,
                        )
                    async for frame in _iter_sse(response):
                        yield frame
        except httpx.TimeoutException as exc:
            phase = (
                "connect"
                if isinstance(exc, httpx.ConnectTimeout)
                else "read"
                if isinstance(exc, httpx.ReadTimeout)
                else "write"
                if isinstance(exc, httpx.WriteTimeout)
                else "pool"
            )
            raise ProviderFailure(
                FailureCode.TIMEOUT,
                f"{self._protocol} {phase} timeout: {exc}",
                details={"phase": phase},
            ) from exc
        except httpx.HTTPError as exc:
            raise ProviderFailure(
                FailureCode.TRANSPORT,
                f"{self._protocol} transport error: {exc}",
                details={"error_type": type(exc).__name__},
            ) from exc
        finally:
            self._closed = True


async def _iter_sse(response: httpx.Response) -> AsyncIterator[Mapping[str, Any]]:
    """Decode ``data:`` frames; ``event:`` lines are labels the adapters ignore."""
    async for line in response.aiter_lines():
        text = line.strip()
        if not text or text.startswith(":"):
            continue
        if not text.startswith("data:"):
            continue
        data = text[5:].strip()
        if not data:
            continue
        if data == "[DONE]":
            return
        try:
            decoded = json.loads(data)
        except json.JSONDecodeError as exc:
            raise ProviderFailure(
                FailureCode.TRANSPORT,
                f"invalid SSE data frame: {exc}",
            ) from exc
        if not isinstance(decoded, Mapping):
            raise ProviderFailure(
                FailureCode.TRANSPORT,
                f"SSE frame is {type(decoded).__name__}, expected an object",
            )
        yield decoded


def build_http_transport(provider: Any, model: Any) -> HttpStreamTransport | None:
    """Build a transport for one ``provider/model`` pair.

    Returns ``None`` for protocols without a transport (e.g. ``bedrock``), so
    that ref falls back to the harness factory without affecting siblings.
    """
    protocol = str(getattr(provider, "protocol", "") or "openai").strip().lower()
    if protocol not in {"openai", "anthropic"}:
        return None
    base_url = str(getattr(provider, "base_url", "") or "").strip()
    if not base_url:
        return None
    return HttpStreamTransport(
        protocol=protocol,
        base_url=base_url,
        api_key=str(getattr(provider, "api_key", "") or ""),
        extra_headers=dict(getattr(provider, "headers", {}) or {}),
    )
