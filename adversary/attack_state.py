#!/usr/bin/env python3
"""State attacks: operations on non-existent, consumed, or removed resources."""
from __future__ import annotations

import uuid
from attack_common import req, record, reset_fixture, login, auth_headers


def attack_state():
    print("\n=== STATE ATTACKS ===")

    # Pay non-existent request
    reset_fixture()
    _, token = login("ada@example.com")
    s, r, _ = req("POST", "/requests/rq_nonexistent/pay", {}, auth_headers(token, uuid.uuid4().hex))
    record("state", "pay_nonexistent_404", s == 404, f"status={s}")

    # Decline non-existent request
    s, _, _ = req("POST", "/requests/rq_nonexistent/decline", headers=auth_headers(token))
    record("state", "decline_nonexistent_404", s == 404, f"status={s}")

    # Cancel non-existent request
    s, _, _ = req("POST", "/requests/rq_nonexistent/cancel", headers=auth_headers(token))
    record("state", "cancel_nonexistent_404", s == 404, f"status={s}")

    # Pay already-paid request → 409
    reset_fixture()
    _, t_ada = login("ada@example.com")
    _, t_bob = login("bob@example.com")
    req("POST", "/requests", {"payer_handle": "ada", "amount": 500, "note": "test"},
        auth_headers(t_bob, uuid.uuid4().hex))
    _, resp, _ = req("GET", "/requests?direction=incoming", headers=auth_headers(t_ada))
    rq_id = resp["requests"][0]["request_id"]
    req("POST", f"/requests/{rq_id}/pay", {}, auth_headers(t_ada, uuid.uuid4().hex))
    s, _, _ = req("POST", f"/requests/{rq_id}/pay", {}, auth_headers(t_ada, uuid.uuid4().hex))
    record("state", "pay_already_paid_409", s == 409, f"status={s}")

    # Decline already-declined → 200
    reset_fixture()
    _, t_ada = login("ada@example.com")
    _, t_bob = login("bob@example.com")
    req("POST", "/requests", {"payer_handle": "ada", "amount": 500, "note": "test"},
        auth_headers(t_bob, uuid.uuid4().hex))
    _, resp, _ = req("GET", "/requests?direction=incoming", headers=auth_headers(t_ada))
    rq_id = resp["requests"][0]["request_id"]
    req("POST", f"/requests/{rq_id}/decline", headers=auth_headers(t_ada))
    s, r, _ = req("POST", f"/requests/{rq_id}/decline", headers=auth_headers(t_ada))
    record("state", "decline_already_200", s == 200 and r.get("status") == "declined", f"status={s}")

    # Decline paid request → 409
    reset_fixture()
    _, t_ada = login("ada@example.com")
    _, t_bob = login("bob@example.com")
    req("POST", "/requests", {"payer_handle": "ada", "amount": 500, "note": "test"},
        auth_headers(t_bob, uuid.uuid4().hex))
    _, resp, _ = req("GET", "/requests?direction=incoming", headers=auth_headers(t_ada))
    rq_id = resp["requests"][0]["request_id"]
    req("POST", f"/requests/{rq_id}/pay", {}, auth_headers(t_ada, uuid.uuid4().hex))
    s, _, _ = req("POST", f"/requests/{rq_id}/decline", headers=auth_headers(t_ada))
    record("state", "decline_paid_409", s == 409, f"status={s}")

    # Third party pay → 403
    reset_fixture()
    _, t_ada = login("ada@example.com")
    _, t_bob = login("bob@example.com")
    _, t_cy = login("cy@example.com")
    req("POST", "/requests", {"payer_handle": "ada", "amount": 500, "note": "test"},
        auth_headers(t_bob, uuid.uuid4().hex))
    _, resp, _ = req("GET", "/requests?direction=incoming", headers=auth_headers(t_ada))
    rq_id = resp["requests"][0]["request_id"]
    s, _, _ = req("POST", f"/requests/{rq_id}/pay", {}, auth_headers(t_cy, uuid.uuid4().hex))
    record("state", "third_party_pay_403", s == 403, f"status={s}")
    s, _, _ = req("POST", f"/requests/{rq_id}/decline", headers=auth_headers(t_cy))
    record("state", "third_party_decline_403", s == 403, f"status={s}")
    s, _, _ = req("POST", f"/requests/{rq_id}/cancel", headers=auth_headers(t_cy))
    record("state", "third_party_cancel_403", s == 403, f"status={s}")

    # Requester tries to pay → 403
    s, _, _ = req("POST", f"/requests/{rq_id}/pay", {}, auth_headers(t_bob, uuid.uuid4().hex))
    record("state", "requester_pay_403", s == 403, f"status={s}")

    # Payer tries to cancel → 403
    s, _, _ = req("POST", f"/requests/{rq_id}/cancel", headers=auth_headers(t_ada))
    record("state", "payer_cancel_403", s == 403, f"status={s}")

    # Requester tries to decline → 403
    s, _, _ = req("POST", f"/requests/{rq_id}/decline", headers=auth_headers(t_bob))
    record("state", "requester_decline_403", s == 403, f"status={s}")

    # Long sequence conserves money
    reset_fixture()
    _, t_ada = login("ada@example.com")
    _, t_bob = login("bob@example.com")
    _, t_cy = login("cy@example.com")
    tokens = [t_ada, t_bob, t_cy]
    handles = ["ada", "bob", "cy"]
    for i in range(100):
        src, dst = i % 3, (i + 1) % 3
        req("POST", "/payments", {"to_handle": handles[dst], "amount": (i % 100) + 1},
            auth_headers(tokens[src], uuid.uuid4().hex))
    total = 0
    for i, h in enumerate(handles):
        _, r, _ = req("GET", "/me", headers=auth_headers(tokens[i]))
        total += r["balance"]
    record("state", "long_sequence_conserves", total == 13000, f"total={total}")


if __name__ == "__main__":
    attack_state()
    from attack_common import summary
    ok = summary()
    exit(0 if ok else 1)
