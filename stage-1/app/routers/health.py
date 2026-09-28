"""GET /health (§3.2)."""
from __future__ import annotations

from fastapi import APIRouter, Request

from ..errors import ApiError
from ..responses import JsonResponse

router = APIRouter()


@router.get("/health")
def health(request: Request) -> JsonResponse:
    if not request.app.state.db.ping():
        raise ApiError(503, "unavailable", "data store is not ready")
    return JsonResponse({"status": "ok"})
