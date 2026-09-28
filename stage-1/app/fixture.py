"""The reset fixture (§4): validation, then loading as the whole service state.

`validate()` checks everything before any state changes, so an invalid fixture is
422 `validation_failed` and the previous state is untouched (S1-FIX-4, D12).
"""
from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass, field
from typing import Any

from . import timeutil
from .db import MAX_BALANCE, clear_state
from .jsonbody import integral, invalid
from .security import hash_passwords

HANDLE_RE = re.compile(r"[a-z0-9_]{1,20}")
MINOR_UNITS = (0, 2, 3)
MAX_AMOUNT = 1_000_000_000
VISIBILITIES = ("public", "private")
STATUSES = ("pending", "paid", "declined", "cancelled")


def email_key(email: str) -> str:
    """Emails are unique and looked up case-insensitively (D8)."""
    return email.lower()


@dataclass
class Fixture:
    currency: str
    minor_units: int
    users: list[dict[str, Any]] = field(default_factory=list)
    payments: list[dict[str, Any]] = field(default_factory=list)
    requests: list[dict[str, Any]] = field(default_factory=list)
    operator_ids: set[str] = field(default_factory=set)


def _string(obj: dict, key: str, where: str, *, default: str | None = None) -> str:
    if key not in obj:
        if default is not None:
            return default
        raise invalid(f"{where}: `{key}` is required")
    value = obj[key]
    if not isinstance(value, str):
        raise invalid(f"{where}: `{key}` must be a string")
    return value


def _id(obj: dict, key: str, where: str) -> str:
    value = _string(obj, key, where)
    if not value:
        raise invalid(f"{where}: `{key}` must not be empty")
    return value


def _list(body: dict, key: str) -> list:
    value = body.get(key, [])
    if value is None:
        return []
    if not isinstance(value, list):
        raise invalid(f"`{key}` must be an array")
    return value


def _objects(items: list, name: str) -> list[dict]:
    for i, item in enumerate(items):
        if not isinstance(item, dict):
            raise invalid(f"{name}[{i}] must be an object")
    return items


def _created(obj: dict, reset_time: tuple[str, float]) -> tuple[str, float]:
    return timeutil.parse_rfc3339(obj.get("created_at")) or reset_time


def validate(body: dict[str, Any]) -> Fixture:
    if "currency" not in body:
        raise invalid("`currency` is required")
    currency = body["currency"]
    if not isinstance(currency, str) or not currency:
        raise invalid("`currency` must be a non-empty string")
    if "minor_units" not in body:
        raise invalid("`minor_units` is required")
    minor_units = integral(body["minor_units"])
    if minor_units not in MINOR_UNITS:
        raise invalid("`minor_units` must be 0, 2 or 3")
    if "users" not in body:
        raise invalid("`users` is required")
    if not isinstance(body["users"], list):
        raise invalid("`users` must be an array")

    fixture = Fixture(currency=currency, minor_units=minor_units)
    ids: set[str] = set()
    handles: set[str] = set()
    emails: set[str] = set()
    total = 0
    for i, raw in enumerate(_objects(body["users"], "users")):
        where = f"users[{i}]"
        uid = _id(raw, "id", where)
        email = _id(raw, "email", where)
        password = _string(raw, "password", where)
        handle = _string(raw, "handle", where)
        if not HANDLE_RE.fullmatch(handle):
            raise invalid(f"{where}: `handle` must match ^[a-z0-9_]{{1,20}}$")
        display_name = _string(raw, "display_name", where, default=handle)
        if "balance" not in raw:
            raise invalid(f"{where}: `balance` is required")
        balance = integral(raw["balance"])
        if balance is None or balance < 0:
            raise invalid(f"{where}: `balance` must be a non-negative integer")
        if uid in ids:
            raise invalid(f"{where}: duplicate user id")
        if handle in handles:
            raise invalid(f"{where}: duplicate handle")
        if email_key(email) in emails:
            raise invalid(f"{where}: duplicate email")
        ids.add(uid)
        handles.add(handle)
        emails.add(email_key(email))
        total += balance
        if total > MAX_BALANCE:
            raise invalid("total balance exceeds 2^53")
        fixture.users.append({"id": uid, "email": email, "password": password,
                              "display_name": display_name, "handle": handle,
                              "balance": balance})

    reset_time = timeutil.now()

    payment_ids: set[str] = set()
    for i, raw in enumerate(_objects(_list(body, "payments"), "payments")):
        where = f"payments[{i}]"
        pid = _id(raw, "id", where)
        sender = _id(raw, "from_user_id", where)
        receiver = _id(raw, "to_user_id", where)
        if sender not in ids or receiver not in ids:
            raise invalid(f"{where}: names an unknown user")
        amount = integral(raw.get("amount"))
        if amount is None or not 1 <= amount <= MAX_AMOUNT:
            raise invalid(f"{where}: invalid `amount`")
        note = _string(raw, "note", where, default="")
        visibility = _string(raw, "visibility", where, default="public")
        if visibility not in VISIBILITIES:
            raise invalid(f"{where}: invalid `visibility`")
        if pid in payment_ids:
            raise invalid(f"{where}: duplicate payment id")
        payment_ids.add(pid)
        created_at, created_ts = _created(raw, reset_time)
        fixture.payments.append({"id": pid, "from_user_id": sender, "to_user_id": receiver,
                                 "amount": amount, "note": note, "visibility": visibility,
                                 "created_at": created_at, "created_ts": created_ts})

    request_ids: set[str] = set()
    for i, raw in enumerate(_objects(_list(body, "requests"), "requests")):
        where = f"requests[{i}]"
        rid = _id(raw, "id", where)
        requester = _id(raw, "requester_id", where)
        payer = _id(raw, "payer_id", where)
        if requester not in ids or payer not in ids:
            raise invalid(f"{where}: names an unknown user")
        # A request may carry 0: splits create zero-share requests (D16).
        amount = integral(raw.get("amount"))
        if amount is None or not 0 <= amount <= MAX_AMOUNT:
            raise invalid(f"{where}: invalid `amount`")
        note = _string(raw, "note", where, default="")
        status = _string(raw, "status", where, default="pending")
        if status not in STATUSES:
            raise invalid(f"{where}: invalid `status`")
        payment_id = raw.get("payment_id")
        if payment_id is not None and not isinstance(payment_id, str):
            raise invalid(f"{where}: `payment_id` must be a string or null")
        if rid in request_ids:
            raise invalid(f"{where}: duplicate request id")
        request_ids.add(rid)
        created_at, created_ts = _created(raw, reset_time)
        fixture.requests.append({"id": rid, "requester_id": requester, "payer_id": payer,
                                 "amount": amount, "note": note, "status": status,
                                 "payment_id": payment_id if status == "paid" else None,
                                 "created_at": created_at, "created_ts": created_ts})

    operators = _list(body, "settlement_operator_ids")
    # Operator ids that name no user are ignored (D12).
    fixture.operator_ids = {oid for oid in operators if isinstance(oid, str) and oid in ids}
    return fixture


def hash_credentials(fixture: Fixture) -> list[str]:
    """Password hashes for the fixture's users, in order. Slow; call before locking."""
    return hash_passwords(u["password"] for u in fixture.users)


def load(conn: sqlite3.Connection, fixture: Fixture, password_hashes: list[str]) -> None:
    """Replace all state with the fixture. Call inside a transaction."""
    clear_state(conn)
    conn.execute("INSERT INTO service (id, currency, minor_units) VALUES (1, ?, ?)",
                 (fixture.currency, fixture.minor_units))
    conn.executemany(
        "INSERT INTO users (id, email, email_key, password_hash, display_name, handle,"
        " balance, is_operator) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [(u["id"], u["email"], email_key(u["email"]), pw, u["display_name"], u["handle"],
          u["balance"], int(u["id"] in fixture.operator_ids))
         for u, pw in zip(fixture.users, password_hashes)])
    conn.executemany(
        "INSERT INTO payments (id, from_user_id, to_user_id, amount, note, visibility,"
        " request_id, settlement_id, created_at, created_ts)"
        " VALUES (:id, :from_user_id, :to_user_id, :amount, :note, :visibility,"
        " NULL, NULL, :created_at, :created_ts)",
        fixture.payments)
    conn.executemany(
        "INSERT INTO requests (id, requester_id, payer_id, amount, note, status, payment_id,"
        " created_at, created_ts) VALUES (:id, :requester_id, :payer_id, :amount, :note,"
        " :status, :payment_id, :created_at, :created_ts)",
        fixture.requests)
