#!/usr/bin/env python3
"""Concurrency attacks: simultaneous requests competing for the same resource."""
from __future__ import annotations

import random
import uuid
from concurrent.futures import ThreadPoolExecutor

from attack_common import req, record, reset_fixture, login, auth_headers


def attack_concurrency():
    print("\n=== CONCURRENCY ATTACKS ===")

    # 1a. Concurrent identical idempotency-key requests (S1-IDEM-7)
    reset_fixture()
    _, token = login("ada@example.com")
    k = uuid.uuid4().hex
    with ThreadPoolExecutor(50) as pool:
        codes = list(pool.map(lambda _: req("POST", "/payments",
            {"to_handle": "bob", "amount": 100}, auth_headers(token, k))[0], range(50)))
    passed = sorted(codes) == [200] * 49 + [201]
    record("concurrency", "idem_key_one_201_rest_200", passed, f"codes={sorted(set(codes))}")

    # 1b. Concurrent drain - money conservation (S1-INV-1, S1-INV-2)
    reset_fixture(users=[
        {"id": "u_ada", "email": "ada@example.com", "password": "correct horse",
         "display_name": "Ada", "handle": "ada", "balance": 1000},
        {"id": "u_bob", "email": "bob@example.com", "password": "correct horse",
         "display_name": "Bob", "handle": "bob", "balance": 0},
    ])
    _, token = login("ada@example.com")
    with ThreadPoolExecutor(50) as pool:
        codes = list(pool.map(lambda _: req("POST", "/payments",
            {"to_handle": "bob", "amount": 100}, auth_headers(token, uuid.uuid4().hex))[0], range(50)))
    passed = sorted(codes) == [201] * 10 + [409] * 40
    record("concurrency", "drain_10_success_40_fail", passed, f"codes={sorted(set(codes))}")

    # 1c. Random burst conserves money (S1-INV-1)
    reset_fixture()
    _, t_ada = login("ada@example.com")
    _, t_bob = login("bob@example.com")
    _, t_cy = login("cy@example.com")
    tokens = [t_ada, t_bob, t_cy]
    handles = ["ada", "bob", "cy"]
    with ThreadPoolExecutor(50) as pool:
        def one(i):
            rnd = random.Random(i)
            src = rnd.randrange(3)
            dst = (src + 1 + rnd.randrange(2)) % 3
            return req("POST", "/payments", {"to_handle": handles[dst], "amount": rnd.randint(1, 3000)},
                       auth_headers(tokens[src], uuid.uuid4().hex))[0]
        codes = list(pool.map(one, range(50)))
    passed = set(codes) <= {201, 409}
    record("concurrency", "random_burst_no_5xx", passed, f"codes={sorted(set(codes))}")

    # 1d. Concurrent settlements racing on same wallets
    reset_fixture(users=[
        {"id": "u_ada", "email": "ada@example.com", "password": "correct horse",
         "display_name": "Ada", "handle": "ada", "balance": 10000},
        {"id": "u_bob", "email": "bob@example.com", "password": "correct horse",
         "display_name": "Bob", "handle": "bob", "balance": 2500},
        {"id": "u_cy", "email": "cy@example.com", "password": "correct horse",
         "display_name": "Cy", "handle": "cy", "balance": 500},
    ], operators=["u_ada"])
    _, op_token = login("ada@example.com")
    with ThreadPoolExecutor(20) as pool:
        def settle(i):
            return req("POST", "/settlements", {"transfers": [
                {"from_handle": "ada", "to_handle": "bob", "amount": 100},
                {"from_handle": "bob", "to_handle": "cy", "amount": 50}]},
                auth_headers(op_token, uuid.uuid4().hex))[0]
        codes = list(pool.map(settle, range(20)))
    passed = set(codes) <= {201, 409}
    record("concurrency", "concurrent_settlements", passed, f"codes={sorted(set(codes))}")

    # 1e. Concurrent pay on same request (S1-INV-3)
    reset_fixture()
    _, t_ada = login("ada@example.com")
    _, t_bob = login("bob@example.com")
    req("POST", "/requests", {"payer_handle": "ada", "amount": 500, "note": "test"},
        auth_headers(t_bob, uuid.uuid4().hex))
    _, resp, _ = req("GET", "/requests?direction=incoming", headers=auth_headers(t_ada))
    rq_id = resp["requests"][0]["request_id"]
    with ThreadPoolExecutor(20) as pool:
        codes = list(pool.map(lambda _: req("POST", f"/requests/{rq_id}/pay", {},
            auth_headers(t_ada, uuid.uuid4().hex))[0], range(20)))
    passed = sorted(codes) == [201] + [409] * 19
    record("concurrency", "concurrent_pay_one_success", passed, f"codes={sorted(set(codes))}")

    # 1f. Concurrent decline and cancel on same request
    reset_fixture()
    _, t_ada = login("ada@example.com")
    _, t_bob = login("bob@example.com")
    req("POST", "/requests", {"payer_handle": "ada", "amount": 500, "note": "test"},
        auth_headers(t_bob, uuid.uuid4().hex))
    _, resp, _ = req("GET", "/requests?direction=incoming", headers=auth_headers(t_ada))
    rq_id = resp["requests"][0]["request_id"]
    with ThreadPoolExecutor(20) as pool:
        def act(i):
            if i % 2 == 0:
                return req("POST", f"/requests/{rq_id}/decline", headers=auth_headers(t_ada))[0]
            else:
                return req("POST", f"/requests/{rq_id}/cancel", headers=auth_headers(t_bob))[0]
        codes = list(pool.map(act, range(20)))
    passed = set(codes) <= {200, 409}
    record("concurrency", "concurrent_decline_cancel", passed, f"codes={sorted(set(codes))}")

    # 1g. Concurrent splits
    reset_fixture()
    _, t_ada = login("ada@example.com")
    with ThreadPoolExecutor(20) as pool:
        codes = list(pool.map(lambda _: req("POST", "/splits",
            {"amount": 100, "participant_handles": ["ada", "bob", "cy"]},
            auth_headers(t_ada, uuid.uuid4().hex))[0], range(20)))
    passed = set(codes) <= {201, 422}
    record("concurrency", "concurrent_splits", passed, f"codes={sorted(set(codes))}")

    # 1h. Concurrent signup with same email
    reset_fixture()
    with ThreadPoolExecutor(20) as pool:
        codes = list(pool.map(lambda _: req("POST", "/auth/signup",
            {"email": "race@example.com", "password": "correct horse", "display_name": "Race"})[0], range(20)))
    passed = sorted(codes) == [201] + [409] * 19
    record("concurrency", "signup_race_same_email", passed, f"codes={sorted(set(codes))}")

    # 1i. Concurrent login
    reset_fixture()
    with ThreadPoolExecutor(50) as pool:
        codes = list(pool.map(lambda _: req("POST", "/auth/login",
            {"email": "ada@example.com", "password": "correct horse"})[0], range(50)))
    passed = codes == [200] * 50
    record("concurrency", "concurrent_login_50", passed, f"codes={sorted(set(codes))}")

    # 1j. Concurrent reset and write
    reset_fixture()
    _, t_ada = login("ada@example.com")
    _, t_bob = login("bob@example.com")
    with ThreadPoolExecutor(10) as pool:
        def mixed(i):
            if i % 3 == 0:
                return req("POST", "/_test/reset", {"currency": "EUR", "minor_units": 2,
                    "users": [{"id": "u_ada", "email": "ada@example.com", "password": "correct horse",
                              "display_name": "Ada", "handle": "ada", "balance": 10000}]})[0]
            else:
                return req("POST", "/payments", {"to_handle": "bob", "amount": 1},
                    auth_headers(t_ada, uuid.uuid4().hex))[0]
        codes = list(pool.map(mixed, range(30)))
    passed = set(codes) <= {201, 204, 401, 404, 409}
    record("concurrency", "concurrent_reset_and_write", passed, f"codes={sorted(set(codes))}")


if __name__ == "__main__":
    attack_concurrency()
    from attack_common import summary
    ok = summary()
    exit(0 if ok else 1)
