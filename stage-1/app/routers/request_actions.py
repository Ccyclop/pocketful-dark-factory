"""POST /requests/{id}/pay, /decline and /cancel (§8).

Each action reads the request and changes it in one write transaction, so exactly one
terminal state wins and a request moves money at most once (S1-INV-3).
"""
from __future__ import annotations

import sqlite3
from typing import Any

from fastapi import APIRouter, Depends, Request

from .. import fields, idempotency, money_requests, payments
from ..auth import current_user
from ..errors import ApiError
from ..jsonbody import json_object_or_empty
from ..responses import JsonResponse

router = APIRouter()


def _existing(conn: sqlite3.Connection, request_id: str) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM requests WHERE id = ?", (request_id,)).fetchone()
    if row is None:
        raise ApiError(404, "not_found", "no such request")
    return row


def _forbidden(action: str, party: str) -> ApiError:
    return ApiError(403, "forbidden", f"only the {party} may {action} this request")


def _not_pending(status: str) -> ApiError:
    return ApiError(409, "request_not_pending", f"the request is {status}")


@router.post("/requests/{request_id}/pay", status_code=201)
def pay(request_id: str, request: Request,
        user: sqlite3.Row = Depends(current_user),
        key: str = Depends(idempotency.idempotency_key),
        body: dict[str, Any] = Depends(json_object_or_empty)) -> JsonResponse:
    """An idempotent write path. Only the payer may pay; returns the new payment."""
    def operation(conn: sqlite3.Connection) -> dict[str, Any]:
        visibility = fields.visibility(body)
        row = _existing(conn, request_id)
        if row["payer_id"] != user["id"]:
            raise _forbidden("pay", "payer")
        if row["status"] != "pending":
            raise _not_pending(row["status"])
        # D23: from the payer to the requester, carrying the request's note.
        payment_id = payments.transfer(conn, from_user_id=row["payer_id"],
                                       to_user_id=row["requester_id"], amount=row["amount"],
                                       note=row["note"], visibility=visibility,
                                       request_id=row["id"])
        conn.execute("UPDATE requests SET status = 'paid', payment_id = ? WHERE id = ?",
                     (payment_id, row["id"]))
        return payments.load_payment(conn, payment_id)

    return idempotency.run(request, user, key, body, operation)


def _close(request: Request, user: sqlite3.Row, request_id: str, *, party: str,
           action: str, final: str) -> JsonResponse:
    """Move a pending request to `final`. Repeating it is 200 with the current state;
    any other terminal state is 409. No idempotency key; the body is ignored (D14)."""
    with request.app.state.db.transaction() as conn:
        row = _existing(conn, request_id)
        if row[party + "_id"] != user["id"]:
            raise _forbidden(action, party)
        if row["status"] == "pending":
            conn.execute("UPDATE requests SET status = ? WHERE id = ?", (final, row["id"]))
        elif row["status"] != final:
            raise _not_pending(row["status"])
        return JsonResponse(money_requests.load(conn, row["id"]))


@router.post("/requests/{request_id}/decline")
def decline(request_id: str, request: Request,
            user: sqlite3.Row = Depends(current_user)) -> JsonResponse:
    return _close(request, user, request_id, party="payer", action="decline", final="declined")


@router.post("/requests/{request_id}/cancel")
def cancel(request_id: str, request: Request,
           user: sqlite3.Row = Depends(current_user)) -> JsonResponse:
    return _close(request, user, request_id, party="requester", action="cancel",
                  final="cancelled")
