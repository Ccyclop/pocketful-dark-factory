"""POST /requests and GET /requests (§8)."""
from __future__ import annotations

import sqlite3
from typing import Any

from fastapi import APIRouter, Depends, Request

from .. import fields, idempotency, money_requests, payments
from ..auth import current_user
from ..errors import ApiError
from ..jsonbody import invalid, json_object
from ..paging import Page, page
from ..responses import JsonResponse

router = APIRouter()

DIRECTIONS = {"incoming": "r.payer_id = ?", "outgoing": "r.requester_id = ?"}


@router.post("/requests", status_code=201)
def create_request(request: Request,
                   user: sqlite3.Row = Depends(current_user),
                   key: str = Depends(idempotency.idempotency_key),
                   body: dict[str, Any] = Depends(json_object)) -> JsonResponse:
    """An idempotent write path. The caller is the requester."""
    def operation(conn: sqlite3.Connection) -> dict[str, Any]:
        fields.check_string_types(body, ("payer_handle",))
        payer_handle = fields.required(body, "payer_handle")
        amount = fields.amount(body)
        note = fields.note(body)
        payer = payments.user_by_handle(conn, payer_handle)
        if payer["id"] == user["id"]:
            raise ApiError(422, "self_request", "cannot request money from yourself")
        request_id = money_requests.create(conn, requester_id=user["id"],
                                           payer_id=payer["id"], amount=amount, note=note)
        return money_requests.load(conn, request_id)

    return idempotency.run(request, user, key, body, operation)


@router.get("/requests")
def list_requests(request: Request, user: sqlite3.Row = Depends(current_user),
                  paging: Page = Depends(page)) -> JsonResponse:
    """Requests where the caller is the requester or the payer, and no others.
    Newest first; ties by creation order, later first (D10)."""
    direction = request.query_params.get("direction")
    status = request.query_params.get("status")
    if direction is not None and direction not in DIRECTIONS:
        raise invalid("`direction` must be incoming or outgoing")
    if status is not None and status not in money_requests.STATUSES:
        raise invalid("`status` must be pending, paid, declined or cancelled")

    where = [DIRECTIONS[direction]] if direction else ["(r.payer_id = ? OR r.requester_id = ?)"]
    args: list[Any] = [user["id"]] if direction else [user["id"], user["id"]]
    if status:
        where.append("r.status = ?")
        args.append(status)
    with request.app.state.db.snapshot() as conn:
        rows = conn.execute(
            money_requests.REQUEST_SELECT + " WHERE " + " AND ".join(where) +
            " ORDER BY r.created_ts DESC, r.seq DESC LIMIT ? OFFSET ?",
            (*args, paging.limit + 1, paging.offset)).fetchall()
        currency = payments.currency(conn) if rows else None
    return JsonResponse({
        "requests": [money_requests.request_body(row, currency) for row in rows[:paging.limit]],
        "has_more": len(rows) > paging.limit,
    })
