"""Shared helpers for M1 attack scripts."""
from __future__ import annotations

import json
import threading
import time
import urllib.request
import urllib.error
from typing import Any

BASE = "http://localhost:8080"
RESULTS: list[dict[str, Any]] = []
LOCK = threading.Lock()


def req(method: str, path: str, body: Any = None, headers: dict | None = None,
        raw: bytes | None = None, timeout: float = 10.0) -> tuple[int, dict | str, float]:
    url = BASE + path
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    h = {"Content-Type": "application/json"}
    if headers:
        h.update(headers)
    r = urllib.request.Request(url, data=data, headers=h, method=method)
    start = time.monotonic()
    try:
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            elapsed = time.monotonic() - start
            text = resp.read().decode()
            try:
                return resp.status, json.loads(text), elapsed
            except json.JSONDecodeError:
                return resp.status, text, elapsed
    except urllib.error.HTTPError as e:
        elapsed = time.monotonic() - start
        text = e.read().decode()
        try:
            return e.code, json.loads(text), elapsed
        except json.JSONDecodeError:
            return e.code, text, elapsed
    except Exception as e:
        elapsed = time.monotonic() - start
        return -1, str(e), elapsed


def record(category: str, name: str, passed: bool, detail: str = ""):
    with LOCK:
        RESULTS.append({"category": category, "name": name, "passed": passed, "detail": detail})
    status = "PASS" if passed else "FAIL"
    print(f"  [{status}] {category}/{name}: {detail}")


def reset_fixture(users=None, payments=None, requests=None, operators=None):
    if users is None:
        users = [
            {"id": "u_ada", "email": "ada@example.com", "password": "correct horse",
             "display_name": "Ada", "handle": "ada", "balance": 10000},
            {"id": "u_bob", "email": "bob@example.com", "password": "correct horse",
             "display_name": "Bob", "handle": "bob", "balance": 2500},
            {"id": "u_cy", "email": "cy@example.com", "password": "correct horse",
             "display_name": "Cy", "handle": "cy", "balance": 500},
        ]
    body = {"currency": "EUR", "minor_units": 2, "users": users,
            "payments": payments or [], "requests": requests or []}
    if operators:
        body["settlement_operator_ids"] = operators
    status, resp, _ = req("POST", "/_test/reset", body)
    return status == 204


def login(email: str, password: str = "correct horse") -> tuple[int, str]:
    status, resp, _ = req("POST", "/auth/login", {"email": email, "password": password})
    if status == 200:
        return status, resp["token"]
    return status, ""


def auth_headers(token: str, idem: str | None = None) -> dict:
    h = {"Authorization": f"Bearer {token}"}
    if idem:
        h["Idempotency-Key"] = idem
    return h


def summary():
    total = len(RESULTS)
    passed = sum(1 for r in RESULTS if r["passed"])
    failed = total - passed
    print(f"\n{'='*60}")
    print(f"RESULTS: {passed}/{total} passed, {failed} failed")
    if failed:
        print("\nFAILURES:")
        for r in RESULTS:
            if not r["passed"]:
                print(f"  {r['category']}/{r['name']}: {r['detail']}")
    print(f"{'='*60}")
    return failed == 0
