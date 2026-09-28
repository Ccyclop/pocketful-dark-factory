"""Black-box acceptance tests for WI-1.5 — GET /activity feed."""

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
    reset,
    running_container,
)


def feed_fixture():
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
            {
                "id": "u_cy",
                "email": "cy@example.com",
                "password": "cy pass",
                "display_name": "Cy",
                "handle": "cy",
                "balance": 1000,
            },
        ],
        "payments": [
            {
                "id": "p_1",
                "from_user_id": "u_ada",
                "to_user_id": "u_bob",
                "amount": 500,
                "note": "seed public",
                "visibility": "public",
            },
            {
                "id": "p_2",
                "from_user_id": "u_ada",
                "to_user_id": "u_bob",
                "amount": 100,
                "note": "seed private",
                "visibility": "private",
            },
            {
                "id": "p_3",
                "from_user_id": "u_bob",
                "to_user_id": "u_cy",
                "amount": 200,
                "note": "bob to cy public",
                "visibility": "public",
            },
        ],
        "requests": [],
    }


def login_all(ctx: dict) -> dict[str, str]:
    return {
        "ada": login(ctx, "ada@example.com", "correct horse")["token"],
        "bob": login(ctx, "bob@example.com", "battery stapler")["token"],
        "cy": login(ctx, "cy@example.com", "cy pass")["token"],
    }


def payment_ids(resp) -> list[str]:
    return [p["payment_id"] for p in resp.json()["payments"]]


def assert_feed_shape(resp):
    assert resp.status_code == 200
    assert_json_content_type(resp)
    body = resp.json()
    assert set(body.keys()) == {"payments", "has_more"}
    assert isinstance(body["payments"], list)
    assert isinstance(body["has_more"], bool)
    return body


def assert_payment_item(item: dict):
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
    assert set(item.keys()) == expected_keys
    assert item["currency"] == "EUR"
    assert item["request_id"] is None
    assert item["settlement_id"] is None
    assert item["visibility"] in ("public", "private")


class TestFeedVisibility:
    """Criterion 1: visibility rules."""

    def test_visibility(self):
        with running_container() as ctx:
            reset(ctx, feed_fixture())
            tokens = login_all(ctx)
            r_ada = activity(ctx, tokens["ada"])
            body_ada = assert_feed_shape(r_ada)
            assert payment_ids(r_ada) == ["p_3", "p_2", "p_1"]
            r_bob = activity(ctx, tokens["bob"])
            assert payment_ids(r_bob) == ["p_3", "p_2", "p_1"]
            r_cy = activity(ctx, tokens["cy"])
            assert payment_ids(r_cy) == ["p_3", "p_1"]
            for item in body_ada["payments"]:
                assert_payment_item(item)


class TestPrivatePaymentVisibleToReceiver:
    """Criterion 2: receiver sees private payment with visibility private."""

    def test_private_to_receiver(self):
        with running_container() as ctx:
            reset(ctx, feed_fixture())
            tokens = login_all(ctx)
            for item in activity(ctx, tokens["bob"]).json()["payments"]:
                if item["payment_id"] == "p_2":
                    assert item["visibility"] == "private"
                    assert item["from_handle"] == "ada"
                    assert item["to_handle"] == "bob"
                    return
            raise AssertionError("private payment not found in bob's feed")


class TestPagination:
    """Criterion 3: limit and offset."""

    def test_pagination(self):
        with running_container() as ctx:
            fixture = {
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
                        "balance": 5000,
                    },
                ],
                "payments": [
                    {
                        "id": f"p_{i}",
                        "from_user_id": "u_ada",
                        "to_user_id": "u_bob",
                        "amount": 10,
                        "note": f"p{i}",
                        "visibility": "public",
                    }
                    for i in range(5)
                ],
                "requests": [],
            }
            reset(ctx, fixture)
            token = login(ctx, "ada@example.com", "correct horse")["token"]
            body = assert_feed_shape(activity(ctx, token, {"limit": "2", "offset": "0"}))
            assert len(body["payments"]) == 2
            assert body["has_more"] is True

            body = assert_feed_shape(activity(ctx, token, {"limit": "2", "offset": "4"}))
            assert len(body["payments"]) == 1
            assert body["has_more"] is False

            body = assert_feed_shape(activity(ctx, token, {"limit": "2", "offset": "5"}))
            assert body["payments"] == []
            assert body["has_more"] is False

            body = assert_feed_shape(activity(ctx, token))
            assert len(body["payments"]) == 5
            assert body["has_more"] is False

            body = assert_feed_shape(activity(ctx, token, {"limit": "200"}))
            assert len(body["payments"]) == 5
            assert body["has_more"] is False


class TestInvalidQueryParameters:
    """Criterion 4: malformed limit/offset and unknown params ignored."""

    def test_invalid_limit(self):
        with running_container() as ctx:
            reset(ctx, feed_fixture())
            token = login(ctx, "ada@example.com", "correct horse")["token"]
            for bad in ["0", "201", "-1", "1e2", "4.0", "+4", "abc", ""]:
                r = activity(ctx, token, {"limit": bad})
                assert r.status_code == 422, f"limit={bad!r} gave {r.status_code}"
                assert_error_envelope(r.json(), "validation_failed")

    def test_invalid_offset(self):
        with running_container() as ctx:
            reset(ctx, feed_fixture())
            token = login(ctx, "ada@example.com", "correct horse")["token"]
            for bad in ["-1", "1.0", "abc"]:
                r = activity(ctx, token, {"offset": bad})
                assert r.status_code == 422, f"offset={bad!r} gave {r.status_code}"
                assert_error_envelope(r.json(), "validation_failed")

    def test_unknown_parameter_ignored(self):
        with running_container() as ctx:
            reset(ctx, feed_fixture())
            token = login(ctx, "ada@example.com", "correct horse")["token"]
            r = activity(ctx, token, {"foo": "bar", "limit": "1"})
            assert_feed_shape(r)
            assert len(r.json()["payments"]) == 1


class TestAuth:
    """Criterion 5: bearer token required."""

    def test_no_token(self):
        with running_container() as ctx:
            reset(ctx, feed_fixture())
            r = requests.get(f"{ctx['url']}/activity", timeout=REQUEST_TIMEOUT)
            assert r.status_code == 401
            assert_error_envelope(r.json(), "unauthenticated")


class TestOrdering:
    """Criterion 6: newest first; later payment precedes earlier one."""

    def test_newest_first_by_api(self):
        with running_container() as ctx:
            reset(ctx, feed_fixture())
            tokens = login_all(ctx)
            r_a = pay(ctx, tokens["ada"], "pay-a", {"to_handle": "bob", "amount": 1, "note": "A"})
            r_b = pay(ctx, tokens["bob"], "pay-b", {"to_handle": "cy", "amount": 2, "note": "B"})
            a_id = r_a.json()["payment_id"]
            b_id = r_b.json()["payment_id"]
            ids = payment_ids(activity(ctx, tokens["cy"]))
            assert ids.index(b_id) < ids.index(a_id)

    def test_api_payments_newest_first(self):
        with running_container() as ctx:
            fixture = {
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
                        "balance": 5000,
                    },
                ],
                "payments": [],
                "requests": [],
            }
            reset(ctx, fixture)
            ada_token = login(ctx, "ada@example.com", "correct horse")["token"]
            bob_token = login(ctx, "bob@example.com", "battery stapler")["token"]
            r_a = pay(ctx, ada_token, "pay-a", {"to_handle": "bob", "amount": 1, "note": "A"})
            r_b = pay(ctx, ada_token, "pay-b", {"to_handle": "bob", "amount": 2, "note": "B"})
            a_id = r_a.json()["payment_id"]
            b_id = r_b.json()["payment_id"]
            ids = payment_ids(activity(ctx, bob_token))
            assert ids == [b_id, a_id]


class TestSeededOrdering:
    """Seeded payments appear newest first; ties broken by later fixture order."""

    def test_seeded_newest_first(self):
        with running_container() as ctx:
            fixture = {
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
                        "balance": 5000,
                    },
                ],
                "payments": [
                    {
                        "id": "p_old",
                        "from_user_id": "u_ada",
                        "to_user_id": "u_bob",
                        "amount": 1,
                        "created_at": "2020-01-01T00:00:00+00:00",
                        "visibility": "public",
                    },
                    {
                        "id": "p_new",
                        "from_user_id": "u_ada",
                        "to_user_id": "u_bob",
                        "amount": 2,
                        "created_at": "2025-01-01T00:00:00+00:00",
                        "visibility": "public",
                    },
                ],
                "requests": [],
            }
            reset(ctx, fixture)
            token = login(ctx, "ada@example.com", "correct horse")["token"]
            assert payment_ids(activity(ctx, token)) == ["p_new", "p_old"]

    def test_seeded_tie_breaker(self):
        with running_container() as ctx:
            fixture = {
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
                        "balance": 5000,
                    },
                ],
                "payments": [
                    {
                        "id": "p_first",
                        "from_user_id": "u_ada",
                        "to_user_id": "u_bob",
                        "amount": 1,
                        "created_at": "2020-01-01T00:00:00+00:00",
                        "visibility": "public",
                    },
                    {
                        "id": "p_second",
                        "from_user_id": "u_ada",
                        "to_user_id": "u_bob",
                        "amount": 2,
                        "created_at": "2020-01-01T00:00:00+00:00",
                        "visibility": "public",
                    },
                ],
                "requests": [],
            }
            reset(ctx, fixture)
            token = login(ctx, "ada@example.com", "correct horse")["token"]
            assert payment_ids(activity(ctx, token)) == ["p_second", "p_first"]