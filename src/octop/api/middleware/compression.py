"""HTTP compression for the dashboard bundle and JSON responses.

The dashboard ships multi-megabyte vendor chunks; without transport
compression the first paint downloads them in full. Starlette's
``GZipMiddleware`` already skips ``text/event-stream`` (SSE must not be
buffered), so the only extra rule here is to skip payloads that are already
compressed — gzipping a PNG or a woff2 burns CPU for no bytes saved.
"""

from __future__ import annotations

from typing import Any

from starlette.middleware.gzip import GZipMiddleware

# Formats whose bytes are already entropy-coded.
_ALREADY_COMPRESSED_SUFFIXES = (
    ".br",
    ".gif",
    ".gz",
    ".jpeg",
    ".jpg",
    ".m4a",
    ".mp3",
    ".mp4",
    ".onnx",
    ".png",
    ".tgz",
    ".webm",
    ".webp",
    ".woff",
    ".woff2",
    ".zip",
)

# One-off gzip of a chunk this size costs a few milliseconds; below the floor
# the framing overhead cancels the saving.
_MINIMUM_SIZE = 1024


class DashboardGZipMiddleware(GZipMiddleware):
    """``GZipMiddleware`` that leaves already-compressed files untouched."""

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] == "http":
            path = str(scope.get("path") or "").lower()
            if path.endswith(_ALREADY_COMPRESSED_SUFFIXES):
                await self.app(scope, receive, send)
                return
            # Byte ranges (video scrubbing, resumed downloads) address the
            # uncompressed file; re-encoding them would break the offsets.
            if _has_range_header(scope):
                await self.app(scope, receive, send)
                return
        await super().__call__(scope, receive, send)


def _has_range_header(scope: Any) -> bool:
    for key, _value in scope.get("headers", []):
        if key.lower() == b"range":
            return True
    return False


def install(app: Any) -> None:
    """Add the compression middleware as the outermost layer."""
    app.add_middleware(
        DashboardGZipMiddleware,
        minimum_size=_MINIMUM_SIZE,
        compresslevel=6,
    )
