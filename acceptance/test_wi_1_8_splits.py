"""Black-box acceptance tests for WI-1.8 — POST /splits."""

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
    request_pay,
    requests_list,
    reset,
    running_container,
    split,
)


def is_rfc3339(ts: str) -> bool:
    return bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{2}:\d{2}", ts))


def split_fixture():
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
                "balance": 10000,
            },
            {
                "id": "u_cy",
                "email": "cy@example.com",
                "password": "cy pass",
                "display_name": "Cy",
                "handle": "cy",
                "balance": 10000,
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


def assert_split_shape(body: dict, amount: int, note: str, expected_shares: list[dict],
                       expected_request_payers: list[str]):
    expected_keys = {"split_id", "amount", "currency", "note", "shares", "requests", "created_at"}
    assert set(body.keys()) == expected_keys
    assert body["amount"] == amount
    assert body["currency"] == "EUR"
    assert body["note"] == note
    assert body["shares"] == expected_shares
    assert is_rfc3339(body["created_at"])
    assert len(body["requests"]) == len(expected_request_payers)
    for req, payer in zip(body["requests"], expected_request_payers):
        req_keys = {
            "request_id", "requester_id", "requester_handle", "payer_id", "payer_handle",
            "amount", "currency", "note", "status", "payment_id", "created_at",
        }
        assert set(req.keys()) == req_keys
        assert req["requester_id"] == "u_ada"
        assert req["requester_handle"] == "ada"
        assert req["payer_handle"] == payer
        assert req["status"] == "pending"
        assert req["payment_id"] is None


class TestBasicSplit:
    """Criterion 1: basic equal split."""

    def test_equal_split(self):
        with running_container() as ctx:
            reset(ctx, split_fixture())
            tokens = login_all(ctx)
            r = split(ctx, tokens["ada"], "k1", {"amount": 3000, "participant_handles": ["ada", "bob", "cy"], "note": "dinner"})
            assert r.status_code == 201
            assert_json_content_type(r)
            body = r.json()
            assert_split_shape(
                body,
                3000,
                "dinner",
                [{"handle": "ada", "amount": 1000}, {"handle": "bob", "amount": 1000}, {"handle": "cy", "amount": 1000}],
                ["bob", "cy"],
            )

            # Balances unchanged by the split itself.
            for token in tokens.values():
                assert me(ctx, token).json()["balance"] == 10000

            # Requests visible only to their parties.
            ada_incoming = requests_list(ctx, tokens["ada"], {"direction": "incoming"}).json()["requests"]
            assert len(ada_incoming) == 0
            bob_incoming = requests_list(ctx, tokens["bob"], {"direction": "incoming"}).json()["requests"]
            assert len(bob_incoming) == 1
            cy_incoming = requests_list(ctx, tokens["cy"], {"direction": "incoming"}).json()["requests"]
            assert len(cy_incoming) == 1

            # No request appears in activity.
            for token in tokens.values():
                assert activity(ctx, token).json()["payments"] == []


class TestRounding:
    """Criterion 2: equal-split rounding and ordering."""

    @pytest.mark.parametrize("amount,expected", [
        (1000, [334, 333, 333]),
        (1, [1, 0, 0]),
        (10, [4, 3, 3]),
        (999, [333, 333, 333]),
        (5, [1, 1, 1, 1, 1]),
    ])
    def test_rounding(self, amount, expected):
        with running_container() as ctx:
            fixture = split_fixture()
            # need 5 users for last case
            if amount == 5:
                fixture["users"].append({
                    "id": "u_dan",
                    "email": "dan@example.com",
                    "password": "dan pass",
                    "display_name": "Dan",
                    "handle": "dan",
                    "balance": 10000,
                })
                fixture["users"].append({
                    "id": "u_eve",
                    "email": "eve@example.com",
                    "password": "eve pass",
                    "display_name": "Eve",
                    "handle": "eve",
                    "balance": 10000,
                })
            reset(ctx, fixture)
            token = login(ctx, "ada@example.com", "correct horse")["token"]
            handles = ["ada", "bob", "cy"] if amount != 5 else ["ada", "bob", "cy", "dan", "eve"]
            r = split(ctx, token, "k1", {"amount": amount, "participant_handles": handles})
            assert r.status_code == 201
            shares = [s["amount"] for s in r.json()["shares"]]
            assert shares == expected
            assert sum(shares) == amount

    def test_order_moves_extra_unit(self):
        with running_container() as ctx:
            reset(ctx, split_fixture())
            token = login(ctx, "ada@example.com", "correct horse")["token"]
            r1 = split(ctx, token, "k1", {"amount": 1000, "participant_handles": ["ada", "bob", "cy"]})
            assert [s["amount"] for s in r1.json()["shares"]] == [334, 333, 333]
            r2 = split(ctx, token, "k2", {"amount": 1000, "participant_handles": ["cy", "bob", "ada"]})
            assert [s["amount"] for s in r2.json()["shares"]] == [334, 333, 333]
            assert r2.json()["shares"][0]["handle"] == "cy"

    def test_caller_omitted(self):
        with running_container() as ctx:
            reset(ctx, split_fixture())
            token = login(ctx, "ada@example.com", "correct horse")["token"]
            r = split(ctx, token, "k1", {"amount": 2000, "participant_handles": ["bob", "cy"]})
            assert r.status_code == 201
            assert_split_shape(
                r.json(),
                2000,
                "",
                [{"handle": "bob", "amount": 1000}, {"handle": "cy", "amount": 1000}],
                ["bob", "cy"],
            )


class TestZeroShare:
    """Criterion 3: a 0 share still creates a request, payable as 0."""

    def test_zero_share_payable(self):
        with running_container() as ctx:
            reset(ctx, split_fixture())
            tokens = login_all(ctx)
            r = split(ctx, tokens["ada"], "k1", {"amount": 1, "participant_handles": ["ada", "bob", "cy"]})
            assert r.status_code == 201
            body = r.json()
            assert body["shares"] == [{"handle": "ada", "amount": 1}, {"handle": "bob", "amount": 0}, {"handle": "cy", "amount": 0}]
            zero_req = [req for req in body["requests"] if req["payer_handle"] == "bob"][0]
            assert zero_req["amount"] == 0
            pr = request_pay(ctx, tokens["bob"], zero_req["request_id"], "pay-zero", {})
            assert pr.status_code == 201
            assert pr.json()["amount"] == 0


class TestCallerOnly:
    """Criterion 4: only the caller → valid, no requests."""

    def test_caller_only(self):
        with running_container() as ctx:
            reset(ctx, split_fixture())
            token = login(ctx, "ada@example.com", "correct horse")["token"]
            r = split(ctx, token, "k1", {"amount": 100, "participant_handles": ["ada"]})
            assert r.status_code == 201
            assert_split_shape(
                r.json(),
                100,
                "",
                [{"handle": "ada", "amount": 100}],
                [],
            )


class TestValidation:
    """Criterion 5: validation errors."""

    def test_empty_handles(self):
        with running_container() as ctx:
            reset(ctx, split_fixture())
            token = login(ctx, "ada@example.com", "correct horse")["token"]
            r = split(ctx, token, "k1", {"amount": 100, "participant_handles": []})
            assert r.status_code == 422
            assert_error_envelope(r.json(), "validation_failed")

    def test_duplicate_handles(self):
        with running_container() as ctx:
            reset(ctx, split_fixture())
            token = login(ctx, "ada@example.com", "correct horse")["token"]
            r = split(ctx, token, "k1", {"amount": 100, "participant_handles": ["ada", "bob", "ada"]})
            assert r.status_code == 422
            assert_error_envelope(r.json(), "validation_failed")

    def test_unknown_handle(self):
        with running_container() as ctx:
            reset(ctx, split_fixture())
            token = login(ctx, "ada@example.com", "correct horse")["token"]
            r = split(ctx, token, "k1", {"amount": 100, "participant_handles": ["ada", "nobody"]})
            assert r.status_code == 404
            assert_error_envelope(r.json(), "not_found")
            # No requests were created.
            assert requests_list(ctx, token).json()["requests"] == []

    def test_invalid_amount(self):
        with running_container() as ctx:
            reset(ctx, split_fixture())
            token = login(ctx, "ada@example.com", "correct horse")["token"]
            for bad in [0, -1, 1000000001, 1.5, "5", True, None]:
                r = split(ctx, token, f"k-{bad}", {"amount": bad, "participant_handles": ["ada", "bob"]})
                assert r.status_code == 422, f"amount={bad!r} gave {r.status_code}"
                assert_error_envelope(r.json(), "validation_failed")

    def test_note_too_long(self):
        with running_container() as ctx:
            reset(ctx, split_fixture())
            token = login(ctx, "ada@example.com", "correct horse")["token"]
            r = split(ctx, token, "k1", {"amount": 100, "participant_handles": ["ada", "bob"], "note": "x" * 201})
            assert r.status_code == 422
            assert_error_envelope(r.json(), "validation_failed")

    def test_handles_wrong_type(self):
        with running_container() as ctx:
            reset(ctx, split_fixture())
            token = login(ctx, "ada@example.com", "correct horse")["token"]
            r = split(ctx, token, "k1", {"amount": 100, "participant_handles": "ada"})
            assert r.status_code == 400
            assert_error_envelope(r.json(), "malformed_request")

    def test_element_wrong_type(self):
        with running_container() as ctx:
            reset(ctx, split_fixture())
            token = login(ctx, "ada@example.com", "correct horse")["token"]
            r = split(ctx, token, "k1", {"amount": 100, "participant_handles": ["ada", 5]})
            assert r.status_code == 400
            assert_error_envelope(r.json(), "malformed_request")

    def test_missing_handles(self):
        with running_container() as ctx:
            reset(ctx, split_fixture())
            token = login(ctx, "ada@example.com", "correct horse")["token"]
            r = split(ctx, token, "k1", {"amount": 100})
            assert r.status_code == 422
            assert_error_envelope(r.json(), "validation_failed")

    def test_missing_key(self):
        with running_container() as ctx:
            reset(ctx, split_fixture())
            token = login(ctx, "ada@example.com", "correct horse")["token"]
            r = requests.post(
                f"{ctx['url']}/splits",
                json={"amount": 100, "participant_handles": ["ada", "bob"]},
                headers={"Authorization": f"Bearer {token}"},
                timeout=REQUEST_TIMEOUT,
            )
            assert r.status_code == 400
            assert_error_envelope(r.json(), "missing_idempotency_key")


class TestIdempotency:
    """Criterion 6: idempotency on splits."""

    def test_replay_same_body(self):
        with running_container() as ctx:
            reset(ctx, split_fixture())
            token = login(ctx, "ada@example.com", "correct horse")["token"]
            body = {"amount": 100, "participant_handles": ["ada", "bob"]}
            r1 = split(ctx, token, "k1", body)
            assert r1.status_code == 201
            original = r1.json()
            r2 = split(ctx, token, "k1", body)
            assert r2.status_code == 200
            assert r2.json() == original

    def test_different_body_same_key(self):
        with running_container() as ctx:
            reset(ctx, split_fixture())
            token = login(ctx, "ada@example.com", "correct horse")["token"]
            r1 = split(ctx, token, "k1", {"amount": 100, "participant_handles": ["ada", "bob"]})
            assert r1.status_code == 201
            r2 = split(ctx, token, "k1", {"amount": 200, "participant_handles": ["ada", "bob"]})
            assert r2.status_code == 409
            assert_error_envelope(r2.json(), "idempotency_key_reuse")

    def test_concurrent_same_key(self):
        with running_container() as ctx:
            reset(ctx, split_fixture())
            token = login(ctx, "ada@example.com", "correct horse")["token"]
            body = {"amount": 100, "participant_handles": ["ada", "bob"]}
            results, errors = [], []

            def do_split():
                try:
                    results.append(split(ctx, token, "same-key", body))
                except Exception as exc:
                    errors.append(exc)

            threads = [threading.Thread(target=do_split) for _ in range(20)]
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


class TestPayAllRequests:
    """Criterion 7: paying all split requests preserves total balance."""

    def test_pay_all_preserves_total(self):
        with running_container() as ctx:
            reset(ctx, split_fixture())
            tokens = login_all(ctx)
            initial_total = sum(me(ctx, t).json()["balance"] for t in tokens.values())

            r1 = split(ctx, tokens["ada"], "k1", {"amount": 3000, "participant_handles": ["ada", "bob", "cy"]})
            assert r1.status_code == 201
            r2 = split(ctx, tokens["ada"], "k2", {"amount": 2000, "participant_handles": ["ada", "bob"]})
            assert r2.status_code == 201

            all_request_ids = []
            for req in r1.json()["requests"] + r2.json()["requests"]:
                all_request_ids.append((req["payer_handle"], req["request_id"]))

            for payer_handle, rid in all_request_ids:
                pr = request_pay(ctx, tokens[payer_handle], rid, f"pay-{rid}", {})
                assert pr.status_code == 201, f"pay {rid} failed: {pr.status_code} {pr.text}"

            final_total = sum(me(ctx, t).json()["balance"] for t in tokens.values())
            assert final_total == initial_total
