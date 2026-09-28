#!/usr/bin/env python3
"""Repetition attacks: replays, changed bodies, replays after failures."""
from __future__ import annotations

import uuid

from attack_common import req, record, reset_fixture, login, auth_headers


def attack_repetition():
    print("\n=== REPETITION ATTACKS ===")

    # 2a. Sequential replay returns 200 with identical body
    reset_fixture()
    _, token = login("ada@example.com")
    k = uuid.uuid4().hex
    s1, r1, _ = req("POST", "/payments", {"to_handle": "bob", "amount": 1500, "note": "n"},
                     auth_headers(token, k))
    s2, r2, _ = req("POST", "/payments", {"to_handle": "bob", "amount": 1500, "note": "n"},
                     auth_headers(token, k))
    passed = s1 == 201 and s2 == 200 and r1 == r2
    record("repetition", "sequential_replay_200_identical", passed, f"{s1}->{s2}")

    # 2b. Replay with changed body → 409
    reset_fixture()
    _, token = login("ada@example.com")
    k = uuid.uuid4().hex
    req("POST", "/payments", {"to_handle": "bob", "amount": 1500, "note": "n"},
        auth_headers(token, k))
    s, r, _ = req("POST", "/payments", {"to_handle": "bob", "amount": 1501, "note": "n"},
                   auth_headers(token, k))
    passed = s == 409 and r.get("error", {}).get("code") == "idempotency_key_reuse"
    record("repetition", "changed_body_409", passed, f"status={s}")

    # 2c. Replay after 4xx failure → key reusable
    reset_fixture()
    _, token = login("cy@example.com")
    k = uuid.uuid4().hex
    s1, _, _ = req("POST", "/payments", {"to_handle": "bob", "amount": 1000},
                    auth_headers(token, k))
    # Give cy more money so the retry can succeed
    _, t_ada = login("ada@example.com")
    req("POST", "/payments", {"to_handle": "cy", "amount": 600},
        auth_headers(t_ada, uuid.uuid4().hex))
    s2, _, _ = req("POST", "/payments", {"to_handle": "bob", "amount": 1000},
                    auth_headers(token, k))
    passed = s1 == 409 and s2 == 201
    record("repetition", "failed_key_reusable", passed, f"{s1}->{s2}")

    # 2d. Replay after state change (reset) → key reusable
    reset_fixture()
    _, token = login("ada@example.com")
    k = uuid.uuid4().hex
    req("POST", "/payments", {"to_handle": "bob", "amount": 1}, auth_headers(token, k))
    reset_fixture()
    _, token = login("ada@example.com")
    s, _, _ = req("POST", "/payments", {"to_handle": "bob", "amount": 1}, auth_headers(token, k))
    passed = s == 201
    record("repetition", "replay_after_reset_reusable", passed, f"status={s}")

    # 2e. Replay after export/import → 200 with original body
    reset_fixture()
    _, token = login("ada@example.com")
    k = uuid.uuid4().hex
    s1, r1, _ = req("POST", "/payments", {"to_handle": "bob", "amount": 1500, "note": "n"},
                     auth_headers(token, k))
    _, export, _ = req("GET", "/_test/export")
    reset_fixture()
    req("POST", "/_test/import", export)
    _, token = login("ada@example.com")
    s2, r2, _ = req("POST", "/payments", {"to_handle": "bob", "amount": 1500, "note": "n"},
                     auth_headers(token, k))
    passed = s1 == 201 and s2 == 200 and r1 == r2
    record("repetition", "replay_after_import_200", passed, f"{s1}->{s2}")

    # 2f. Same key, different path → independent
    reset_fixture()
    _, token = login("ada@example.com")
    k = uuid.uuid4().hex
    s1, _, _ = req("POST", "/payments", {"to_handle": "bob", "amount": 100}, auth_headers(token, k))
    s2, _, _ = req("POST", "/requests", {"payer_handle": "bob", "amount": 100}, auth_headers(token, k))
    passed = s1 == 201 and s2 == 201
    record("repetition", "same_key_different_path_independent", passed, f"{s1},{s2}")

    # 2g. Same key, different user → independent
    reset_fixture()
    _, t_ada = login("ada@example.com")
    _, t_bob = login("bob@example.com")
    k = uuid.uuid4().hex
    s1, _, _ = req("POST", "/payments", {"to_handle": "cy", "amount": 10}, auth_headers(t_ada, k))
    s2, _, _ = req("POST", "/payments", {"to_handle": "cy", "amount": 10}, auth_headers(t_bob, k))
    passed = s1 == 201 and s2 == 201
    record("repetition", "same_key_different_user_independent", passed, f"{s1},{s2}")

    # 2h. Replay of pay after request already paid → 200, no double payment
    reset_fixture()
    _, t_ada = login("ada@example.com")
    _, t_bob = login("bob@example.com")
    req("POST", "/requests", {"payer_handle": "ada", "amount": 500, "note": "test"},
        auth_headers(t_bob, uuid.uuid4().hex))
    _, resp, _ = req("GET", "/requests?direction=incoming", headers=auth_headers(t_ada))
    rq_id = resp["requests"][0]["request_id"]
    k = uuid.uuid4().hex
    s1, r1, _ = req("POST", f"/requests/{rq_id}/pay", {}, auth_headers(t_ada, k))
    s2, r2, _ = req("POST", f"/requests/{rq_id}/pay", {}, auth_headers(t_ada, k))
    passed = s1 == 201 and s2 == 200 and r1 == r2
    record("repetition", "pay_replay_after_paid_200", passed, f"{s1}->{s2}")

    # 2i. Replay with different body on pay → 409
    reset_fixture()
    _, t_ada = login("ada@example.com")
    _, t_bob = login("bob@example.com")
    req("POST", "/requests", {"payer_handle": "ada", "amount": 500, "note": "test"},
        auth_headers(t_bob, uuid.uuid4().hex))
    _, resp, _ = req("GET", "/requests?direction=incoming", headers=auth_headers(t_ada))
    rq_id = resp["requests"][0]["request_id"]
    k = uuid.uuid4().hex
    req("POST", f"/requests/{rq_id}/pay", {}, auth_headers(t_ada, k))
    s, _, _ = req("POST", f"/requests/{rq_id}/pay", {"visibility": "private"}, auth_headers(t_ada, k))
    passed = s == 409
    record("repetition", "pay_replay_different_body_409", passed, f"status={s}")

    # 2j. Replay with equivalent body (different key order, 15e2 vs 1500) → 200
    reset_fixture()
    _, token = login("ada@example.com")
    k = uuid.uuid4().hex
    s1, r1, _ = req("POST", "/payments", {"to_handle": "bob", "amount": 1500, "note": "n"},
                     auth_headers(token, k))
    s2, r2, _ = req("POST", "/payments", raw=b'{"amount":15e2,"note":"n","to_handle":"bob"}',
                     headers=auth_headers(token, k))
    passed = s1 == 201 and s2 == 200 and r1 == r2
    record("repetition", "equivalent_body_replay_200", passed, f"{s1}->{s2}")

    # 2k. Replay of decline → 200
    reset_fixture()
    _, t_ada = login("ada@example.com")
    _, t_bob = login("bob@example.com")
    req("POST", "/requests", {"payer_handle": "ada", "amount": 500, "note": "test"},
        auth_headers(t_bob, uuid.uuid4().hex))
    _, resp, _ = req("GET", "/requests?direction=incoming", headers=auth_headers(t_ada))
    rq_id = resp["requests"][0]["request_id"]
    s1, r1, _ = req("POST", f"/requests/{rq_id}/decline", headers=auth_headers(t_ada))
    s2, r2, _ = req("POST", f"/requests/{rq_id}/decline", headers=auth_headers(t_ada))
    passed = s1 == 200 and s2 == 200 and r1 == r2
    record("repetition", "decline_replay_200", passed, f"{s1}->{s2}")

    # 2l. Replay of cancel → 200
    reset_fixture()
    _, t_ada = login("ada@example.com")
    _, t_bob = login("bob@example.com")
    req("POST", "/requests", {"payer_handle": "ada", "amount": 500, "note": "test"},
        auth_headers(t_bob, uuid.uuid4().hex))
    _, resp, _ = req("GET", "/requests?direction=incoming", headers=auth_headers(t_ada))
    rq_id = resp["requests"][0]["request_id"]
    s1, r1, _ = req("POST", f"/requests/{rq_id}/cancel", headers=auth_headers(t_bob))
    s2, r2, _ = req("POST", f"/requests/{rq_id}/cancel", headers=auth_headers(t_bob))
    passed = s1 == 200 and s2 == 200 and r1 == r2
    record("repetition", "cancel_replay_200", passed, f"{s1}->{s2}")


if __name__ == "__main__":
    attack_repetition()
    from attack_common import summary
    ok = summary()
    exit(0 if ok else 1)
