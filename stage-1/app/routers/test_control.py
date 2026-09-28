"""Unauthenticated test control endpoints: POST /_test/reset (§3.3),
GET /_test/export and POST /_test/import (§10)."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request, Response

from .. import fixture as fixture_mod
from .. import snapshot
from ..jsonbody import json_object
from ..responses import JsonResponse

router = APIRouter()


@router.post("/_test/reset", status_code=204)
def reset(request: Request, body: dict[str, Any] = Depends(json_object)) -> Response:
    fixture = fixture_mod.validate(body)
    # Hashing is the slow part; do it before taking the write lock.
    password_hashes = fixture_mod.hash_credentials(fixture)
    with request.app.state.db.transaction() as conn:
        fixture_mod.load(conn, fixture, password_hashes)
    return Response(status_code=204)


@router.get("/_test/export")
def export(request: Request) -> JsonResponse:
    """An atomic, read-only snapshot of the whole state."""
    with request.app.state.db.snapshot() as conn:
        return JsonResponse(snapshot.export_document(conn))


@router.post("/_test/import", status_code=204)
def import_(request: Request, body: dict[str, Any] = Depends(json_object)) -> Response:
    """Atomically replace the whole state with an export; 422 leaves it unchanged."""
    with request.app.state.db.transaction() as conn:
        loaded = snapshot.validate_document(conn, body)
        snapshot.import_rows(conn, loaded)
    return Response(status_code=204)
