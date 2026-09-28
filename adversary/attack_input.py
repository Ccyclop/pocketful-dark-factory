#!/usr/bin/env python3
"""Input attacks: malformed, missing, wrong-type, boundary values."""
from __future__ import annotations

import uuid
from attack_common import req, record, reset_fixture, login, auth_headers


def attack_input():
    print("\n=== INPUT ATTACKS ===")
    reset_fixture()
    _, token = login("ada@example.com")

    # Malformed JSON
    for raw in [b"{nope", b"", b"[]", b"null", b"123", b'"str"']:
        s, r, _ = req("POST", "/payments", raw=raw, headers=auth_headers(token, uuid.uuid4().hex))
        record("input", f"malformed_{raw[:8]!r}", s == 400, f"status={s}")

    # Amount edge values
    for amt in [0, -1, 1_000_000_001, 1.5, "10", True, None, [], {}, 1e-3, 1e3, 1000.0,
                1000000000.0000001, -0]:
        s, r, _ = req("POST", "/payments", {"to_handle": "bob", "amount": amt},
                       auth_headers(token, uuid.uuid4().hex))
        if amt in (1e3, 1000.0):
            ok = s == 201
        else:
            ok = s == 422
        record("input", f"amount_{amt!r}", ok, f"status={s}")
    # 1e309 as raw JSON is parsed as Decimal('1E+309'), finite but > 2^64 -> 422 per D4
    s, _, _ = req("POST", "/payments", raw=b'{"to_handle":"bob","amount":1e309}',
                   headers=auth_headers(token, uuid.uuid4().hex))
    record("input", "amount_1e309", s == 422, f"status={s}")

    # Note edge values
    s, _, _ = req("POST", "/payments", {"to_handle": "bob", "amount": 1, "note": "x" * 200},
                   auth_headers(token, uuid.uuid4().hex))
    record("input", "note_200_ok", s == 201, f"status={s}")
    s, _, _ = req("POST", "/payments", {"to_handle": "bob", "amount": 1, "note": "x" * 201},
                   auth_headers(token, uuid.uuid4().hex))
    record("input", "note_201_422", s == 422, f"status={s}")
    note = "héllo 👋🏽\n<b>&amp;"
    s, r, _ = req("POST", "/payments", {"to_handle": "bob", "amount": 1, "note": note},
                   auth_headers(token, uuid.uuid4().hex))
    record("input", "note_unicode", s == 201 and r.get("note") == note, f"status={s}")

    # Visibility edge values
    for vis in ["PUBLIC", None, 1, "public", "private", ""]:
        s, _, _ = req("POST", "/payments", {"to_handle": "bob", "amount": 1, "visibility": vis},
                       auth_headers(token, uuid.uuid4().hex))
        ok = s == 201 if vis in ("public", "private") else s == 422
        record("input", f"vis_{vis!r}", ok, f"status={s}")

    # Query parameter forms
    for qp in ["limit=1e9", "limit=4.0", "limit=+4", "limit=", "limit=0", "limit=201",
               "offset=-1", "offset=abc", "direction=sideways", "status=unknown"]:
        s, _, _ = req("GET", f"/requests?{qp}", headers=auth_headers(token))
        record("input", f"qp_{qp}", s == 422, f"status={s}")

    # Idempotency key edge values
    s, _, _ = req("POST", "/payments", {"to_handle": "bob", "amount": 1},
                   headers={"Authorization": f"Bearer {token}"})
    record("input", "idem_missing", s == 400, f"status={s}")
    s, _, _ = req("POST", "/payments", {"to_handle": "bob", "amount": 1},
                   headers={"Authorization": f"Bearer {token}", "Idempotency-Key": ""})
    record("input", "idem_empty", s == 400, f"status={s}")
    s, _, _ = req("POST", "/payments", {"to_handle": "bob", "amount": 1},
                   headers={"Authorization": f"Bearer {token}", "Idempotency-Key": "k" * 255})
    record("input", "idem_255_ok", s == 201, f"status={s}")
    s, _, _ = req("POST", "/payments", {"to_handle": "bob", "amount": 1},
                   headers={"Authorization": f"Bearer {token}", "Idempotency-Key": "k" * 256})
    record("input", "idem_256_422", s == 422, f"status={s}")

    # No 5xx on any input
    all_codes = set()
    for raw in [b"{nope", b"", b"[]", b"null", b"123", b'"str"',
                b'{"to_handle":"bob","amount":1e309}',
                b'{"to_handle":"bob","amount":-1e309}']:
        s, _, _ = req("POST", "/payments", raw=raw, headers=auth_headers(token, uuid.uuid4().hex))
        all_codes.add(s)
    record("input", "no_5xx", all_codes <= {400, 401, 403, 404, 409, 422}, f"codes={sorted(all_codes)}")


if __name__ == "__main__":
    attack_input()
    from attack_common import summary
    ok = summary()
    exit(0 if ok else 1)
