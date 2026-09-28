"""GET /activity (§4 feed contract, §8)."""
from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, Request

from .. import payments
from ..auth import current_user
from ..paging import Page, page
from ..responses import JsonResponse

router = APIRouter()


@router.get("/activity")
def activity(request: Request, user: sqlite3.Row = Depends(current_user),
             paging: Page = Depends(page)) -> JsonResponse:
    """Payments that are public or that the caller sent or received, and nothing else
    (S1-FEED-1). Newest first; ties by creation order, later first (D10)."""
    with request.app.state.db.snapshot() as conn:
        rows = conn.execute(
            payments.PAYMENT_SELECT +
            " WHERE p.visibility = 'public' OR p.from_user_id = ? OR p.to_user_id = ?"
            " ORDER BY p.created_ts DESC, p.seq DESC LIMIT ? OFFSET ?",
            (user["id"], user["id"], paging.limit + 1, paging.offset)).fetchall()
        currency = payments.currency(conn) if rows else None
    return JsonResponse({
        "payments": [payments.payment_body(row, currency) for row in rows[:paging.limit]],
        "has_more": len(rows) > paging.limit,
    })
