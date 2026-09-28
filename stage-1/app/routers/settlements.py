"""POST /settlements (§11). Operators only; the fifth idempotent write path (§7)."""
from __future__ import annotations

import sqlite3
from typing import Any

from fastapi import APIRouter, Depends, Request

from .. import idempotency, settlements
from ..auth import current_user
from ..errors import ApiError
from ..jsonbody import json_object
from ..responses import JsonResponse

router = APIRouter()


def current_operator(user: sqlite3.Row = Depends(current_user)) -> sqlite3.Row:
    """401 without a valid token, then 403 for a non-operator, before the key (D17)."""
    if not user["is_operator"]:
        raise ApiError(403, "forbidden", "only a settlement operator may settle")
    return user


@router.post("/settlements", status_code=201)
def create_settlement(request: Request,
                      operator: sqlite3.Row = Depends(current_operator),
                      key: str = Depends(idempotency.idempotency_key),
                      body: dict[str, Any] = Depends(json_object)) -> JsonResponse:
    def operation(conn: sqlite3.Connection) -> dict[str, Any]:
        # A reset may have changed the operator list since authentication.
        if not conn.execute("SELECT is_operator FROM users WHERE id = ?",
                            (operator["id"],)).fetchone()["is_operator"]:
            raise ApiError(403, "forbidden", "only a settlement operator may settle")
        transfers = settlements.validate(conn, body)
        return settlements.commit(conn, operator["id"], transfers)

    return idempotency.run(request, operator, key, body, operation)
