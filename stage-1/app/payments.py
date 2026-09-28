"""Payments: moving money between wallets, and the payment response body (§8).

`transfer()` is the only code that changes balances for a single payment. Call it inside
a write transaction; the debit, the credit and the payment row commit together or not
at all (S1-PAY-10).
"""
from __future__ import annotations

import sqlite3
from typing import Any

from . import timeutil
from .errors import ApiError
from .ids import new_id


def currency(conn: sqlite3.Connection) -> str:
    return conn.execute("SELECT currency FROM service WHERE id = 1").fetchone()["currency"]


def user_by_handle(conn: sqlite3.Connection, handle: str) -> sqlite3.Row:
    """Exact, case-sensitive match (D6); no such user is 404 `not_found`."""
    row = conn.execute("SELECT id, handle FROM users WHERE handle = ?", (handle,)).fetchone()
    if row is None:
        raise ApiError(404, "not_found", f"no user has the handle {handle!r}")
    return row


def insufficient_funds() -> ApiError:
    return ApiError(409, "insufficient_funds", "balance is below the amount")


def transfer(conn: sqlite3.Connection, *, from_user_id: str, to_user_id: str, amount: int,
             note: str, visibility: str, request_id: str | None = None,
             settlement_id: str | None = None,
             created: tuple[str, float] | None = None) -> str:
    """Debit, credit and record one payment; returns the payment id.

    The debit is guarded in the UPDATE itself, so no balance ever goes negative.
    """
    debited = conn.execute(
        "UPDATE users SET balance = balance - ? WHERE id = ? AND balance >= ?",
        (amount, from_user_id, amount)).rowcount
    if debited != 1:
        raise insufficient_funds()
    conn.execute("UPDATE users SET balance = balance + ? WHERE id = ?", (amount, to_user_id))
    payment_id = new_id("p")
    created_at, created_ts = created or timeutil.now()
    conn.execute(
        "INSERT INTO payments (id, from_user_id, to_user_id, amount, note, visibility,"
        " request_id, settlement_id, created_at, created_ts)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (payment_id, from_user_id, to_user_id, amount, note, visibility, request_id,
         settlement_id, created_at, created_ts))
    return payment_id


PAYMENT_SELECT = (
    "SELECT p.id, p.from_user_id, f.handle AS from_handle, p.to_user_id,"
    " t.handle AS to_handle, p.amount, p.note, p.visibility, p.request_id,"
    " p.settlement_id, p.created_at"
    " FROM payments p JOIN users f ON f.id = p.from_user_id JOIN users t ON t.id = p.to_user_id")


def payment_body(row: sqlite3.Row, currency_code: str) -> dict[str, Any]:
    """The payment as the API returns it (S1-PAY-3, D18)."""
    return {
        "payment_id": row["id"],
        "from_user_id": row["from_user_id"],
        "from_handle": row["from_handle"],
        "to_user_id": row["to_user_id"],
        "to_handle": row["to_handle"],
        "amount": row["amount"],
        "currency": currency_code,
        "note": row["note"],
        "visibility": row["visibility"],
        "request_id": row["request_id"],
        "settlement_id": row["settlement_id"],
        "created_at": row["created_at"],
    }


def load_payment(conn: sqlite3.Connection, payment_id: str) -> dict[str, Any]:
    row = conn.execute(PAYMENT_SELECT + " WHERE p.id = ?", (payment_id,)).fetchone()
    return payment_body(row, currency(conn))
