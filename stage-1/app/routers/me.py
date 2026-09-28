"""GET /me (§8)."""
from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, Request

from ..auth import current_user, unauthenticated
from ..responses import JsonResponse

router = APIRouter()


@router.get("/me")
def me(request: Request, user: sqlite3.Row = Depends(current_user)) -> JsonResponse:
    # One statement, so the user and the currency come from the same state even if a
    # reset commits between authentication and this read.
    row = request.app.state.db.connection().execute(
        "SELECT users.id, users.display_name, users.handle, users.balance,"
        " service.currency, service.minor_units"
        " FROM users JOIN service ON service.id = 1 WHERE users.id = ?",
        (user["id"],)).fetchone()
    if row is None:
        raise unauthenticated()
    return JsonResponse({
        "user_id": row["id"],
        "display_name": row["display_name"],
        "handle": row["handle"],
        "balance": row["balance"],
        "currency": row["currency"],
        "minor_units": row["minor_units"],
    })
