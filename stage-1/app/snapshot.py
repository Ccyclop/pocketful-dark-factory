"""Export and import of the whole service state (§10).

The state is every row of every state table, column for column:

    {"tables": {"<table>": {"columns": [...], "rows": [[...], ...]}, ...}}

Nothing is regenerated on import: ids, timestamps, balances, password hashes, token
digests and stored idempotent responses come back exactly as exported, so old tokens,
receipts and retries stay valid. Import checks the shape and every value's type against
the schema, then loads the rows in one transaction; the database constraints (foreign
keys, uniqueness, balance range) reject anything else, and any failure is 422 with the
previous state untouched.
"""
from __future__ import annotations

import sqlite3
from decimal import Decimal
from typing import Any

from .db import MAX_BALANCE, STATE_TABLES, clear_state
from .jsonbody import invalid

TRACK = "pocketful"
FORMAT_VERSION = 1

# Parents before children, so foreign keys hold while loading.
LOAD_ORDER = tuple(reversed(STATE_TABLES))


def _columns(conn: sqlite3.Connection, table: str) -> list[sqlite3.Row]:
    return conn.execute(f"PRAGMA table_info({table})").fetchall()


def export_state(conn: sqlite3.Connection) -> dict[str, Any]:
    """Call inside a read snapshot so every table comes from the same moment."""
    tables = {}
    for table in LOAD_ORDER:
        names = [c["name"] for c in _columns(conn, table)]
        rows = conn.execute(
            f"SELECT {', '.join(names)} FROM {table} ORDER BY rowid").fetchall()
        tables[table] = {"columns": names, "rows": [list(row) for row in rows]}
    return {"tables": tables}


def export_document(conn: sqlite3.Connection) -> dict[str, Any]:
    return {"track": TRACK, "format_version": FORMAT_VERSION, "state": export_state(conn)}


def _value(column: sqlite3.Row, value: Any, where: str) -> Any:
    """A JSON value checked against the column's declared type."""
    if value is None:
        if column["notnull"] and not column["pk"]:
            raise invalid(f"{where}: must not be null")
        return None
    kind = column["type"].upper()
    if kind == "TEXT":
        if isinstance(value, str):
            return value
    elif kind == "INTEGER":
        if isinstance(value, int) and not isinstance(value, bool):
            return value
    elif kind == "REAL":
        if isinstance(value, bool):
            pass
        elif isinstance(value, int):
            return float(value)
        elif isinstance(value, Decimal) and value.is_finite():
            return float(value)
    raise invalid(f"{where}: expected {kind.lower()}")


def _rows(conn: sqlite3.Connection, table: str, data: Any) -> list[tuple]:
    columns = _columns(conn, table)
    names = [c["name"] for c in columns]
    if not isinstance(data, dict) or data.get("columns") != names:
        raise invalid(f"state: table {table} must list columns {names}")
    rows = data.get("rows")
    if not isinstance(rows, list):
        raise invalid(f"state: table {table} must have a rows array")
    checked = []
    for i, row in enumerate(rows):
        if not isinstance(row, list) or len(row) != len(columns):
            raise invalid(f"state: {table}[{i}] must have {len(columns)} values")
        checked.append(tuple(_value(col, v, f"state: {table}[{i}].{col['name']}")
                             for col, v in zip(columns, row)))
    return checked


def validate_document(conn: sqlite3.Connection, body: dict[str, Any]) -> dict[str, list]:
    """The rows to load for each table, or 422 `validation_failed`."""
    if body.get("track") != TRACK:
        raise invalid('`track` must be "pocketful"')
    version = body.get("format_version")
    if isinstance(version, bool) or not isinstance(version, int) or version != FORMAT_VERSION:
        raise invalid("`format_version` must be 1")
    state = body.get("state")
    if not isinstance(state, dict) or not isinstance(state.get("tables"), dict):
        raise invalid("`state` is not a state exported by this service")
    tables = state["tables"]
    if set(tables) != set(STATE_TABLES):
        raise invalid("`state` must contain exactly the tables this service exports")
    loaded = {table: _rows(conn, table, tables[table]) for table in LOAD_ORDER}
    if len(loaded["service"]) != 1:
        raise invalid("`state` must declare exactly one currency")
    return loaded


def import_rows(conn: sqlite3.Connection, loaded: dict[str, list]) -> None:
    """Replace all state with the given rows. Call inside a write transaction."""
    clear_state(conn)
    for table in LOAD_ORDER:
        rows = loaded[table]
        if not rows:
            continue
        names = [c["name"] for c in _columns(conn, table)]
        placeholders = ", ".join("?" for _ in names)
        try:
            conn.executemany(
                f"INSERT INTO {table} ({', '.join(names)}) VALUES ({placeholders})", rows)
        except sqlite3.IntegrityError as exc:
            raise invalid(f"state: table {table} violates a constraint ({exc})") from exc
    total = conn.execute("SELECT COALESCE(SUM(balance), 0) FROM users").fetchone()[0]
    if total > MAX_BALANCE:
        raise invalid("state: total balance exceeds 2^53")
