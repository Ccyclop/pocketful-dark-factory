"""Atomic net settlements (§11): validating a batch and committing it.

A batch is affordable when every wallet's balance after all its incoming and outgoing
transfers is nonnegative (S1-SET-4). Each wallet's balance moves once, by its net delta,
so no balance is ever negative, not even between two statements of the transaction.
"""
from __future__ import annotations

import sqlite3
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from . import fields, payments, timeutil
from .errors import ApiError
from .ids import new_id
from .jsonbody import invalid

MAX_TRANSFERS = 32


@dataclass(frozen=True)
class Transfer:
    from_user_id: str
    to_user_id: str
    amount: int
    note: str
    visibility: str


def _handle(entry: dict[str, Any], name: str, where: str) -> str:
    value = entry.get(name)
    if not isinstance(value, str):
        raise invalid(f"{where}: `{name}` must be a string")
    return value


def validate(conn: sqlite3.Connection, body: dict[str, Any]) -> list[Transfer]:
    """Batch shape first, then each entry in input order; the first failing entry
    decides the error (D17)."""
    entries = body.get("transfers")
    if not isinstance(entries, list) or not 1 <= len(entries) <= MAX_TRANSFERS:
        raise invalid(f"`transfers` must be an array of 1 to {MAX_TRANSFERS} objects")
    if not all(isinstance(e, dict) for e in entries):
        raise invalid("every entry of `transfers` must be an object")
    transfers = []
    for i, entry in enumerate(entries):
        where = f"transfers[{i}]"
        from_handle = _handle(entry, "from_handle", where)
        to_handle = _handle(entry, "to_handle", where)
        amount = fields.amount(entry)
        note = fields.note(entry)
        visibility = fields.visibility(entry)
        sender = payments.user_by_handle(conn, from_handle)
        receiver = payments.user_by_handle(conn, to_handle)
        if sender["id"] == receiver["id"]:
            raise ApiError(422, "self_payment", f"{where}: cannot transfer to the same wallet")
        transfers.append(Transfer(sender["id"], receiver["id"], amount, note, visibility))
    return transfers


def commit(conn: sqlite3.Connection, operator_id: str,
           transfers: list[Transfer]) -> dict[str, Any]:
    """Move every balance by its net delta and record the member payments, or raise
    409 `insufficient_funds` having changed nothing. Call inside a write transaction."""
    deltas: dict[str, int] = defaultdict(int)
    for t in transfers:
        deltas[t.from_user_id] -= t.amount
        deltas[t.to_user_id] += t.amount
    # Debits first: each is guarded, so a short wallet aborts before anything is credited.
    for user_id, delta in sorted(deltas.items(), key=lambda item: item[1]):
        if delta == 0:
            continue
        moved = conn.execute(
            "UPDATE users SET balance = balance + ? WHERE id = ? AND balance + ? >= 0",
            (delta, user_id, delta)).rowcount
        if moved != 1:
            raise payments.insufficient_funds()

    settlement_id = new_id("st")
    committed_at, committed_ts = timeutil.now()
    conn.execute(
        "INSERT INTO settlements (id, operator_id, committed_at, created_ts) VALUES (?, ?, ?, ?)",
        (settlement_id, operator_id, committed_at, committed_ts))
    payment_ids = [
        payments.insert_payment(conn, from_user_id=t.from_user_id, to_user_id=t.to_user_id,
                                amount=t.amount, note=t.note, visibility=t.visibility,
                                settlement_id=settlement_id,
                                created=(committed_at, committed_ts))
        for t in transfers]
    return {
        "settlement_id": settlement_id,
        "committed_at": committed_at,
        "payments": [payments.load_payment(conn, pid) for pid in payment_ids],
    }
