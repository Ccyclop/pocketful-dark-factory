#!/usr/bin/env python3
"""Auth attacks: token handling, signup races, derived handles, email case."""
from __future__ import annotations

import uuid
from concurrent.futures import ThreadPoolExecutor
from attack_common import req, record, reset_fixture, login, auth_headers


def attack_auth():
    print("\n=== AUTH ATTACKS ===")

    reset_fixture()
    # Missing token
    s, _, _ = req("GET", "/me")
    record("auth", "missing_token_401", s == 401, f"status={s}")
    # Invalid token
    s, _, _ = req("GET", "/me", headers={"Authorization": "Bearer invalidtoken123"})
    record("auth", "invalid_token_401", s == 401, f"status={s}")
    # Wrong scheme
    s, _, _ = req("GET", "/me", headers={"Authorization": "Basic abc"})
    record("auth", "wrong_scheme_401", s == 401, f"status={s}")

    # Signup race - same email concurrently
    reset_fixture()
    with ThreadPoolExecutor(20) as pool:
        codes = list(pool.map(lambda _: req("POST", "/auth/signup",
            {"email": "race@example.com", "password": "correct horse", "display_name": "Race"})[0], range(20)))
    record("auth", "signup_race", sorted(codes) == [201] + [409] * 19, f"codes={sorted(set(codes))}")

    # Signup different emails all succeed
    reset_fixture()
    with ThreadPoolExecutor(20) as pool:
        codes = list(pool.map(lambda i: req("POST", "/auth/signup",
            {"email": f"user{i}@example.com", "password": "correct horse", "display_name": f"U{i}"})[0], range(20)))
    record("auth", "signup_different", codes == [201] * 20, f"codes={sorted(set(codes))}")

    # Case-insensitive email
    reset_fixture()
    req("POST", "/auth/signup", {"email": "test@example.com", "password": "correct horse", "display_name": "Test"})
    s, _, _ = req("POST", "/auth/signup", {"email": "TEST@example.com", "password": "correct horse", "display_name": "T2"})
    record("auth", "email_case_insensitive", s == 409, f"status={s}")

    # Handle derivation with special chars
    reset_fixture()
    s, r, _ = req("POST", "/auth/signup", {"email": "a.b+c@example.com", "password": "correct horse", "display_name": "AB"})
    record("auth", "handle_derivation", s == 201, f"status={s}")

    # Login wrong password
    reset_fixture()
    s, _, _ = req("POST", "/auth/login", {"email": "ada@example.com", "password": "wrong password"})
    record("auth", "wrong_password_401", s == 401, f"status={s}")

    # Login unknown email
    s, _, _ = req("POST", "/auth/login", {"email": "nobody@example.com", "password": "correct horse"})
    record("auth", "unknown_email_401", s == 401, f"status={s}")

    # Password too short
    s, _, _ = req("POST", "/auth/signup", {"email": "short@example.com", "password": "short", "display_name": "S"})
    record("auth", "password_short_422", s == 422, f"status={s}")

    # Invalid email formats
    for email in ["noat", "@nodomain", "no@spaces@x", ""]:
        s, _, _ = req("POST", "/auth/signup", {"email": email, "password": "correct horse", "display_name": "X"})
        record("auth", f"bad_email_{email!r}", s == 422, f"status={s}")

    # Multiple tokens for same user
    reset_fixture()
    _, t1 = login("ada@example.com")
    _, t2 = login("ada@example.com")
    s1, _, _ = req("GET", "/me", headers=auth_headers(t1))
    s2, _, _ = req("GET", "/me", headers=auth_headers(t2))
    record("auth", "multiple_tokens", s1 == 200 and s2 == 200, f"{s1},{s2}")

    # Token cleared by reset
    reset_fixture()
    _, token = login("ada@example.com")
    reset_fixture()
    s, _, _ = req("GET", "/me", headers=auth_headers(token))
    record("auth", "token_cleared_by_reset", s == 401, f"status={s}")


if __name__ == "__main__":
    attack_auth()
    from attack_common import summary
    ok = summary()
    exit(0 if ok else 1)
