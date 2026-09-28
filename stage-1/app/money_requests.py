"""Payment requests (§4, §8): creating them and the request response body.

Named `money_requests` to keep it apart from HTTP requests. A request is `pending`, then
exactly one of `paid`, `declined` or `cancelled`. Creating one never checks the payer's
balance (S1-REQ-4).
"""
from __future__ import annotations

import sqlite3
from typing import Any

from . import timeutil
from .ids import new_id
from .payments import currency

STATUSES = ("pending", "paid", "declined", "cancelled")

REQUEST_SELECT = (
    "SELECT r.id, r.requester_id, q.handle AS requester_handle, r.payer_id,"
    " p.handle AS payer_handle, r.amount, r.note, r.status, r.payment_id, r.created_at"
    " FROM requests r JOIN users q ON q.id = r.requester_id JOIN users p ON p.id = r.payer_id")


def request_body(row: sqlite3.Row, currency_code: str) -> dict[str, Any]:
    """The request as the API returns it (S1-REQ-2)."""
    return {
        "request_id": row["id"],
        "requester_id": row["requester_id"],
        "requester_handle": row["requester_handle"],
        "payer_id": row["payer_id"],
        "payer_handle": row["payer_handle"],
        "amount": row["amount"],
        "currency": currency_code,
        "note": row["note"],
        "status": row["status"],
        "payment_id": row["payment_id"],
        "created_at": row["created_at"],
    }


def create(conn: sqlite3.Connection, *, requester_id: str, payer_id: str, amount: int,
           note: str, created: tuple[str, float] | None = None) -> str:
    """Insert a pending request; returns its id. Call inside a write transaction."""
    request_id = new_id("rq")
    created_at, created_ts = created or timeutil.now()
    conn.execute(
        "INSERT INTO requests (id, requester_id, payer_id, amount, note, status, payment_id,"
        " created_at, created_ts) VALUES (?, ?, ?, ?, ?, 'pending', NULL, ?, ?)",
        (request_id, requester_id, payer_id, amount, note, created_at, created_ts))
    return request_id


def load(conn: sqlite3.Connection, request_id: str) -> dict[str, Any]:
    row = conn.execute(REQUEST_SELECT + " WHERE r.id = ?", (request_id,)).fetchone()
    return request_body(row, currency(conn))
