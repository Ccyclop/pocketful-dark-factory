"""Black-box acceptance tests for WI-1.9 — operator settlements."""

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
    request_post,
    requests_list,
    reset,
    running_container,
    settlement,
)


def is_rfc3339(ts: str) -> bool:
    return bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{2}:\d{2}", ts))


def settlement_fixture():
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
                "balance": 0,
            },
            {
                "id": "u_cy",
                "email": "cy@example.com",
                "password": "cy pass",
                "display_name": "Cy",
                "handle": "cy",
                "balance": 0,
            },
            {
                "id": "u_op",
                "email": "op@example.com",
                "password": "op secret",
                "display_name": "Op",
                "handle": "op",
                "balance": 0,
            },
        ],
        "payments": [],
        "requests": [],
        "settlement_operator_ids": ["u_op"],
    }


def login_all(ctx: dict) -> dict[str, str]:
    return {
        "ada": login(ctx, "ada@example.com", "correct horse")["token"],
        "bob": login(ctx, "bob@example.com", "battery stapler")["token"],
        "cy": login(ctx, "cy@example.com", "cy pass")["token"],
        "op": login(ctx, "op@example.com", "op secret")["token"],
    }


def assert_settlement_shape(body: dict, transfer_count: int):
    assert set(body.keys()) == {"settlement_id", "committed_at", "payments"}
    assert body["settlement_id"].startswith("set_")
    assert is_rfc3339(body["committed_at"])
    assert len(body["payments"]) == transfer_count
    for p in body["payments"]:
        assert p["settlement_id"] == body["settlement_id"]
        assert p["request_id"] is None
        assert p["created_at"] == body["committed_at"]
        assert p["currency"] == "EUR"
    return body


class TestBasicSettlement:
    """Criterion 1: basic settlement across wallets."""

    def test_settlement(self):
        with running_container() as ctx:
            reset(ctx, settlement_fixture())
            tokens = login_all(ctx)
            r = settlement(ctx, tokens["op"], "k1", {
                "transfers": [
                    {"from_handle": "ada", "to_handle": "bob", "amount": 100},
                    {"from_handle": "bob", "to_handle": "cy", "amount": 50},
                ]
            })
            assert r.status_code == 201
            assert_json_content_type(r)
            body = assert_settlement_shape(r.json(), 2)

            assert me(ctx, tokens["ada"]).json()["balance"] == 0
            assert me(ctx, tokens["bob"]).json()["balance"] == 50
            assert me(ctx, tokens["cy"]).json()["balance"] == 50

            for p in body["payments"]:
                assert p["note"] == ""
                assert p["visibility"] == "public"

            # Activity: both payments are public, so all three non-operator parties see them.
            for handle in ("ada", "bob", "cy"):
                feed = activity(ctx, tokens[handle]).json()
                assert len(feed["payments"]) == 2
            op_feed = activity(ctx, tokens["op"]).json()
            assert op_feed["payments"] == []


class TestInsufficientFunds:
    """Criterion 2: net unaffordable settlement fails atomically."""

    def test_insufficient_then_reusable_key(self):
        with running_container() as ctx:
            reset(ctx, settlement_fixture())
            tokens = login_all(ctx)
            r1 = settlement(ctx, tokens["op"], "k1", {
                "transfers": [
                    {"from_handle": "ada", "to_handle": "bob", "amount": 100},
                    {"from_handle": "bob", "to_handle": "cy", "amount": 150},
                ]
            })
            assert r1.status_code == 409
            assert_error_envelope(r1.json(), "insufficient_funds")
            assert me(ctx, tokens["ada"]).json()["balance"] == 100
            assert me(ctx, tokens["bob"]).json()["balance"] == 0
            assert me(ctx, tokens["cy"]).json()["balance"] == 0

            r2 = settlement(ctx, tokens["op"], "k1", {
                "transfers": [
                    {"from_handle": "ada", "to_handle": "bob", "amount": 100},
                ]
            })
            assert r2.status_code == 201
            assert me(ctx, tokens["ada"]).json()["balance"] == 0
            assert me(ctx, tokens["bob"]).json()["balance"] == 100


class TestAuth:
    """Criterion 3: auth and key."""

    def test_no_token(self):
        with running_container() as ctx:
            reset(ctx, settlement_fixture())
            r = requests.post(
                f"{ctx['url']}/settlements",
                json={"transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": 10}]},
                timeout=REQUEST_TIMEOUT,
            )
            assert r.status_code == 401
            assert_error_envelope(r.json(), "unauthenticated")

    def test_non_operator(self):
        with running_container() as ctx:
            reset(ctx, settlement_fixture())
            token = login(ctx, "ada@example.com", "correct horse")["token"]
            r = settlement(ctx, token, "k1", {"transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": 10}]})
            assert r.status_code == 403
            assert_error_envelope(r.json(), "forbidden")

    def test_missing_key(self):
        with running_container() as ctx:
            reset(ctx, settlement_fixture())
            token = login(ctx, "op@example.com", "op secret")["token"]
            r = requests.post(
                f"{ctx['url']}/settlements",
                json={"transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": 10}]},
                headers={"Authorization": f"Bearer {token}"},
                timeout=REQUEST_TIMEOUT,
            )
            assert r.status_code == 400
            assert_error_envelope(r.json(), "missing_idempotency_key")


class TestBatchValidation:
    """Criterion 4: batch shape and entry errors."""

    def test_empty_or_missing_transfers(self):
        with running_container() as ctx:
            reset(ctx, settlement_fixture())
            token = login(ctx, "op@example.com", "op secret")["token"]
            for body in [{}, {"transfers": []}, {"transfers": "x"}]:
                r = settlement(ctx, token, "k1", body)
                assert r.status_code == 422, f"body={body} gave {r.status_code}"
                assert_error_envelope(r.json(), "validation_failed")

    def test_entry_not_object(self):
        with running_container() as ctx:
            reset(ctx, settlement_fixture())
            token = login(ctx, "op@example.com", "op secret")["token"]
            r = settlement(ctx, token, "k1", {"transfers": [5]})
            assert r.status_code == 422
            assert_error_envelope(r.json(), "validation_failed")

    def test_max_entries(self):
        with running_container() as ctx:
            reset(ctx, settlement_fixture())
            token = login(ctx, "op@example.com", "op secret")["token"]
            transfers_33 = [{"from_handle": "ada", "to_handle": "bob", "amount": 1} for _ in range(33)]
            r = settlement(ctx, token, "k1", {"transfers": transfers_33})
            assert r.status_code == 422
            assert_error_envelope(r.json(), "validation_failed")

            transfers_32 = [{"from_handle": "ada", "to_handle": "bob", "amount": 1} for _ in range(32)]
            r = settlement(ctx, token, "k2", {"transfers": transfers_32})
            assert r.status_code == 201
            assert len(r.json()["payments"]) == 32

    def test_first_entry_decides(self):
        with running_container() as ctx:
            reset(ctx, settlement_fixture())
            token = login(ctx, "op@example.com", "op secret")["token"]
            # Unknown first, self-transfer second -> 404
            r = settlement(ctx, token, "k1", {
                "transfers": [
                    {"from_handle": "nobody", "to_handle": "bob", "amount": 10},
                    {"from_handle": "bob", "to_handle": "bob", "amount": 10},
                ]
            })
            assert r.status_code == 404
            assert_error_envelope(r.json(), "not_found")
            # Self-transfer first, unknown second -> 422 self_payment
            r = settlement(ctx, token, "k2", {
                "transfers": [
                    {"from_handle": "bob", "to_handle": "bob", "amount": 10},
                    {"from_handle": "nobody", "to_handle": "bob", "amount": 10},
                ]
            })
            assert r.status_code == 422
            assert_error_envelope(r.json(), "self_payment")

    def test_invalid_amount_before_unaffordable(self):
        with running_container() as ctx:
            reset(ctx, settlement_fixture())
            token = login(ctx, "op@example.com", "op secret")["token"]
            r = settlement(ctx, token, "k1", {
                "transfers": [
                    {"from_handle": "ada", "to_handle": "bob", "amount": 1.5},
                    {"from_handle": "bob", "to_handle": "cy", "amount": 150},
                ]
            })
            assert r.status_code == 422
            assert_error_envelope(r.json(), "validation_failed")

    def test_unknown_fields_ignored(self):
        with running_container() as ctx:
            reset(ctx, settlement_fixture())
            token = login(ctx, "op@example.com", "op secret")["token"]
            r = settlement(ctx, token, "k1", {
                "transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": 10}],
                "extra": "ignored",
            })
            assert r.status_code == 201


class TestVisibilityAndSettlementId:
    """Criterion 5: private members, non-settlement payments expose null settlement_id."""

    def test_private_member(self):
        with running_container() as ctx:
            reset(ctx, settlement_fixture())
            tokens = login_all(ctx)
            r = settlement(ctx, tokens["op"], "k1", {
                "transfers": [
                    {"from_handle": "ada", "to_handle": "bob", "amount": 100, "visibility": "private", "note": ".private"},
                ]
            })
            assert r.status_code == 201
            payment = r.json()["payments"][0]
            assert payment["visibility"] == "private"
            assert payment["note"] == ".private"

            # Sender and receiver see it; operator does not.
            for handle in ("ada", "bob"):
                feed = activity(ctx, tokens[handle]).json()
                assert len(feed["payments"]) == 1
            op_feed = activity(ctx, tokens["op"]).json()
            assert op_feed["payments"] == []

    def test_non_settlement_payment_has_null_settlement_id(self):
        with running_container() as ctx:
            reset(ctx, settlement_fixture())
            tokens = login_all(ctx)
            # Give bob enough to pay.
            settlement(ctx, tokens["op"], "fund", {"transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": 100}]})
            r = pay(ctx, tokens["bob"], "pay-key", {"to_handle": "cy", "amount": 10})
            assert r.status_code == 201
            assert r.json()["settlement_id"] is None


class TestReplay:
    """Criterion 6: idempotency on settlements."""

    def test_replay(self):
        with running_container() as ctx:
            reset(ctx, settlement_fixture())
            token = login(ctx, "op@example.com", "op secret")["token"]
            body = {"transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": 100}]}
            r1 = settlement(ctx, token, "k1", body)
            assert r1.status_code == 201
            original = r1.json()
            r2 = settlement(ctx, token, "k1", body)
            assert r2.status_code == 200
            assert r2.json() == original

    def test_different_body_same_key(self):
        with running_container() as ctx:
            reset(ctx, settlement_fixture())
            token = login(ctx, "op@example.com", "op secret")["token"]
            r1 = settlement(ctx, token, "k1", {"transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": 100}]})
            assert r1.status_code == 201
            r2 = settlement(ctx, token, "k1", {"transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": 50}]})
            assert r2.status_code == 409
            assert_error_envelope(r2.json(), "idempotency_key_reuse")

    def test_concurrent_same_key(self):
        with running_container() as ctx:
            reset(ctx, settlement_fixture())
            token = login(ctx, "op@example.com", "op secret")["token"]
            body = {"transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": 100}]}
            results, errors = [], []

            def do_settlement():
                try:
                    results.append(settlement(ctx, token, "same-key", body))
                except Exception as exc:
                    errors.append(exc)

            threads = [threading.Thread(target=do_settlement) for _ in range(20)]
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

    def test_concurrent_settlement_and_payment(self):
        with running_container() as ctx:
            fixture = settlement_fixture()
            fixture["users"][0]["balance"] = 300
            reset(ctx, fixture)
            tokens = login_all(ctx)
            initial_total = sum(me(ctx, t).json()["balance"] for t in tokens.values())

            results, errors = [], []

            def settle():
                try:
                    results.append(settlement(ctx, tokens["op"], "settle-key", {
                        "transfers": [
                            {"from_handle": "ada", "to_handle": "bob", "amount": 200},
                            {"from_handle": "bob", "to_handle": "cy", "amount": 100},
                        ]
                    }))
                except Exception as exc:
                    errors.append(exc)

            def pay_direct():
                try:
                    results.append(pay(ctx, tokens["ada"], "pay-key", {"to_handle": "cy", "amount": 50}))
                except Exception as exc:
                    errors.append(exc)

            threads = [threading.Thread(target=settle) for _ in range(5)] + [threading.Thread(target=pay_direct) for _ in range(5)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            assert not errors
            assert not any(r.status_code >= 500 for r in results)
            final_balances = {h: me(ctx, tokens[h]).json()["balance"] for h in tokens}
            assert all(b >= 0 for b in final_balances.values())
            assert sum(final_balances.values()) == initial_total


class TestOperatorPermissions:
    """Criterion 7: operator cannot see other users' requests."""

    def test_operator_sees_only_own_requests(self):
        with running_container() as ctx:
            fixture = settlement_fixture()
            fixture["requests"] = [
                {
                    "id": "r_1",
                    "requester_id": "u_ada",
                    "payer_id": "u_bob",
                    "amount": 10,
                    "status": "pending",
                }
            ]
            reset(ctx, fixture)
            op_token = login(ctx, "op@example.com", "op secret")["token"]
            assert requests_list(ctx, op_token).json()["requests"] == []
            ada_token = login(ctx, "ada@example.com", "correct horse")["token"]
            assert len(requests_list(ctx, ada_token).json()["requests"]) == 1