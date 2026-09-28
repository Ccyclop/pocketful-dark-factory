#!/usr/bin/env python3
"""Rounding attacks: split edge cases, especially the 5/5 lead."""
from __future__ import annotations

import uuid
from concurrent.futures import ThreadPoolExecutor
from attack_common import req, record, reset_fixture, login, auth_headers


def attack_rounding():
    print("\n=== ROUNDING ATTACKS ===")

    # The lead: split 5 among 5 → 1,1,1,1,1
    users5 = [
        {"id": "u_ada", "email": "ada@example.com", "password": "correct horse",
         "display_name": "Ada", "handle": "ada", "balance": 10000},
        {"id": "u_bob", "email": "bob@example.com", "password": "correct horse",
         "display_name": "Bob", "handle": "bob", "balance": 2500},
        {"id": "u_cy", "email": "cy@example.com", "password": "correct horse",
         "display_name": "Cy", "handle": "cy", "balance": 500},
        {"id": "u_dan", "email": "dan@example.com", "password": "correct horse",
         "display_name": "Dan", "handle": "dan", "balance": 100},
        {"id": "u_eve", "email": "eve@example.com", "password": "correct horse",
         "display_name": "Eve", "handle": "eve", "balance": 200},
    ]
    reset_fixture(users=users5)
    _, t_ada = login("ada@example.com")
    s, r, _ = req("POST", "/splits", {"amount": 5, "participant_handles": ["ada", "bob", "cy", "dan", "eve"]},
                   auth_headers(t_ada, uuid.uuid4().hex))
    shares = [sh["amount"] for sh in r.get("shares", [])]
    record("rounding", "split_5_among_5", shares == [1, 1, 1, 1, 1], f"shares={shares}")

    # Split 1000 among 3 → 334, 333, 333
    reset_fixture()
    _, t_ada = login("ada@example.com")
    s, r, _ = req("POST", "/splits", {"amount": 1000, "participant_handles": ["ada", "bob", "cy"]},
                   auth_headers(t_ada, uuid.uuid4().hex))
    shares = [sh["amount"] for sh in r.get("shares", [])]
    record("rounding", "split_1000_among_3", shares == [334, 333, 333], f"shares={shares}")

    # Split 1 among 3 → 1, 0, 0
    reset_fixture()
    _, t_ada = login("ada@example.com")
    s, r, _ = req("POST", "/splits", {"amount": 1, "participant_handles": ["ada", "bob", "cy"]},
                   auth_headers(t_ada, uuid.uuid4().hex))
    shares = [sh["amount"] for sh in r.get("shares", [])]
    record("rounding", "split_1_among_3", shares == [1, 0, 0], f"shares={shares}")

    # Split 10 among 3 → 4, 3, 3
    reset_fixture()
    _, t_ada = login("ada@example.com")
    s, r, _ = req("POST", "/splits", {"amount": 10, "participant_handles": ["ada", "bob", "cy"]},
                   auth_headers(t_ada, uuid.uuid4().hex))
    shares = [sh["amount"] for sh in r.get("shares", [])]
    record("rounding", "split_10_among_3", shares == [4, 3, 3], f"shares={shares}")

    # Split 999 among 3 → 333, 333, 333
    reset_fixture()
    _, t_ada = login("ada@example.com")
    s, r, _ = req("POST", "/splits", {"amount": 999, "participant_handles": ["ada", "bob", "cy"]},
                   auth_headers(t_ada, uuid.uuid4().hex))
    shares = [sh["amount"] for sh in r.get("shares", [])]
    record("rounding", "split_999_among_3", shares == [333, 333, 333], f"shares={shares}")

    # Split 3000 among 3 → 1000, 1000, 1000
    reset_fixture()
    _, t_ada = login("ada@example.com")
    s, r, _ = req("POST", "/splits", {"amount": 3000, "participant_handles": ["ada", "bob", "cy"]},
                   auth_headers(t_ada, uuid.uuid4().hex))
    shares = [sh["amount"] for sh in r.get("shares", [])]
    record("rounding", "split_3000_among_3", shares == [1000, 1000, 1000], f"shares={shares}")

    # Split 7 among 1 → 7
    reset_fixture()
    _, t_ada = login("ada@example.com")
    s, r, _ = req("POST", "/splits", {"amount": 7, "participant_handles": ["ada"]},
                   auth_headers(t_ada, uuid.uuid4().hex))
    shares = [sh["amount"] for sh in r.get("shares", [])]
    record("rounding", "split_7_among_1", shares == [7], f"shares={shares}")

    # Split 1e9 among 7
    reset_fixture()
    _, t_ada = login("ada@example.com")
    s, r, _ = req("POST", "/splits", {"amount": 1_000_000_000, "participant_handles": ["ada", "bob", "cy"]},
                   auth_headers(t_ada, uuid.uuid4().hex))
    shares = [sh["amount"] for sh in r.get("shares", [])]
    expected = [333333334, 333333333, 333333333]
    record("rounding", "split_1e9_among_3", shares == expected, f"shares={shares}")

    # Repeated resets and splits (try to reproduce the lead)
    for trial in range(20):
        reset_fixture(users=users5)
        _, t_ada = login("ada@example.com")
        s, r, _ = req("POST", "/splits", {"amount": 5, "participant_handles": ["ada", "bob", "cy", "dan", "eve"]},
                       auth_headers(t_ada, uuid.uuid4().hex))
        shares = [sh["amount"] for sh in r.get("shares", [])]
        if shares != [1, 1, 1, 1, 1]:
            record("rounding", f"lead_trial_{trial}", False, f"shares={shares}")
            return
    record("rounding", "lead_20_trials", True, "all 20 trials correct")

    # Concurrent splits with same amount
    reset_fixture(users=users5)
    _, t_ada = login("ada@example.com")
    with ThreadPoolExecutor(20) as pool:
        results = list(pool.map(lambda _: req("POST", "/splits",
            {"amount": 5, "participant_handles": ["ada", "bob", "cy", "dan", "eve"]},
            auth_headers(t_ada, uuid.uuid4().hex)), range(20)))
    successful = [r[1].get("shares", []) for r in results if r[0] == 201]
    all_correct = len(successful) == 20 and all([s["amount"] for s in r] == [1, 1, 1, 1, 1] for r in successful)
    record("rounding", "concurrent_splits", all_correct, f"all_correct={all_correct}")


if __name__ == "__main__":
    attack_rounding()
    from attack_common import summary
    ok = summary()
    exit(0 if ok else 1)
