"""Black-box acceptance tests for WI-1.6 — requests lifecycle/listing."""

import re
import threading
from typing import Any

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
    request_post,
    requests_list,
    reset,
    running_container,
)


def is_rfc3339(ts: str) -> bool:
    return bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{2}:\d{2}", ts))


def request_fixture():
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
                "balance": 100,
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


def assert_request_shape(body: dict, requester_id: str, requester_handle: str,
                         payer_id: str, payer_handle: str, amount: int, note: str = ""):
    expected_keys = {
        "request_id",
        "requester_id",
        "requester_handle",
        "payer_id",
        "payer_handle",
        "amount",
        "currency",
        "note",
        "status",
        "payment_id",
        "created_at",
    }
    assert set(body.keys()) == expected_keys
    assert body["requester_id"] == requester_id
    assert body["requester_handle"] == requester_handle
    assert body["payer_id"] == payer_id
    assert body["payer_handle"] == payer_handle
    assert body["amount"] == amount
    assert body["currency"] == "EUR"
    assert body["note"] == note
    assert body["status"] == "pending"
    assert body["payment_id"] is None
    assert is_rfc3339(body["created_at"])


def request_ids(resp: requests.Response) -> list[str]:
    return [r["request_id"] for r in resp.json()["requests"]]


def assert_list_shape(resp: requests.Response):
    assert resp.status_code == 200
    assert_json_content_type(resp)
    body = resp.json()
    assert set(body.keys()) == {"requests", "has_more"}
    assert isinstance(body["requests"], list)
    assert isinstance(body["has_more"], bool)
    return body


class TestCreateRequest:
    """Criteria 1 and 2: basic request creation and validation."""

    def test_create_request(self):
        with running_container() as ctx:
            reset(ctx, request_fixture())
            tokens = login_all(ctx)
            r = request_post(ctx, tokens["bob"], "k1", {"payer_handle": "ada", "amount": 1200, "note": "taxi"})
            assert r.status_code == 201
            assert_json_content_type(r)
            assert_request_shape(r.json(), "u_bob", "bob", "u_ada", "ada", 1200, "taxi")
            assert me(ctx, tokens["ada"]).json()["balance"] == 100
            assert me(ctx, tokens["bob"]).json()["balance"] == 10000

    def test_default_note(self):
        with running_container() as ctx:
            reset(ctx, request_fixture())
            tokens = login_all(ctx)
            r = request_post(ctx, tokens["bob"], "k1", {"payer_handle": "ada", "amount": 100})
            assert r.status_code == 201
            assert r.json()["note"] == ""

    def test_invalid_amount(self):
        with running_container() as ctx:
            reset(ctx, request_fixture())
            token = login(ctx, "bob@example.com", "battery stapler")["token"]
            for bad in [0, -1, 1000000001, 1.5, "5", True, None, []]:
                r = request_post(ctx, token, f"k-{bad}", {"payer_handle": "ada", "amount": bad})
                assert r.status_code == 422, f"amount={bad!r} gave {r.status_code}"
                assert_error_envelope(r.json(), "validation_failed")

    def test_self_request(self):
        with running_container() as ctx:
            reset(ctx, request_fixture())
            token = login(ctx, "bob@example.com", "battery stapler")["token"]
            r = request_post(ctx, token, "k1", {"payer_handle": "bob", "amount": 100})
            assert r.status_code == 422
            assert_error_envelope(r.json(), "self_request")

    def test_unknown_payer_handle(self):
        with running_container() as ctx:
            reset(ctx, request_fixture())
            token = login(ctx, "bob@example.com", "battery stapler")["token"]
            for bad in ["nobody", "ADA", "@ada", ""]:
                r = request_post(ctx, token, f"k-{bad}", {"payer_handle": bad, "amount": 100})
                assert r.status_code == 404, f"payer_handle={bad!r} gave {r.status_code}"
                assert_error_envelope(r.json(), "not_found")

    def test_note_validation(self):
        with running_container() as ctx:
            reset(ctx, request_fixture())
            token = login(ctx, "bob@example.com", "battery stapler")["token"]
            r = request_post(ctx, token, "k1", {"payer_handle": "ada", "amount": 100, "note": "a" * 201})
            assert r.status_code == 422
            assert_error_envelope(r.json(), "validation_failed")
            for bad in [None, 5, []]:
                r = request_post(ctx, token, f"k-{bad}", {"payer_handle": "ada", "amount": 100, "note": bad})
                assert r.status_code == 422, f"note={bad!r} gave {r.status_code}"
                assert_error_envelope(r.json(), "validation_failed")

    def test_payer_handle_type(self):
        with running_container() as ctx:
            reset(ctx, request_fixture())
            token = login(ctx, "bob@example.com", "battery stapler")["token"]
            r = request_post(ctx, token, "k1", {"payer_handle": 7, "amount": 100})
            assert r.status_code == 400
            assert_error_envelope(r.json(), "malformed_request")

    def test_missing_amount(self):
        with running_container() as ctx:
            reset(ctx, request_fixture())
            token = login(ctx, "bob@example.com", "battery stapler")["token"]
            r = request_post(ctx, token, "k1", {"payer_handle": "ada"})
            assert r.status_code == 422
            assert_error_envelope(r.json(), "validation_failed")

    def test_missing_key(self):
        with running_container() as ctx:
            reset(ctx, request_fixture())
            token = login(ctx, "bob@example.com", "battery stapler")["token"]
            r = requests.post(
                f"{ctx['url']}/requests",
                json={"payer_handle": "ada", "amount": 100},
                headers={"Authorization": f"Bearer {token}"},
                timeout=REQUEST_TIMEOUT,
            )
            assert r.status_code == 400
            assert_error_envelope(r.json(), "missing_idempotency_key")


class TestRequestIdempotency:
    """Criterion 3: idempotency on POST /requests."""

    def test_replay_same_body(self):
        with running_container() as ctx:
            reset(ctx, request_fixture())
            token = login(ctx, "bob@example.com", "battery stapler")["token"]
            key = "shared"
            r1 = request_post(ctx, token, key, {"payer_handle": "ada", "amount": 1200, "note": "taxi"})
            assert r1.status_code == 201
            original = r1.json()
            r2 = request_post(ctx, token, key, {"payer_handle": "ada", "amount": 1200, "note": "taxi"})
            assert r2.status_code == 200
            assert r2.json() == original

    def test_different_body_same_key(self):
        with running_container() as ctx:
            reset(ctx, request_fixture())
            token = login(ctx, "bob@example.com", "battery stapler")["token"]
            key = "shared"
            r1 = request_post(ctx, token, key, {"payer_handle": "ada", "amount": 1200})
            assert r1.status_code == 201
            r2 = request_post(ctx, token, key, {"payer_handle": "ada", "amount": 1300})
            assert r2.status_code == 409
            assert_error_envelope(r2.json(), "idempotency_key_reuse")

    def test_same_key_independent_across_paths(self):
        with running_container() as ctx:
            reset(ctx, request_fixture())
            tokens = login_all(ctx)
            key = "cross-path"
            r_pay = pay(ctx, tokens["bob"], key, {"to_handle": "cy", "amount": 100})
            assert r_pay.status_code == 201
            r_req = request_post(ctx, tokens["bob"], key, {"payer_handle": "ada", "amount": 100})
            assert r_req.status_code == 201


class TestListRequests:
    """Criteria 4 and 6: GET /requests filters, status, and ordering."""

    def fixture_with_statuses(self):
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
                    "balance": 1000,
                },
                {
                    "id": "u_bob",
                    "email": "bob@example.com",
                    "password": "battery stapler",
                    "display_name": "Bob",
                    "handle": "bob",
                    "balance": 1000,
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
            "requests": [
                {
                    "id": "r_out_pending",
                    "requester_id": "u_ada",
                    "payer_id": "u_bob",
                    "amount": 100,
                    "status": "pending",
                    "created_at": "2025-01-01T12:00:00+00:00",
                },
                {
                    "id": "r_out_paid",
                    "requester_id": "u_ada",
                    "payer_id": "u_bob",
                    "amount": 200,
                    "status": "paid",
                    "created_at": "2025-01-02T12:00:00+00:00",
                },
                {
                    "id": "r_in_declined",
                    "requester_id": "u_bob",
                    "payer_id": "u_ada",
                    "amount": 300,
                    "status": "declined",
                    "created_at": "2025-01-03T12:00:00+00:00",
                },
                {
                    "id": "r_in_cancelled",
                    "requester_id": "u_bob",
                    "payer_id": "u_ada",
                    "amount": 400,
                    "status": "cancelled",
                    "created_at": "2025-01-04T12:00:00+00:00",
                },
                {
                    "id": "r_in_pending",
                    "requester_id": "u_bob",
                    "payer_id": "u_ada",
                    "amount": 50,
                    "status": "pending",
                    "created_at": "2025-01-05T12:00:00+00:00",
                },
            ],
        }

    def test_direction_filters(self):
        with running_container() as ctx:
            reset(ctx, self.fixture_with_statuses())
            tokens = login_all(ctx)
            ada_token = tokens["ada"]
            assert request_ids(requests_list(ctx, ada_token, {"direction": "incoming"})) == ["r_in_pending", "r_in_cancelled", "r_in_declined"]
            assert request_ids(requests_list(ctx, ada_token, {"direction": "outgoing"})) == ["r_out_paid", "r_out_pending"]
            assert request_ids(requests_list(ctx, ada_token)) == ["r_in_pending", "r_in_cancelled", "r_in_declined", "r_out_paid", "r_out_pending"]
            assert request_ids(requests_list(ctx, tokens["cy"])) == []

    def test_status_filter(self):
        with running_container() as ctx:
            reset(ctx, self.fixture_with_statuses())
            tokens = login_all(ctx)
            for status, expected in [
                ("pending", ["r_in_pending", "r_out_pending"]),
                ("paid", ["r_out_paid"]),
                ("declined", ["r_in_declined"]),
                ("cancelled", ["r_in_cancelled"]),
            ]:
                body = assert_list_shape(requests_list(ctx, tokens["ada"], {"status": status}))
                assert request_ids(requests_list(ctx, tokens["ada"], {"status": status})) == expected

    def test_direction_and_status_combined(self):
        with running_container() as ctx:
            reset(ctx, self.fixture_with_statuses())
            tokens = login_all(ctx)
            assert request_ids(requests_list(ctx, tokens["ada"], {"direction": "incoming", "status": "declined"})) == ["r_in_declined"]

    def test_newest_first_and_pagination(self):
        with running_container() as ctx:
            reset(ctx, self.fixture_with_statuses())
            tokens = login_all(ctx)
            page1 = requests_list(ctx, tokens["ada"], {"limit": "2", "offset": "0"}).json()
            assert [r["request_id"] for r in page1["requests"]] == ["r_in_pending", "r_in_cancelled"]
            assert page1["has_more"] is True
            page2 = requests_list(ctx, tokens["ada"], {"limit": "2", "offset": "2"}).json()
            assert [r["request_id"] for r in page2["requests"]] == ["r_in_declined", "r_out_paid"]
            assert page2["has_more"] is True
            page3 = requests_list(ctx, tokens["ada"], {"limit": "2", "offset": "4"}).json()
            assert [r["request_id"] for r in page3["requests"]] == ["r_out_pending"]
            assert page3["has_more"] is False


class TestListValidation:
    """Criterion 5: invalid list parameters."""

    def test_invalid_direction_status(self):
        with running_container() as ctx:
            reset(ctx, request_fixture())
            token = login(ctx, "bob@example.com", "battery stapler")["token"]
            for bad in ["sideways", "UP", ""]:
                r = requests_list(ctx, token, {"direction": bad})
                assert r.status_code == 422, f"direction={bad!r} gave {r.status_code}"
                assert_error_envelope(r.json(), "validation_failed")
            for bad in ["open", "PENDING", ""]:
                r = requests_list(ctx, token, {"status": bad})
                assert r.status_code == 422, f"status={bad!r} gave {r.status_code}"
                assert_error_envelope(r.json(), "validation_failed")

    def test_limit_offset_rules(self):
        with running_container() as ctx:
            reset(ctx, request_fixture())
            token = login(ctx, "bob@example.com", "battery stapler")["token"]
            for bad_limit in ["0", "201", "-1", "1e2", "4.0", "+4", "abc", ""]:
                r = requests_list(ctx, token, {"limit": bad_limit})
                assert r.status_code == 422, f"limit={bad_limit!r} gave {r.status_code}"
                assert_error_envelope(r.json(), "validation_failed")
            for bad_offset in ["-1", "1.0", "abc"]:
                r = requests_list(ctx, token, {"offset": bad_offset})
                assert r.status_code == 422, f"offset={bad_offset!r} gave {r.status_code}"
                assert_error_envelope(r.json(), "validation_failed")

    def test_unknown_parameter_ignored(self):
        with running_container() as ctx:
            reset(ctx, request_fixture())
            token = login(ctx, "bob@example.com", "battery stapler")["token"]
            r = requests_list(ctx, token, {"foo": "bar", "limit": "1"})
            assert_list_shape(r)


class TestAuth:
    """Criterion 5: no token."""

    def test_no_token(self):
        with running_container() as ctx:
            reset(ctx, request_fixture())
            r = requests.get(f"{ctx['url']}/requests", timeout=REQUEST_TIMEOUT)
            assert r.status_code == 401
            assert_error_envelope(r.json(), "unauthenticated")


class TestRequestsNotInActivity:
    """Criterion 7: requests never appear in GET /activity."""

    def test_requests_not_in_activity(self):
        with running_container() as ctx:
            reset(ctx, request_fixture())
            tokens = login_all(ctx)
            request_post(ctx, tokens["bob"], "k1", {"payer_handle": "ada", "amount": 1200, "note": "taxi"})
            for token in tokens.values():
                body = activity(ctx, token).json()
                assert all("request_id" not in p for p in body["payments"])
                assert all(p.get("from_user_id") or p.get("to_user_id") for p in body["payments"])


class TestConcurrentRequests:
    """Criterion 8: concurrent identical POST /requests with one key."""

    def test_concurrent_identical(self):
        with running_container() as ctx:
            reset(ctx, request_fixture())
            token = login(ctx, "bob@example.com", "battery stapler")["token"]
            body = {"payer_handle": "ada", "amount": 100}
            results, errors = [], []

            def do_post():
                try:
                    results.append(request_post(ctx, token, "same-key", body))
                except Exception as exc:
                    errors.append(exc)

            threads = [threading.Thread(target=do_post) for _ in range(20)]
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