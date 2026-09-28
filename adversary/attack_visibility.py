#!/usr/bin/env python3
"""Feed and request visibility attacks."""
from __future__ import annotations

import uuid
from attack_common import req, record, reset_fixture, login, auth_headers


def attack_visibility():
    print("\n=== VISIBILITY ATTACKS ===")

    # Private payment hidden from third party
    reset_fixture()
    _, t_ada = login("ada@example.com")
    _, t_bob = login("bob@example.com")
    _, t_cy = login("cy@example.com")
    req("POST", "/payments", {"to_handle": "bob", "amount": 100, "visibility": "private"},
        auth_headers(t_ada, uuid.uuid4().hex))
    _, r_ada, _ = req("GET", "/activity", headers=auth_headers(t_ada))
    _, r_bob, _ = req("GET", "/activity", headers=auth_headers(t_bob))
    _, r_cy, _ = req("GET", "/activity", headers=auth_headers(t_cy))
    ok = len(r_ada["payments"]) == 1 and len(r_bob["payments"]) == 1 and len(r_cy["payments"]) == 0
    record("visibility", "private_hidden", ok, f"ada={len(r_ada['payments'])}, bob={len(r_bob['payments'])}, cy={len(r_cy['payments'])}")

    # Public payment visible to all
    reset_fixture()
    _, t_ada = login("ada@example.com")
    _, t_bob = login("bob@example.com")
    _, t_cy = login("cy@example.com")
    req("POST", "/payments", {"to_handle": "bob", "amount": 100, "visibility": "public"},
        auth_headers(t_ada, uuid.uuid4().hex))
    _, r_ada, _ = req("GET", "/activity", headers=auth_headers(t_ada))
    _, r_bob, _ = req("GET", "/activity", headers=auth_headers(t_bob))
    _, r_cy, _ = req("GET", "/activity", headers=auth_headers(t_cy))
    ok = len(r_ada["payments"]) == 1 and len(r_bob["payments"]) == 1 and len(r_cy["payments"]) == 1
    record("visibility", "public_visible", ok, f"ada={len(r_ada['payments'])}, bob={len(r_bob['payments'])}, cy={len(r_cy['payments'])}")

    # Requests not in activity feed
    reset_fixture()
    _, t_ada = login("ada@example.com")
    _, t_bob = login("bob@example.com")
    req("POST", "/requests", {"payer_handle": "ada", "amount": 500, "note": "test"},
        auth_headers(t_bob, uuid.uuid4().hex))
    _, r, _ = req("GET", "/activity", headers=auth_headers(t_ada))
    record("visibility", "requests_not_in_feed", len(r["payments"]) == 0, f"count={len(r['payments'])}")

    # Request visibility - third party cannot see
    reset_fixture()
    _, t_ada = login("ada@example.com")
    _, t_bob = login("bob@example.com")
    _, t_cy = login("cy@example.com")
    req("POST", "/requests", {"payer_handle": "ada", "amount": 500, "note": "test"},
        auth_headers(t_bob, uuid.uuid4().hex))
    _, r_ada, _ = req("GET", "/requests", headers=auth_headers(t_ada))
    _, r_bob, _ = req("GET", "/requests", headers=auth_headers(t_bob))
    _, r_cy, _ = req("GET", "/requests", headers=auth_headers(t_cy))
    ok = len(r_ada["requests"]) == 1 and len(r_bob["requests"]) == 1 and len(r_cy["requests"]) == 0
    record("visibility", "request_hidden", ok, f"ada={len(r_ada['requests'])}, bob={len(r_bob['requests'])}, cy={len(r_cy['requests'])}")

    # Operator cannot see others' private payments
    reset_fixture(operators=["u_ada"])
    _, t_ada = login("ada@example.com")
    _, t_bob = login("bob@example.com")
    _, t_cy = login("cy@example.com")
    req("POST", "/payments", {"to_handle": "bob", "amount": 100, "visibility": "private"},
        auth_headers(t_cy, uuid.uuid4().hex))
    _, r_ada, _ = req("GET", "/activity", headers=auth_headers(t_ada))
    record("visibility", "operator_no_private", len(r_ada["payments"]) == 0, f"count={len(r_ada['payments'])}")


if __name__ == "__main__":
    attack_visibility()
    from attack_common import summary
    ok = summary()
    exit(0 if ok else 1)
