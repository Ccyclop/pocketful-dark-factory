"""POST /splits (§8). An idempotent write path (§7)."""
from __future__ import annotations

import sqlite3
from typing import Any

from fastapi import APIRouter, Depends, Request

from .. import fields, idempotency, money_requests, payments, splits, timeutil
from ..auth import current_user
from ..jsonbody import invalid, json_object, malformed
from ..responses import JsonResponse

router = APIRouter()


def _participants(body: dict[str, Any]) -> list[str]:
    """`participant_handles`: an array of strings (else 400, D5), present (else 422)."""
    value = body.get("participant_handles")
    if "participant_handles" in body and (
            not isinstance(value, list) or not all(isinstance(h, str) for h in value)):
        raise malformed("`participant_handles` must be an array of strings")
    return value


@router.post("/splits", status_code=201)
def create_split(request: Request,
                 user: sqlite3.Row = Depends(current_user),
                 key: str = Depends(idempotency.idempotency_key),
                 body: dict[str, Any] = Depends(json_object)) -> JsonResponse:
    """Split an amount the caller already paid: one share per participant, and one
    pending request, with the caller as requester, per participant except the caller.
    No balance is checked (S1-SPL-6)."""
    def operation(conn: sqlite3.Connection) -> dict[str, Any]:
        handles = _participants(body)
        amount = fields.amount(body)
        if handles is None:
            raise invalid("`participant_handles` is required")
        if not handles:
            raise invalid("`participant_handles` must not be empty")
        if len(set(handles)) != len(handles):
            raise invalid("`participant_handles` must not contain duplicates")
        note = fields.note(body)
        # The first unknown handle, in the order given, decides the 404.
        participants = [payments.user_by_handle(conn, h) for h in handles]

        created_at, created_ts = timeutil.now()
        split_id = splits.record(conn, requester_id=user["id"], amount=amount, note=note,
                                 created_at=created_at, created_ts=created_ts)
        shares = splits.equal_split(amount, len(participants))
        request_ids = [
            money_requests.create(conn, requester_id=user["id"], payer_id=p["id"],
                                  amount=share, note=note, created=(created_at, created_ts))
            for p, share in zip(participants, shares) if p["id"] != user["id"]]
        return {
            "split_id": split_id,
            "amount": amount,
            "currency": payments.currency(conn),
            "note": note,
            "shares": [{"handle": p["handle"], "amount": share}
                       for p, share in zip(participants, shares)],
            "requests": [money_requests.load(conn, rid) for rid in request_ids],
            "created_at": created_at,
        }

    return idempotency.run(request, user, key, body, operation)
