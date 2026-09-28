"""POST /payments (§8). An idempotent write path (§7)."""
from __future__ import annotations

import sqlite3
from typing import Any

from fastapi import APIRouter, Depends, Request

from .. import fields, idempotency, payments
from ..auth import current_user
from ..errors import ApiError
from ..jsonbody import json_object
from ..responses import JsonResponse

router = APIRouter()


@router.post("/payments", status_code=201)
def create_payment(request: Request,
                   user: sqlite3.Row = Depends(current_user),
                   key: str = Depends(idempotency.idempotency_key),
                   body: dict[str, Any] = Depends(json_object)) -> JsonResponse:
    def operation(conn: sqlite3.Connection) -> dict[str, Any]:
        # Field rules in the order D1 gives: types, then values, then resources.
        fields.check_string_types(body, ("to_handle",))
        to_handle = fields.required(body, "to_handle")
        amount = fields.amount(body)
        note = fields.note(body)
        visibility = fields.visibility(body)
        receiver = payments.user_by_handle(conn, to_handle)
        if receiver["id"] == user["id"]:
            raise ApiError(422, "self_payment", "cannot pay yourself")
        payment_id = payments.transfer(conn, from_user_id=user["id"],
                                       to_user_id=receiver["id"], amount=amount,
                                       note=note, visibility=visibility)
        return payments.load_payment(conn, payment_id)

    return idempotency.run(request, user, key, body, operation)
