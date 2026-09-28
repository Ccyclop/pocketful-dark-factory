"""Black-box acceptance tests for WI-1.7 — paying, declining and cancelling requests."""

import re
import threading

import pytest
import requests

from conftest import (
    REQUEST_TIMEOUT,
    activity,
    assert_error_envelope,
    assert_json_content_type,
    login,
    me,
    pay,
    request_cancel,
    request_decline,
    request_pay,
    request_post,
    requests_list,
    reset,
    running_container,
)


def is_rfc3339(ts: str) -> bool:
    return bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{2}:\d{2}", ts))


def action_fixture():
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
                "balance": 5000,
            },
            {
                "id": "u_bob",
                "email": "bob@example.com",
                "password": "battery stapler",
                "display_name": "Bob",
                "handle": "bob",
                "balance": 10000,
            },
            {
                "id": "u_cy",
                "email": "cy@example.com",
                "password": "cy pass",
                "display_name": "Cy",
                "handle": "cy",
                "balance": 1000,
            },
        ],
        "payments": [],
        "requests": [],
    }


def login_all(ctx: dict) -> dict[str, str]:
    return {
        "ada": login(ctx, "ada@example.com", "correct horse")["token"],
        "bob": login(ctx, "bob@example.com", "battery stapler")["token"],
        "cy": login(ctx, "cy@example.com", "cy pass")["token"],
    }


def create_request(ctx: dict, bob_token: str, amount: int = 1200) -> str:
    r = request_post(ctx, bob_token, "create-key", {"payer_handle": "ada", "amount": amount, "note": "taxi"})
    assert r.status_code == 201, f"create request failed: {r.status_code} {r.text}"
    return r.json()["request_id"]


def assert_payment_matches_request(payment: dict, request_id: str, note: str, visibility: str):
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
    assert set(payment.keys()) == expected_keys
    assert payment["from_user_id"] == "u_ada"
    assert payment["from_handle"] == "ada"
    assert payment["to_user_id"] == "u_bob"
    assert payment["to_handle"] == "bob"
    assert payment["amount"] == 1200
    assert payment["currency"] == "EUR"
    assert payment["note"] == note
    assert payment["visibility"] == visibility
    assert payment["request_id"] == request_id
    assert payment["settlement_id"] is None
    assert is_rfc3339(payment["created_at"])


class TestPayRequest:
    """Criteria 1 and 2: paying a request."""

    def test_pay_with_visibility(self):
        with running_container() as ctx:
            reset(ctx, action_fixture())
            tokens = login_all(ctx)
            rid = create_request(ctx, tokens["bob"])
            r = request_pay(ctx, tokens["ada"], rid, "pay-key", {"visibility": "private"})
            assert r.status_code == 201
            payment = r.json()
            assert_payment_matches_request(payment, rid, "taxi", "private")

            assert me(ctx, tokens["ada"]).json()["balance"] == 3800
            assert me(ctx, tokens["bob"]).json()["balance"] == 11200

            req = requests_list(ctx, tokens["bob"]).json()["requests"][0]
            assert req["status"] == "paid"
            assert req["payment_id"] == payment["payment_id"]

            for token in (tokens["ada"], tokens["bob"]):
                feed = activity(ctx, token).json()
                assert len(feed["payments"]) == 1
                assert feed["payments"][0]["payment_id"] == payment["payment_id"]
            cy_feed = activity(ctx, tokens["cy"]).json()
            assert cy_feed["payments"] == []

    def test_pay_default_visibility(self):
        with running_container() as ctx:
            reset(ctx, action_fixture())
            tokens = login_all(ctx)
            rid = create_request(ctx, tokens["bob"])
            r = request_pay(ctx, tokens["ada"], rid, "pay-key", {})
            assert r.status_code == 201
            assert r.json()["visibility"] == "public"

    def test_replay_same_body(self):
        with running_container() as ctx:
            reset(ctx, action_fixture())
            tokens = login_all(ctx)
            rid = create_request(ctx, tokens["bob"])
            r1 = request_pay(ctx, tokens["ada"], rid, "pay-key", {})
            assert r1.status_code == 201
            original = r1.json()
            r2 = request_pay(ctx, tokens["ada"], rid, "pay-key", {})
            assert r2.status_code == 200
            assert r2.json() == original
            assert me(ctx, tokens["ada"]).json()["balance"] == 3800

    def test_different_body_reuse(self):
        with running_container() as ctx:
            reset(ctx, action_fixture())
            tokens = login_all(ctx)
            rid = create_request(ctx, tokens["bob"])
            r1 = request_pay(ctx, tokens["ada"], rid, "pay-key", {})
            assert r1.status_code == 201
            r2 = request_pay(ctx, tokens["ada"], rid, "pay-key", {"visibility": "public"})
            assert r2.status_code == 409
            assert_error_envelope(r2.json(), "idempotency_key_reuse")


class TestPayPermissions:
    """Criterion 3: permission and state errors."""

    def test_pay_already_paid(self):
        with running_container() as ctx:
            reset(ctx, action_fixture())
            tokens = login_all(ctx)
            rid = create_request(ctx, tokens["bob"])
            assert request_pay(ctx, tokens["ada"], rid, "k1", {}).status_code == 201
            r = request_pay(ctx, tokens["ada"], rid, "k2", {})
            assert r.status_code == 409
            assert_error_envelope(r.json(), "request_not_pending")

    def test_pay_wrong_party(self):
        with running_container() as ctx:
            reset(ctx, action_fixture())
            tokens = login_all(ctx)
            rid = create_request(ctx, tokens["bob"])
            for token in (tokens["bob"], tokens["cy"]):
                r = request_pay(ctx, token, rid, "k1", {})
                assert r.status_code == 403, f"token gave {r.status_code}"
                assert_error_envelope(r.json(), "forbidden")

    def test_pay_unknown_request(self):
        with running_container() as ctx:
            reset(ctx, action_fixture())
            token = login(ctx, "ada@example.com", "correct horse")["token"]
            r = request_pay(ctx, token, "rq_noexists", "k1", {})
            assert r.status_code == 404
            assert_error_envelope(r.json(), "not_found")

    def test_pay_invalid_visibility(self):
        with running_container() as ctx:
            reset(ctx, action_fixture())
            tokens = login_all(ctx)
            rid = create_request(ctx, tokens["bob"])
            r = request_pay(ctx, tokens["ada"], rid, "k1", {"visibility": "x"})
            assert r.status_code == 422
            assert_error_envelope(r.json(), "validation_failed")


class TestInsufficientFunds:
    """Criterion 4: payer short, then funded, same key succeeds."""

    def test_insufficient_then_funded(self):
        with running_container() as ctx:
            reset(ctx, action_fixture())
            tokens = login_all(ctx)
            rid = create_request(ctx, tokens["bob"], amount=6000)
            r1 = request_pay(ctx, tokens["ada"], rid, "k1", {})
            assert r1.status_code == 409
            assert_error_envelope(r1.json(), "insufficient_funds")

            assert requests_list(ctx, tokens["bob"]).json()["requests"][0]["status"] == "pending"

            pay(ctx, tokens["bob"], "fund", {"to_handle": "ada", "amount": 6000})
            assert me(ctx, tokens["ada"]).json()["balance"] == 11000

            r2 = request_pay(ctx, tokens["ada"], rid, "k1", {})
            assert r2.status_code == 201
            assert r2.json()["amount"] == 6000
            assert me(ctx, tokens["ada"]).json()["balance"] == 5000


class TestDeclineCancel:
    """Criterion 5: decline and cancel."""

    def test_decline(self):
        with running_container() as ctx:
            reset(ctx, action_fixture())
            tokens = login_all(ctx)
            rid = create_request(ctx, tokens["bob"])
            r = request_decline(ctx, tokens["ada"], rid)
            assert r.status_code == 200
            body = r.json()
            assert body["status"] == "declined"
            r2 = request_decline(ctx, tokens["ada"], rid)
            assert r2.status_code == 200
            assert r2.json()["status"] == "declined"

    def test_decline_permission_and_state(self):
        with running_container() as ctx:
            reset(ctx, action_fixture())
            tokens = login_all(ctx)
            rid = create_request(ctx, tokens["bob"])
            for token in (tokens["bob"], tokens["cy"]):
                r = request_decline(ctx, token, rid)
                assert r.status_code == 403
                assert_error_envelope(r.json(), "forbidden")
            request_decline(ctx, tokens["ada"], rid)
            r = request_pay(ctx, tokens["ada"], rid, "k1", {})
            assert r.status_code == 409
            assert_error_envelope(r.json(), "request_not_pending")

    def test_cancel(self):
        with running_container() as ctx:
            reset(ctx, action_fixture())
            tokens = login_all(ctx)
            rid = create_request(ctx, tokens["bob"])
            r = request_cancel(ctx, tokens["bob"], rid)
            assert r.status_code == 200
            assert r.json()["status"] == "cancelled"
            r2 = request_cancel(ctx, tokens["bob"], rid)
            assert r2.status_code == 200
            assert r2.json()["status"] == "cancelled"

    def test_cancel_permission_and_state(self):
        with running_container() as ctx:
            reset(ctx, action_fixture())
            tokens = login_all(ctx)
            rid = create_request(ctx, tokens["bob"])
            for token in (tokens["ada"], tokens["cy"]):
                r = request_cancel(ctx, token, rid)
                assert r.status_code == 403
                assert_error_envelope(r.json(), "forbidden")
            request_pay(ctx, tokens["ada"], rid, "k1", {})
            r = request_cancel(ctx, tokens["bob"], rid)
            assert r.status_code == 409
            assert_error_envelope(r.json(), "request_not_pending")


class TestConcurrentPay:
    """Criterion 6: concurrent pays."""

    def test_concurrent_distinct_keys(self):
        with running_container() as ctx:
            reset(ctx, action_fixture())
            tokens = login_all(ctx)
            rid = create_request(ctx, tokens["bob"])
            results, errors = [], []

            def do_pay(i: int):
                try:
                    results.append(request_pay(ctx, tokens["ada"], rid, f"k-{i}", {}))
                except Exception as exc:
                    errors.append(exc)

            threads = [threading.Thread(target=do_pay, args=(i,)) for i in range(20)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            assert not errors
            statuses = [r.status_code for r in results]
            assert statuses.count(201) == 1
            assert statuses.count(409) == 19
            assert all(r.json()["error"]["code"] == "request_not_pending" for r in results if r.status_code == 409)

            req = requests_list(ctx, tokens["bob"]).json()["requests"][0]
            assert req["status"] == "paid"
            assert me(ctx, tokens["ada"]).json()["balance"] == 3800

    def test_concurrent_same_key(self):
        with running_container() as ctx:
            reset(ctx, action_fixture())
            tokens = login_all(ctx)
            rid = create_request(ctx, tokens["bob"])
            results, errors = [], []

            def do_pay():
                try:
                    results.append(request_pay(ctx, tokens["ada"], rid, "same-key", {}))
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

    def test_concurrent_pay_decline_cancel(self):
        with running_container() as ctx:
            reset(ctx, action_fixture())
            tokens = login_all(ctx)
            rid = create_request(ctx, tokens["bob"])
            results, errors = [], []

            def do_action(name: str, key: str):
                try:
                    if name == "pay":
                        results.append(request_pay(ctx, tokens["ada"], rid, key, {}))
                    elif name == "decline":
                        results.append(request_decline(ctx, tokens["ada"], rid))
                    else:
                        results.append(request_cancel(ctx, tokens["bob"], rid))
                except Exception as exc:
                    errors.append(exc)

            threads = [
                threading.Thread(target=do_action, args=("pay", f"pay-{i}"))
                for i in range(5)
            ] + [
                threading.Thread(target=do_action, args=("decline", "")),
                threading.Thread(target=do_action, args=("cancel", "")),
            ]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            assert not errors
            successes = [r for r in results if r.status_code in (200, 201)]
            assert len(successes) == 1
            req = requests_list(ctx, tokens["bob"]).json()["requests"][0]
            assert req["status"] in ("paid", "declined", "cancelled")
            if req["status"] == "paid":
                assert me(ctx, tokens["ada"]).json()["balance"] == 3800
            else:
                assert me(ctx, tokens["ada"]).json()["balance"] == 5000


class TestSeededStates:
    """Criterion 7: seeded paid/declined/cancelled behave per tables."""

    def fixture_with_seeded(self):
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
                    "balance": 5000,
                },
                {
                    "id": "u_bob",
                    "email": "bob@example.com",
                    "password": "battery stapler",
                    "display_name": "Bob",
                    "handle": "bob",
                    "balance": 5000,
                },
            ],
            "payments": [],
            "requests": [
                {
                    "id": "r_paid",
                    "requester_id": "u_bob",
                    "payer_id": "u_ada",
                    "amount": 100,
                    "status": "paid",
                },
                {
                    "id": "r_declined",
                    "requester_id": "u_bob",
                    "payer_id": "u_ada",
                    "amount": 200,
                    "status": "declined",
                },
                {
                    "id": "r_cancelled",
                    "requester_id": "u_bob",
                    "payer_id": "u_ada",
                    "amount": 300,
                    "status": "cancelled",
                },
            ],
        }

    def test_seeded_paid_pay_is_rejected(self):
        with running_container() as ctx:
            reset(ctx, self.fixture_with_seeded())
            token = login(ctx, "ada@example.com", "correct horse")["token"]
            r = request_pay(ctx, token, "r_paid", "k1", {})
            assert r.status_code == 409
            assert_error_envelope(r.json(), "request_not_pending")

    def test_seeded_declined_decline_again(self):
        with running_container() as ctx:
            reset(ctx, self.fixture_with_seeded())
            token = login(ctx, "ada@example.com", "correct horse")["token"]
            r = request_decline(ctx, token, "r_declined")
            assert r.status_code == 200
            assert r.json()["status"] == "declined"

    def test_seeded_cancelled_cancel_again(self):
        with running_container() as ctx:
            reset(ctx, self.fixture_with_seeded())
            token = login(ctx, "bob@example.com", "battery stapler")["token"]
            r = request_cancel(ctx, token, "r_cancelled")
            assert r.status_code == 200
            assert r.json()["status"] == "cancelled"

    def test_seeded_declined_pay_rejected(self):
        with running_container() as ctx:
            reset(ctx, self.fixture_with_seeded())
            token = login(ctx, "ada@example.com", "correct horse")["token"]
            r = request_pay(ctx, token, "r_declined", "k1", {})
            assert r.status_code == 409
            assert_error_envelope(r.json(), "request_not_pending")