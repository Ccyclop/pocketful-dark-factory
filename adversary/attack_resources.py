#!/usr/bin/env python3
"""Resource limit attacks: 50 in flight, latency, reset/import timing, memory."""
from __future__ import annotations

import json
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from attack_common import req, record, reset_fixture, login, auth_headers


def attack_resources():
    print("\n=== RESOURCE LIMIT ATTACKS ===")

    # 50 concurrent requests in flight
    reset_fixture()
    _, token = login("ada@example.com")
    start = time.monotonic()
    with ThreadPoolExecutor(50) as pool:
        codes = list(pool.map(lambda _: req("POST", "/payments",
            {"to_handle": "bob", "amount": 1}, auth_headers(token, uuid.uuid4().hex))[0], range(50)))
    elapsed = time.monotonic() - start
    record("resources", "50_in_flight", set(codes) <= {201, 409} and elapsed < 5.0,
           f"codes={sorted(set(codes))}, elapsed={elapsed:.2f}s")

    # Reset with 200 users within 10s
    users = [{"id": f"u_{i}", "email": f"user{i}@example.com", "password": "correct horse",
              "display_name": f"U{i}", "handle": f"u{i}", "balance": 100} for i in range(200)]
    start = time.monotonic()
    s, _, _ = req("POST", "/_test/reset", {"currency": "EUR", "minor_units": 2, "users": users})
    elapsed = time.monotonic() - start
    record("resources", "reset_200_users", s == 204 and elapsed < 10.0,
           f"status={s}, elapsed={elapsed:.2f}s")

    # Import with 200 users within 10s
    _, export, _ = req("GET", "/_test/export")
    start = time.monotonic()
    s, _, _ = req("POST", "/_test/import", export)
    elapsed = time.monotonic() - start
    record("resources", "import_200_users", s == 204 and elapsed < 10.0,
           f"status={s}, elapsed={elapsed:.2f}s")

    # 50 concurrent logins within 5s
    reset_fixture()
    start = time.monotonic()
    with ThreadPoolExecutor(50) as pool:
        codes = list(pool.map(lambda _: req("POST", "/auth/login",
            {"email": "ada@example.com", "password": "correct horse"})[0], range(50)))
    elapsed = time.monotonic() - start
    record("resources", "50_concurrent_logins", codes == [200] * 50 and elapsed < 5.0,
           f"codes={sorted(set(codes))}, elapsed={elapsed:.2f}s")

    # Large fixture reset
    users = [{"id": f"u_{i}", "email": f"user{i}@example.com", "password": "correct horse",
              "display_name": f"U{i}", "handle": f"u{i}", "balance": 1000000} for i in range(200)]
    start = time.monotonic()
    s, _, _ = req("POST", "/_test/reset", {"currency": "EUR", "minor_units": 2, "users": users})
    elapsed = time.monotonic() - start
    record("resources", "reset_large_balances", s == 204 and elapsed < 10.0,
           f"status={s}, elapsed={elapsed:.2f}s")

    # Oversized body
    reset_fixture()
    _, token = login("ada@example.com")
    big_note = "x" * 10000
    s, _, _ = req("POST", "/payments", {"to_handle": "bob", "amount": 1, "note": big_note},
                   auth_headers(token, uuid.uuid4().hex))
    record("resources", "oversized_body", s == 422, f"status={s}")

    # Deeply nested JSON
    reset_fixture()
    _, token = login("ada@example.com")
    deep = {"to_handle": "bob", "amount": 1}
    for _ in range(100):
        deep = {"nested": deep}
    s, _, _ = req("POST", "/payments", deep, auth_headers(token, uuid.uuid4().hex))
    record("resources", "deeply_nested", s == 422, f"status={s}")


if __name__ == "__main__":
    attack_resources()
    from attack_common import summary
    ok = summary()
    exit(0 if ok else 1)
