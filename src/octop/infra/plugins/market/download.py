"""HTTP reads for market indexes and plugin archives.

Sources take a ``Transport`` so tests can run entirely offline; the default
transport is a bounded ``urllib`` read.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from octop.infra.plugins.market.errors import MarketError, SourceUnreachableError

Transport = Callable[[str], bytes]

FETCH_TIMEOUT_SECONDS = 15.0
READ_CHUNK = 64 * 1024
MAX_INDEX_BYTES = 128 * 1024 * 1024
MAX_ARCHIVE_BYTES = 100 * 1024 * 1024


def require_http_url(url: str, *, path: str = "") -> None:
    parsed = urlparse(url.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise MarketError(f"invalid http url at {path}: {url!r}" if path else f"invalid http url: {url!r}")


def fetch_bytes(url: str, *, limit: int = MAX_ARCHIVE_BYTES) -> bytes:
    """Read ``url`` with a size ceiling. Redirects are followed by ``urllib``."""
    request = Request(url, headers={"Accept": "application/json, application/octet-stream"})
    try:
        with urlopen(request, timeout=FETCH_TIMEOUT_SECONDS) as response:  # noqa: S310
            status = int(getattr(response, "status", 200))
            if status >= 400:
                raise SourceUnreachableError(f"http {status} for {url}", url=url)
            chunks: list[bytes] = []
            total = 0
            while True:
                chunk = response.read(READ_CHUNK)
                if not chunk:
                    break
                total += len(chunk)
                if total > limit:
                    raise SourceUnreachableError(f"response too large: {url}", url=url)
                chunks.append(chunk)
            return b"".join(chunks)
    except HTTPError as exc:
        raise SourceUnreachableError(f"http {exc.code} for {url}", url=url) from exc
    except URLError as exc:
        reason = exc.reason if isinstance(exc.reason, BaseException) else exc
        raise SourceUnreachableError(f"unreachable {url}: {reason}", url=url) from exc
    except TimeoutError as exc:
        raise SourceUnreachableError(f"timeout reading {url}", url=url) from exc
    except OSError as exc:
        raise SourceUnreachableError(f"read failed {url}: {exc}", url=url) from exc


def decode_json(body: bytes, *, label: str) -> Any:
    try:
        return json.loads(body.decode("utf-8-sig"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise MarketError(f"invalid json: {label}") from exc
