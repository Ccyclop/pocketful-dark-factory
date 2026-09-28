"""The equal-split rule (§9) and split records.

Shares are whole minor units, sum exactly to the amount and differ by at most one unit;
the larger shares go to the first participants in the order given (S1-MON-1).
"""
from __future__ import annotations

import sqlite3

from .ids import new_id


def equal_split(amount: int, count: int) -> list[int]:
    """1000/3 -> [334, 333, 333]; 1/3 -> [1, 0, 0]. `amount` >= 0, `count` >= 1."""
    base, remainder = divmod(amount, count)
    return [base + 1 if i < remainder else base for i in range(count)]


def record(conn: sqlite3.Connection, *, requester_id: str, amount: int, note: str,
           created_at: str, created_ts: float) -> str:
    """Store the split itself; returns its id. Call inside a write transaction."""
    split_id = new_id("sp")
    conn.execute(
        "INSERT INTO splits (id, requester_id, amount, note, created_at, created_ts)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (split_id, requester_id, amount, note, created_at, created_ts))
    return split_id
