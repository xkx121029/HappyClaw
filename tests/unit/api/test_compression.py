"""Transport compression for dashboard assets and JSON responses.

Pins the three rules that matter in production:

* large textual payloads are gzipped (the dashboard vendors megabytes of JS);
* SSE stays uncompressed and unbuffered — gzip would delay the first token;
* already-compressed binaries and byte ranges pass through untouched.
"""

from __future__ import annotations

import httpx
import pytest
from starlette.applications import Starlette
from starlette.responses import JSONResponse, PlainTextResponse, Response, StreamingResponse
from starlette.routing import Route

from octop.api.middleware.compression import install


async def _big_json(_request):
    return JSONResponse({"blob": "octop" * 4000})


async def _sse(_request):
    async def gen():
        for index in range(3):
            yield f"data: {index}\n\n".encode()

    return StreamingResponse(gen(), media_type="text/event-stream")


async def _png(_request):
    return Response(b"\x89PNG" + b"\x00" * 4000, media_type="image/png")


async def _small(_request):
    return PlainTextResponse("ok")


def _app() -> Starlette:
    app = Starlette(
        routes=[
            Route("/big", _big_json),
            Route("/stream/events", _sse),
            Route("/logo.png", _png),
            Route("/small", _small),
        ]
    )
    install(app)
    return app


@pytest.fixture
async def client():
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_app()), base_url="http://testserver"
    ) as c:
        yield c


async def test_large_json_is_gzipped(client) -> None:
    response = await client.get("/big", headers={"Accept-Encoding": "gzip"})

    assert response.status_code == 200
    assert response.headers["content-encoding"] == "gzip"
    assert "accept-encoding" in response.headers["vary"].lower()
    assert response.json()["blob"].startswith("octop")


async def test_sse_is_never_compressed(client) -> None:
    response = await client.get("/stream/events", headers={"Accept-Encoding": "gzip"})

    assert response.status_code == 200
    assert "content-encoding" not in response.headers
    assert response.headers["content-type"].startswith("text/event-stream")


async def test_already_compressed_media_passes_through(client) -> None:
    response = await client.get("/logo.png", headers={"Accept-Encoding": "gzip"})

    assert response.status_code == 200
    assert "content-encoding" not in response.headers


async def test_byte_ranges_are_not_reencoded(client) -> None:
    response = await client.get(
        "/big", headers={"Accept-Encoding": "gzip", "Range": "bytes=100-200"}
    )

    assert "content-encoding" not in response.headers


async def test_small_payloads_skip_compression(client) -> None:
    response = await client.get("/small", headers={"Accept-Encoding": "gzip"})

    assert response.status_code == 200
    assert "content-encoding" not in response.headers


async def test_client_without_gzip_gets_identity(client) -> None:
    response = await client.get("/big", headers={"Accept-Encoding": "identity"})

    assert response.status_code == 200
    assert "content-encoding" not in response.headers
