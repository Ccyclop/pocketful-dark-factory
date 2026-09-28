"""JSON responses carrying `application/json; charset=utf-8` (§3.4)."""
from __future__ import annotations

from starlette.responses import JSONResponse


class JsonResponse(JSONResponse):
    media_type = "application/json; charset=utf-8"
