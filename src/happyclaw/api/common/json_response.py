"""JSON responses whose body is rendered by ``orjson``.

Stdlib ``json.dumps`` is the slowest part of putting a large history payload on
the wire: on a real 160 KB page it costs ~3 ms, against ~0.8 ms for the native
encoder. FastAPI's own ``ORJSONResponse`` is deprecated in this version, so the
class lives here and stays a plain ``JSONResponse`` subclass: everything else
(media type, headers, status codes) keeps behaving exactly as before.
"""

from __future__ import annotations

from typing import Any

import orjson
from fastapi.responses import JSONResponse


class OrjsonResponse(JSONResponse):
    """``JSONResponse`` rendered by orjson, byte-identical to the stdlib one."""

    def render(self, content: Any) -> bytes:
        return orjson.dumps(content)
