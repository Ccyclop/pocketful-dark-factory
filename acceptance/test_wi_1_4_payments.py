"""Black-box acceptance tests for WI-1.4 — idempotency and POST /payments."""

import json
import re
import threading
import time
from typing import Any

import pytest
import requests

from conftest import (
    REQUEST_TIMEOUT,
    assert_error_envelope,
    assert_json_content_type,
    eur_fixture,
    login,
    me,
    pay,
    reset,
    running_container,
)


def two_user_fixture():
    return {
        "currency": "EUR",
        "minor_units": 2,
        "users": [
            {
                "id": "u_ada",
                "email": "ada@example.com",
                "password": "correct horse",
                "display_name": "Ada",
                "handle": "ada",
                "balance": 10000,
            },
            {
                "id": "u_bob",
                "email": "bob@example.com",
                "password": "battery stapler",
                "display_name": "Bob",
                "handle": "bob",
                "balance": 2500,
            },
        ],
        "payments": [],
        "requests": [],
    }


def ada_only_fixture(balance: int):
    return {
        "currency": "EUR",
        "minor_units": 2,
        "users": [
            {
                "id": "u_ada",
                "email": "ada@example.com",
                "password": "correct horse",
                "display_name": "Ada",
                "handle": "ada",
                "balance": balance,
            }
        ],
        "payments": [],
        "requests": [],
    }


def three_user_fixture():
    return {
        "currency": "EUR",
        "minor_units": 2,
        "users": [
            {
                "id": "u_ada",
                "email": "ada@example.com",
                "password": "correct horse",
                "display_name": "Ada",
                "handle": "ada",
                "balance": 3000,
            },
            {
                "id": "u_bob",
                "email": "bob@example.com",
                "password": "battery stapler",
                "display_name": "Bob",
                "handle": "bob",
                "balance": 3000,
            },
            {
                "id": "u_cy",
                "email": "cy@example.com",
                "password": "cy pass",
                "display_name": "Cy",
                "handle": "cy",
                "balance": 3000,
            },
        ],
        "payments": [],
        "requests": [],
    }


def is_rfc3339(ts: str) -> bool:
    return bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{2}:\d{2}", ts))


def assert_shape_and_payer(resp: requests.Response, amount: int, note: str, visibility: str):
    assert resp.status_code == 201
    assert_json_content_type(resp)
    body = resp.json()
    expected_keys = {
        "payment_id",
        "from_user_id",
        "from_handle",
        "to_user_id",
        "to_handle",
        "amount",
        "currency",
        "note",
        "visibility",
        "request_id",
        "settlement_id",
        "created_at",
    }
    assert set(body.keys()) == expected_keys
    assert body["from_user_id"] == "u_ada"
    assert body["from_handle"] == "ada"
    assert body["to_user_id"] == "u_bob"
    assert body["to_handle"] == "bob"
    assert body["amount"] == amount
    assert body["currency"] == "EUR"
    assert body["note"] == note
    assert body["visibility"] == visibility
    assert body["request_id"] is None
    assert body["settlement_id"] is None
    assert is_rfc3339(body["created_at"])
    return body


class TestBasicPayment:
    """Criterion 1: basic payment shape and balance update."""

    def test_pay(self):
        with running_container() as ctx:
            reset(ctx, two_user_fixture())
            token = login(ctx, "ada@example.com", "correct horse")["token"]
            r = pay(ctx, token, "k1", {"to_handle": "bob", "amount": 1500, "note": "dinner", "visibility": "public"})
            body = assert_shape_and_payer(r, 1500, "dinner", "public")
            assert body["payment_id"]

            assert me(ctx, token).json()["balance"] == 8500
            bob_token = login(ctx, "bob@example.com", "battery stapler")["token"]
            assert me(ctx, bob_token).json()["balance"] == 4000


class TestPaymentDefaultsAndNote:
    """Criterion 2: defaults and note handling."""

    def test_defaults(self):
        with running_container() as ctx:
            reset(ctx, two_user_fixture())
            token = login(ctx, "ada@example.com", "correct horse")["token"]
            r = pay(ctx, token, "k1", {"to_handle": "bob", "amount": 100})
            body = assert_shape_and_payer(r, 100, "", "public")

    def test_note_round_trip(self):
        with running_container() as ctx:
            reset(ctx, two_user_fixture())
            token = login(ctx, "ada@example.com", "correct horse")["token"]
            note = "  héllo 👋🏽\n<b>&amp;"
            r = pay(ctx, token, "k1", {"to_handle": "bob", "amount": 100, "note": note})
            assert r.json()["note"] == note

    def test_note_length(self):
        with running_container() as ctx:
            reset(ctx, two_user_fixture())
            token = login(ctx, "ada@example.com", "correct horse")["token"]
            r = pay(ctx, token, "k1", {"to_handle": "bob", "amount": 100, "note": "a" * 200})
            assert r.status_code == 201
            r2 = pay(ctx, token, "k2", {"to_handle": "bob", "amount": 100, "note": "a" * 201})
            assert r2.status_code == 422
            assert_error_envelope(r2.json(), "validation_failed")


class TestInvalidValues:
    """Criterion 3: invalid amount, visibility, note."""

    def test_invalid_amount(self):
        with running_container() as ctx:
            reset(ctx, two_user_fixture())
            token = login(ctx, "ada@example.com", "correct horse")["token"]
            for bad in [0, -1, 1000000001, 1.5, "10", True, None, []]:
                r = pay(ctx, token, f"k-{bad}", {"to_handle": "bob", "amount": bad})
                assert r.status_code == 422, f"amount={bad!r} gave {r.status_code}"
                assert_error_envelope(r.json(), "validation_failed")

    def test_equivalent_amounts(self):
        with running_container() as ctx:
            reset(ctx, two_user_fixture())
            token = login(ctx, "ada@example.com", "correct horse")["token"]
            for amount in [1000, 1000.0, "1e3"]:
                body = {"to_handle": "bob"}
                if isinstance(amount, str):
                    body = json.dumps({"to_handle": "bob", "amount": float(amount)})
                    r = requests.post(
                        f"{ctx['url']}/payments",
                        data=body,
                        headers={
                            "Content-Type": "application/json",
                            "Authorization": f"Bearer {token}",
                            "Idempotency-Key": f"k-{amount}",
                        },
                        timeout=REQUEST_TIMEOUT,
                    )
                else:
                    r = pay(ctx, token, f"k-{amount}", {"to_handle": "bob", "amount": amount})
                assert r.status_code == 201, f"amount={amount!r} gave {r.status_code}"
                assert r.json()["amount"] == 1000

    def test_invalid_visibility(self):
        with running_container() as ctx:
            reset(ctx, two_user_fixture())
            token = login(ctx, "ada@example.com", "correct horse")["token"]
            for bad in ["PUBLIC", None, 1, "secret"]:
                r = pay(ctx, token, f"k-{bad}", {"to_handle": "bob", "amount": 100, "visibility": bad})
                assert r.status_code == 422, f"visibility={bad!r} gave {r.status_code}"
                assert_error_envelope(r.json(), "validation_failed")

    def test_invalid_note_type(self):
        with running_container() as ctx:
            reset(ctx, two_user_fixture())
            token = login(ctx, "ada@example.com", "correct horse")["token"]
            for bad in [None, 5, []]:
                r = pay(ctx, token, f"k-{bad}", {"to_handle": "bob", "amount": 100, "note": bad})
                assert r.status_code == 422, f"note={bad!r} gave {r.status_code}"
                assert_error_envelope(r.json(), "validation_failed")


class TestRecipientErrors:
    """Criterion 4: self_payment, unknown handle, type errors, missing, parse errors."""

    def test_self_payment(self):
        with running_container() as ctx:
            reset(ctx, two_user_fixture())
            token = login(ctx, "ada@example.com", "correct horse")["token"]
            r = pay(ctx, token, "k1", {"to_handle": "ada", "amount": 100})
            assert r.status_code == 422
            assert_error_envelope(r.json(), "self_payment")

    def test_unknown_handle(self):
        with running_container() as ctx:
            reset(ctx, two_user_fixture())
            token = login(ctx, "ada@example.com", "correct horse")["token"]
            for bad in ["nobody", "ADA", "@ada", ""]:
                r = pay(ctx, token, f"k-{bad}", {"to_handle": bad, "amount": 100})
                assert r.status_code == 404, f"to_handle={bad!r} gave {r.status_code}"
                assert_error_envelope(r.json(), "not_found")

    def test_to_handle_wrong_type(self):
        with running_container() as ctx:
            reset(ctx, two_user_fixture())
            token = login(ctx, "ada@example.com", "correct horse")["token"]
            r = pay(ctx, token, "k1", {"to_handle": 5, "amount": 100})
            assert r.status_code == 400
            assert_error_envelope(r.json(), "malformed_request")

    def test_missing_to_handle(self):
        with running_container() as ctx:
            reset(ctx, two_user_fixture())
            token = login(ctx, "ada@example.com", "correct horse")["token"]
            r = pay(ctx, token, "k1", {"amount": 100})
            assert r.status_code == 422
            assert_error_envelope(r.json(), "validation_failed")

    def test_unparseable_body(self):
        with running_container() as ctx:
            reset(ctx, two_user_fixture())
            token = login(ctx, "ada@example.com", "correct horse")["token"]
            r = requests.post(
                f"{ctx['url']}/payments",
                data="not json",
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {token}",
                    "Idempotency-Key": "k1",
                },
                timeout=REQUEST_TIMEOUT,
            )
            assert r.status_code == 400
            assert_error_envelope(r.json(), "malformed_request")

    def test_body_not_object(self):
        with running_container() as ctx:
            reset(ctx, two_user_fixture())
            token = login(ctx, "ada@example.com", "correct horse")["token"]
            r = requests.post(
                f"{ctx['url']}/payments",
                json=[],
                headers={
                    "Authorization": f"Bearer {token}",
                    "Idempotency-Key": "k1",
                },
                timeout=REQUEST_TIMEOUT,
            )
            assert r.status_code == 400
            assert_error_envelope(r.json(), "malformed_request")


class TestFunds:
    """Criterion 5: insufficient funds and paying whole balance."""

    def test_insufficient_funds(self):
        with running_container() as ctx:
            reset(ctx, two_user_fixture())
            token = login(ctx, "ada@example.com", "correct horse")["token"]
            r = pay(ctx, token, "k1", {"to_handle": "bob", "amount": 10001})
            assert r.status_code == 409
            assert_error_envelope(r.json(), "insufficient_funds")
            assert me(ctx, token).json()["balance"] == 10000

    def test_exact_balance(self):
        with running_container() as ctx:
            reset(ctx, two_user_fixture())
            token = login(ctx, "ada@example.com", "correct horse")["token"]
            r = pay(ctx, token, "k1", {"to_handle": "bob", "amount": 10000})
            assert r.status_code == 201
            assert me(ctx, token).json()["balance"] == 0


class TestIdempotencyKeyValidation:
    """Criterion 6: idempotency-key header validation and auth order."""

    def test_missing_key(self):
        with running_container() as ctx:
            reset(ctx, two_user_fixture())
            token = login(ctx, "ada@example.com", "correct horse")["token"]
            r = requests.post(
                f"{ctx['url']}/payments",
                json={"to_handle": "bob", "amount": 100},
                headers={"Authorization": f"Bearer {token}"},
                timeout=REQUEST_TIMEOUT,
            )
            assert r.status_code == 400
            assert_error_envelope(r.json(), "missing_idempotency_key")

    def test_empty_key(self):
        with running_container() as ctx:
            reset(ctx, two_user_fixture())
            token = login(ctx, "ada@example.com", "correct horse")["token"]
            r = requests.post(
                f"{ctx['url']}/payments",
                json={"to_handle": "bob", "amount": 100},
                headers={"Authorization": f"Bearer {token}", "Idempotency-Key": ""},
                timeout=REQUEST_TIMEOUT,
            )
            assert r.status_code == 400
            assert_error_envelope(r.json(), "missing_idempotency_key")

    def test_key_length(self):
        with running_container() as ctx:
            reset(ctx, two_user_fixture())
            token = login(ctx, "ada@example.com", "correct horse")["token"]
            r = pay(ctx, token, "x" * 255, {"to_handle": "bob", "amount": 100})
            assert r.status_code == 201
            r2 = pay(ctx, token, "x" * 256, {"to_handle": "bob", "amount": 100})
            assert r2.status_code == 422
            assert_error_envelope(r2.json(), "validation_failed")

    def test_no_token(self):
        with running_container() as ctx:
            reset(ctx, two_user_fixture())
            r = requests.post(
                f"{ctx['url']}/payments",
                json={"to_handle": "bob", "amount": 100},
                headers={"Idempotency-Key": "k1"},
                timeout=REQUEST_TIMEOUT,
            )
            assert r.status_code == 401
            assert_error_envelope(r.json(), "unauthenticated")


class TestIdempotencyReplay:
    """Criterion 7: replay and reuse."""

    def test_replay_same_body_variations(self):
        with running_container() as ctx:
            reset(ctx, two_user_fixture())
            token = login(ctx, "ada@example.com", "correct horse")["token"]
            key = "shared-key"
            r1 = pay(ctx, token, key, {"to_handle": "bob", "amount": 1500, "note": "dinner", "visibility": "public"})
            assert r1.status_code == 201
            original = r1.json()

            variations = [
                json.dumps({"to_handle": "bob", "amount": 1500, "note": "dinner", "visibility": "public"}),
                json.dumps({"visibility": "public", "note": "dinner", "amount": 1500, "to_handle": "bob"}),
                '{"to_handle":"bob","amount":1500.0,"note":"dinner","visibility":"public"}',
                '{ "to_handle" : "bob" , "amount" : 1500 , "note" : "dinner" , "visibility" : "public" }',
            ]
            for body in variations:
                r = requests.post(
                    f"{ctx['url']}/payments",
                    data=body,
                    headers={
                        "Content-Type": "application/json",
                        "Authorization": f"Bearer {token}",
                        "Idempotency-Key": key,
                    },
                    timeout=REQUEST_TIMEOUT,
                )
                assert r.status_code == 200
                assert r.json() == original

            assert me(ctx, token).json()["balance"] == 8500
            bob_token = login(ctx, "bob@example.com", "battery stapler")["token"]
            assert me(ctx, bob_token).json()["balance"] == 4000

    def test_same_key_different_body(self):
        with running_container() as ctx:
            reset(ctx, two_user_fixture())
            token = login(ctx, "ada@example.com", "correct horse")["token"]
            key = "reuse-key"
            r1 = pay(ctx, token, key, {"to_handle": "bob", "amount": 100})
            assert r1.status_code == 201
            r2 = pay(ctx, token, key, {"to_handle": "bob", "amount": 200})
            assert r2.status_code == 409
            assert_error_envelope(r2.json(), "idempotency_key_reuse")

    def test_same_key_invalid_body_after_success(self):
        with running_container() as ctx:
            reset(ctx, two_user_fixture())
            token = login(ctx, "ada@example.com", "correct horse")["token"]
            key = "reuse-key"
            r1 = pay(ctx, token, key, {"to_handle": "bob", "amount": 100})
            assert r1.status_code == 201
            r2 = pay(ctx, token, key, {"to_handle": "bob", "amount": -5})
            assert r2.status_code == 409
            assert_error_envelope(r2.json(), "idempotency_key_reuse")


class TestIdempotencyAfterFailed:
    """Criterion 8: a key used in a failed request remains reusable."""

    def test_after_insufficient_funds(self):
        with running_container() as ctx:
            reset(ctx, two_user_fixture())
            token = login(ctx, "ada@example.com", "correct horse")["token"]
            key = "retry-key"
            r1 = pay(ctx, token, key, {"to_handle": "bob", "amount": 1000000})
            assert r1.status_code == 409
            r2 = pay(ctx, token, key, {"to_handle": "bob", "amount": 100})
            assert r2.status_code == 201

    def test_after_validation_error(self):
        with running_container() as ctx:
            reset(ctx, two_user_fixture())
            token = login(ctx, "ada@example.com", "correct horse")["token"]
            key = "retry-key"
            r1 = pay(ctx, token, key, {"to_handle": "bob", "amount": -1})
            assert r1.status_code == 422
            r2 = pay(ctx, token, key, {"to_handle": "bob", "amount": 100})
            assert r2.status_code == 201

    def test_after_not_found(self):
        with running_container() as ctx:
            reset(ctx, two_user_fixture())
            token = login(ctx, "ada@example.com", "correct horse")["token"]
            key = "retry-key"
            r1 = pay(ctx, token, key, {"to_handle": "nobody", "amount": 100})
            assert r1.status_code == 404
            r2 = pay(ctx, token, key, {"to_handle": "bob", "amount": 100})
            assert r2.status_code == 201


class TestKeyScope:
    """Criterion 9: key scoped to user."""

    def test_different_users_same_key(self):
        with running_container() as ctx:
            reset(ctx, two_user_fixture())
            ada_token = login(ctx, "ada@example.com", "correct horse")["token"]
            bob_token = login(ctx, "bob@example.com", "battery stapler")["token"]
            key = "same-key"
            r1 = pay(ctx, ada_token, key, {"to_handle": "bob", "amount": 100})
            assert r1.status_code == 201
            r2 = pay(ctx, bob_token, key, {"to_handle": "ada", "amount": 100})
            assert r2.status_code == 201


class TestConcurrentReplay:
    """Criterion 10: concurrent identical requests with one key."""

    def test_concurrent_identical(self):
        with running_container() as ctx:
            reset(ctx, two_user_fixture())
            token = login(ctx, "ada@example.com", "correct horse")["token"]
            results, errors = [], []
            body = {"to_handle": "bob", "amount": 100}

            def do_pay():
                try:
                    results.append(pay(ctx, token, "same-key", body))
                except Exception as exc:
                    errors.append(exc)

            threads = [threading.Thread(target=do_pay) for _ in range(20)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            assert not errors
            statuses = [r.status_code for r in results]
            assert statuses.count(201) == 1
            assert statuses.count(200) == 19
            body_201 = next(r.json() for r in results if r.status_code == 201)
            for r in results:
                assert r.json() == body_201
            assert me(ctx, token).json()["balance"] == 9900


class TestConcurrentPayments:
    """Criterion 11: concurrent payments preserve invariants."""

    def test_fifty_payments_exhaust_balance(self):
        with running_container() as ctx:
            reset(ctx, ada_only_fixture(1000))
            token = login(ctx, "ada@example.com", "correct horse")["token"]
            # need a recipient; signup one
            signup(ctx, "bob@example.com", "battery stapler", "Bob")
            bob_token = login(ctx, "bob@example.com", "battery stapler")["token"]
            bob_before = me(ctx, bob_token).json()["balance"]

            results, errors = [], []

            def do_pay(i: int):
                try:
                    results.append(pay(ctx, token, f"pay-{i}", {"to_handle": "bob", "amount": 100}))
                except Exception as exc:
                    errors.append(exc)

            start = time.monotonic()
            threads = [threading.Thread(target=do_pay, args=(i,)) for i in range(50)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
            elapsed = time.monotonic() - start
            assert elapsed <= REQUEST_TIMEOUT

            assert not errors
            assert len(results) == 50
            successes = [r for r in results if r.status_code == 201]
            failures = [r for r in results if r.status_code == 409]
            assert len(successes) == 10
            assert len(failures) == 40
            assert all(r.json()["error"]["code"] == "insufficient_funds" for r in failures)
            assert not any(r.status_code >= 500 for r in results)

            assert me(ctx, token).json()["balance"] == 0
            assert me(ctx, bob_token).json()["balance"] == bob_before + 1000

    def test_random_payments_keep_total(self):
        with running_container() as ctx:
            reset(ctx, three_user_fixture())
            tokens = {
                "ada": login(ctx, "ada@example.com", "correct horse")["token"],
                "bob": login(ctx, "bob@example.com", "battery stapler")["token"],
                "cy": login(ctx, "cy@example.com", "cy pass")["token"],
            }
            total = sum(me(ctx, tokens[h]).json()["balance"] for h in tokens)
            recipients = {"ada": "bob", "bob": "cy", "cy": "ada"}

            results, errors = [], []

            def do_pay(i: int):
                try:
                    sender = ["ada", "bob", "cy"][i % 3]
                    results.append(
                        pay(
                            ctx,
                            tokens[sender],
                            f"rand-{i}",
                            {"to_handle": recipients[sender], "amount": 10},
                        )
                    )
                except Exception as exc:
                    errors.append(exc)

            start = time.monotonic()
            threads = [threading.Thread(target=do_pay, args=(i,)) for i in range(50)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
            assert time.monotonic() - start <= REQUEST_TIMEOUT
            assert not errors
            assert not any(r.status_code >= 500 for r in results)

            new_total = sum(me(ctx, tokens[h]).json()["balance"] for h in tokens)
            assert new_total == total
            for h in tokens:
                assert me(ctx, tokens[h]).json()["balance"] >= 0


class TestExactArithmetic:
    """Criterion 12: exact arithmetic near 2^53."""

    def test_large_amounts(self):
        with running_container() as ctx:
            reset(
                ctx,
                {
                    "currency": "EUR",
                    "minor_units": 2,
                    "users": [
                        {
                            "id": "u_ada",
                            "email": "ada@example.com",
                            "password": "correct horse",
                            "display_name": "Ada",
                            "handle": "ada",
                            "balance": 9007199254740000,
                        },
                        {
                            "id": "u_bob",
                            "email": "bob@example.com",
                            "password": "battery stapler",
                            "display_name": "Bob",
                            "handle": "bob",
                            "balance": 0,
                        },
                    ],
                    "payments": [],
                    "requests": [],
                },
            )
            token = login(ctx, "ada@example.com", "correct horse")["token"]
            r = pay(ctx, token, "k1", {"to_handle": "bob", "amount": 1000000000})
            assert r.status_code == 201
            assert me(ctx, token).json()["balance"] == 9007198254740000
            bob_token = login(ctx, "bob@example.com", "battery stapler")["token"]
            assert me(ctx, bob_token).json()["balance"] == 1000000000