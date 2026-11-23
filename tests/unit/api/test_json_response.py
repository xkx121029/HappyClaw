"""The history endpoint renders its body with orjson, byte for byte.

A faster renderer is only safe if the bytes on the wire do not change, so the
same payload goes through both renderers and the outputs are compared.
"""

from __future__ import annotations

from fastapi.responses import JSONResponse

from happyclaw.api.common.json_response import OrjsonResponse
from happyclaw.api.routers.chat import history as history_mod

# Shapes the history payload really contains: unicode text, floats, nulls,
# nested lists of tool blocks, and keys that keep their insertion order.
PAYLOAD = {
    "thread_id": "thr_01M7AFGXYS9WW5HP93W35C4PNZ",
    "messages": [
        {
            "id": "m1",
            "role": "assistant",
            "content": [
                {"type": "text", "text": "热点在 `__call__` 的三个同步步骤。\n| 步骤 | 耗时 |"},
                {
                    "type": "tool_result",
                    "output": '{"path": "C:/Users/linch/桌面/shot.png", "ok": true}',
                },
            ],
            "created_at": 1763892000000,
            "tokens": 18746,
            "score": 0.123456789,
            "meta": None,
            "flags": [True, False],
        }
    ],
    "has_more": False,
    "limit": 25,
    "offset": 0,
    "next_cursor": None,
    "history_loading": False,
    "hitl_policy": {},
}


def test_render_is_byte_identical_to_stdlib() -> None:
    assert OrjsonResponse(PAYLOAD).body == JSONResponse(PAYLOAD).body


def test_render_keeps_unicode_raw() -> None:
    body = OrjsonResponse(PAYLOAD).body
    assert "热点" in body.decode("utf-8")
    assert b"\\u70ed" not in body


def test_history_route_renders_with_orjson() -> None:
    routes = [
        route
        for route in history_mod.router.routes
        if getattr(route, "path", "").endswith("/threads/{thread_id}/history")
    ]
    assert routes, "history route not registered"
    assert routes[0].response_class is OrjsonResponse
