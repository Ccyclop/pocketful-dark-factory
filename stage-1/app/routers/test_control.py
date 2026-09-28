"""Unauthenticated test control endpoints: POST /_test/reset (§3.3)."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request, Response

from .. import fixture as fixture_mod
from ..jsonbody import json_object

router = APIRouter()


@router.post("/_test/reset", status_code=204)
def reset(request: Request, body: dict[str, Any] = Depends(json_object)) -> Response:
    fixture = fixture_mod.validate(body)
    # Hashing is the slow part; do it before taking the write lock.
    password_hashes = fixture_mod.hash_credentials(fixture)
    with request.app.state.db.transaction() as conn:
        fixture_mod.load(conn, fixture, password_hashes)
    return Response(status_code=204)
