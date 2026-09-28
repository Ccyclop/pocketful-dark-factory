"""Bearer-token authentication (§6).

Use `Depends(current_user)` on every endpoint except /health, /_test/*, and the two
/auth endpoints. Declare it before any body dependency so 401 is decided first (D1).
"""
from __future__ import annotations

import sqlite3

from fastapi import Request

from .errors import ApiError
from .security import token_digest


def unauthenticated(message: str = "missing, malformed or unknown bearer token") -> ApiError:
    return ApiError(401, "unauthenticated", message)


def bearer_token(request: Request) -> str:
    header = request.headers.get("authorization", "")
    scheme, _, token = header.strip().partition(" ")
    token = token.strip()
    if scheme.lower() != "bearer" or not token or " " in token:
        raise unauthenticated()
    return token


def current_user(request: Request) -> sqlite3.Row:
    """The authenticated caller's user row, else 401 `unauthenticated`."""
    token = bearer_token(request)
    user = request.app.state.db.connection().execute(
        "SELECT users.* FROM tokens JOIN users ON users.id = tokens.user_id"
        " WHERE tokens.token_hash = ?", (token_digest(token),)).fetchone()
    if user is None:
        raise unauthenticated()
    return user
