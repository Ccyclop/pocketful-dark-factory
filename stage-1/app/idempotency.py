"""Idempotent write paths (§7), shared by every endpoint that takes an Idempotency-Key.

Usage in a router:

    @router.post("/payments", status_code=201)
    def create(request: Request,
               user: sqlite3.Row = Depends(current_user),          # 401 first (D1)
               key: str = Depends(idempotency_key),                # then 400/422 key
               body: dict[str, Any] = Depends(json_object)):       # then 400 body
        return run(request, user, key, body, lambda conn: do_the_write(conn, ...))

`run()` opens one write transaction, resolves an already claimed key (200 replay or
409 reuse) before the operation sees the body, and otherwise runs the operation and
claims the key with its response in the same transaction. The operation validates the
body and raises `ApiError` for any 4xx, which rolls everything back and leaves the key
unclaimed (D2). Because writers are serialised, concurrent identical requests with an
unused key yield exactly one 201 and replays of it (S1-IDEM-7).
"""
from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable
from decimal import Decimal
from typing import Any

from fastapi import Request

from .auth import unauthenticated
from .errors import ApiError
from .responses import JsonResponse

KEY_HEADER = "idempotency-key"
KEY_MAX = 255


def idempotency_key(request: Request) -> str:
    """The Idempotency-Key header: absent or empty is 400, over 255 code points is 422."""
    raw = request.headers.get(KEY_HEADER)
    if not raw:
        raise ApiError(400, "missing_idempotency_key", "Idempotency-Key header is required")
    # Starlette decodes headers as latin-1; count code points of the UTF-8 text (D7).
    try:
        key = raw.encode("latin-1").decode("utf-8")
    except UnicodeError:
        key = raw
    if len(key) > KEY_MAX:
        raise ApiError(422, "validation_failed",
                       f"Idempotency-Key must be 1 to {KEY_MAX} characters")
    return key


def _canonical(value: Any) -> Any:
    """A form in which two bodies are equal exactly when they are the same JSON value
    (S1-IDEM-6, D3): object key order is ignored, numbers compare by exact value, and
    `true` is not `1`."""
    if isinstance(value, dict):
        return {"o": {k: _canonical(v) for k, v in value.items()}}
    if isinstance(value, list):
        return {"a": [_canonical(v) for v in value]}
    if isinstance(value, bool) or value is None:
        return {"l": value}
    if isinstance(value, (int, Decimal)):
        number = Decimal(value)
        return {"n": "0" if number.is_zero() else str(number.normalize())}
    return {"s": value}


def fingerprint(body: Any) -> str:
    return json.dumps(_canonical(body), sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"))


Operation = Callable[[sqlite3.Connection], dict[str, Any]]


def run(request: Request, user: sqlite3.Row, key: str, body: dict[str, Any],
        operation: Operation, status: int = 201) -> JsonResponse:
    method, path = request.method, request.url.path
    body_print = fingerprint(body)
    with request.app.state.db.transaction() as conn:
        # A reset may have removed the caller since authentication.
        if conn.execute("SELECT 1 FROM users WHERE id = ?", (user["id"],)).fetchone() is None:
            raise unauthenticated()
        claimed = conn.execute(
            "SELECT fingerprint, response FROM idempotency"
            " WHERE user_id = ? AND method = ? AND path = ? AND key = ?",
            (user["id"], method, path, key)).fetchone()
        if claimed is not None:
            if claimed["fingerprint"] != body_print:
                raise ApiError(409, "idempotency_key_reuse",
                               "Idempotency-Key was already used with a different body")
            return JsonResponse(json.loads(claimed["response"]), status_code=200)
        result = operation(conn)
        conn.execute(
            "INSERT INTO idempotency (user_id, method, path, key, fingerprint, status, response)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (user["id"], method, path, key, body_print, status,
             json.dumps(result, ensure_ascii=False, separators=(",", ":"))))
    return JsonResponse(result, status_code=status)
