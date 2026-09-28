"""POST /auth/signup and POST /auth/login (§6)."""
from __future__ import annotations

import sqlite3
from typing import Any

from fastapi import APIRouter, Depends, Request

from ..auth import unauthenticated
from ..errors import ApiError
from ..ids import new_id
from ..jsonbody import invalid, json_object, malformed
from ..responses import JsonResponse
from ..security import (burn_password_check, hash_password, new_token, token_digest,
                        verify_password)
from ..users import PASSWORD_MIN, derive_handle, email_key, is_valid_email

router = APIRouter()


def string_fields(body: dict[str, Any], names: tuple[str, ...]) -> dict[str, str]:
    """Required string fields: any wrong type (incl. null) is 400, then any missing is
    422 (D5, D8)."""
    for name in names:
        if name in body and not isinstance(body[name], str):
            raise malformed(f"`{name}` must be a string")
    for name in names:
        if name not in body:
            raise invalid(f"`{name}` is required")
    return {name: body[name] for name in names}


def issue_token(conn: sqlite3.Connection, user_id: str) -> str:
    token = new_token()
    conn.execute("INSERT INTO tokens (token_hash, user_id) VALUES (?, ?)",
                 (token_digest(token), user_id))
    return token


@router.post("/auth/signup", status_code=201)
def signup(request: Request, body: dict[str, Any] = Depends(json_object)) -> JsonResponse:
    fields = string_fields(body, ("email", "password", "display_name"))
    email, password = fields["email"], fields["password"]
    if not is_valid_email(email):
        raise invalid("`email` must be of the form local@domain")
    if len(password) < PASSWORD_MIN:
        raise invalid(f"`password` must be at least {PASSWORD_MIN} characters")
    handle = derive_handle(email)
    # Hashing is the slow part; do it before taking the write lock.
    password_hash = hash_password(password)
    with request.app.state.db.transaction() as conn:
        if conn.execute("SELECT 1 FROM users WHERE email_key = ?",
                        (email_key(email),)).fetchone():
            raise ApiError(409, "email_taken", "email already registered")
        if conn.execute("SELECT 1 FROM users WHERE handle = ?", (handle,)).fetchone():
            raise ApiError(409, "handle_taken", f"handle {handle!r} is already taken")
        user_id = new_id("u")
        while conn.execute("SELECT 1 FROM users WHERE id = ?", (user_id,)).fetchone():
            user_id = new_id("u")
        conn.execute(
            "INSERT INTO users (id, email, email_key, password_hash, display_name, handle,"
            " balance) VALUES (?, ?, ?, ?, ?, ?, 0)",
            (user_id, email, email_key(email), password_hash, fields["display_name"], handle))
        token = issue_token(conn, user_id)
    return JsonResponse({"user_id": user_id, "display_name": fields["display_name"],
                         "token": token}, status_code=201)


@router.post("/auth/login")
def login(request: Request, body: dict[str, Any] = Depends(json_object)) -> JsonResponse:
    fields = string_fields(body, ("email", "password"))
    db = request.app.state.db
    user = db.connection().execute(
        "SELECT id, display_name, password_hash FROM users WHERE email_key = ?",
        (email_key(fields["email"]),)).fetchone()
    if user is None:
        burn_password_check(fields["password"])
        raise unauthenticated("wrong email or password")
    if not verify_password(fields["password"], user["password_hash"]):
        raise unauthenticated("wrong email or password")
    with db.transaction() as conn:
        # A reset may have replaced the user since the check above.
        if conn.execute("SELECT 1 FROM users WHERE id = ? AND password_hash = ?",
                        (user["id"], user["password_hash"])).fetchone() is None:
            raise unauthenticated("wrong email or password")
        token = issue_token(conn, user["id"])
    return JsonResponse({"user_id": user["id"], "display_name": user["display_name"],
                         "token": token})
