"""Black-box acceptance tests for WI-1.10 — export/import."""

import json
import random
import threading
import time

import pytest
import requests

from conftest import (
    REQUEST_TIMEOUT,
    RESET_TIMEOUT,
    activity,
    api_post,
    assert_error_envelope,
    assert_json_content_type,
    export_state,
    import_state,
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
    settlement,
    signup,
    split,
)


LIFE_FIXTURE = {
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
        {
            "id": "u_cy",
            "email": "cy@example.com",
            "password": "cy pass",
            "display_name": "Cy",
            "handle": "cy",
            "balance": 3000,
        },
        {
            "id": "u_dan",
            "email": "dan@example.com",
            "password": "dan pass",
            "display_name": "Dan",
            "handle": "dan",
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


def life_login_all(ctx: dict) -> dict[str, str]:
    return {
        "ada": login(ctx, "ada@example.com", "correct horse")["token"],
        "bob": login(ctx, "bob@example.com", "battery stapler")["token"],
        "cy": login(ctx, "cy@example.com", "cy pass")["token"],
        "dan": login(ctx, "dan@example.com", "dan pass")["token"],
        "op": login(ctx, "op@example.com", "op secret")["token"],
    }


def total_balances(ctx: dict, tokens: dict[str, str]) -> int:
    return sum(me(ctx, t).json()["balance"] for t in tokens.values())


def id_keys(items: list[dict]) -> set[str]:
    return {item["payment_id"] if "payment_id" in item else item["request_id"] for item in items}


def dict_without(d: dict, keys: set[str]) -> dict:
    return {k: v for k, v in d.items() if k not in keys}


class TestExportShape:
    """Criterion 1: export envelope is correct."""

    def test_export_shape(self):
        with running_container() as ctx:
            reset(ctx, LIFE_FIXTURE)
            tokens = life_login_all(ctx)

            # build variety
            pay(ctx, tokens["ada"], "pay-public", {"to_handle": "bob", "amount": 100, "visibility": "public"}).json()
            pay(ctx, tokens["ada"], "pay-private", {"to_handle": "bob", "amount": 50, "visibility": "private"}).json()
            r_pending = request_post(ctx, tokens["ada"], "req-pending", {"payer_handle": "bob", "amount": 30}).json()
            r_declined = request_post(ctx, tokens["ada"], "req-declined", {"payer_handle": "bob", "amount": 40}).json()
            request_decline(ctx, tokens["bob"], r_declined["request_id"])
            r_cancelled = request_post(ctx, tokens["ada"], "req-cancelled", {"payer_handle": "bob", "amount": 20}).json()
            request_cancel(ctx, tokens["ada"], r_cancelled["request_id"])
            r_paid = request_post(ctx, tokens["ada"], "req-paid", {"payer_handle": "bob", "amount": 70}).json()
            request_pay(ctx, tokens["bob"], r_paid["request_id"], "req-paid-pay", {})
            split(ctx, tokens["ada"], "split-1", {"participant_handles": ["ada", "bob", "cy"], "amount": 300, "note": "dinner"})
            settlement(ctx, tokens["op"], "settle-1", {"transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": 10}]})
            pay(ctx, tokens["dan"], "failed-pay", {"to_handle": "ada", "amount": 1})  # 409, dan has 0

            r = export_state(ctx)
            assert r.status_code == 200
            assert_json_content_type(r)
            body = r.json()
            assert set(body.keys()) == {"track", "format_version", "state"}
            assert body["track"] == "pocketful"
            assert body["format_version"] == 1
            assert isinstance(body["state"], dict) and body["state"]


class TestImportPreservesState:
    """Criterion 2: import preserves users, tokens, activity, requests."""

    def create_life(self, ctx: dict) -> tuple[dict[str, str], dict, dict, requests.Response]:
        reset(ctx, LIFE_FIXTURE)
        tokens = life_login_all(ctx)

        signup_resp = signup(ctx, "xtra@example.com", "xtra password", "Extra")
        assert signup_resp.status_code == 201
        extra_token = login(ctx, "xtra@example.com", "xtra password")["token"]
        tokens["extra"] = extra_token

        pay(ctx, tokens["ada"], "pay-public", {"to_handle": "bob", "amount": 100, "visibility": "public"}).json()
        pay(ctx, tokens["ada"], "pay-private", {"to_handle": "bob", "amount": 50, "visibility": "private"}).json()
        r_pending = request_post(ctx, tokens["ada"], "req-pending", {"payer_handle": "bob", "amount": 30}).json()
        r_declined = request_post(ctx, tokens["ada"], "req-declined", {"payer_handle": "bob", "amount": 40}).json()
        request_decline(ctx, tokens["bob"], r_declined["request_id"])
        r_cancelled = request_post(ctx, tokens["ada"], "req-cancelled", {"payer_handle": "bob", "amount": 20}).json()
        request_cancel(ctx, tokens["ada"], r_cancelled["request_id"])
        r_paid = request_post(ctx, tokens["ada"], "req-paid", {"payer_handle": "bob", "amount": 70}).json()
        request_pay(ctx, tokens["bob"], r_paid["request_id"], "req-paid-pay", {})
        split_body = split(ctx, tokens["ada"], "split-1", {"participant_handles": ["ada", "bob", "cy"], "amount": 300, "note": "dinner"}).json()
        settlement_body = settlement(ctx, tokens["op"], "settle-1", {"transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": 10}]}).json()
        pay(ctx, tokens["dan"], "failed-pay", {"to_handle": "ada", "amount": 1})  # fails

        # capture state on A
        a_state = {h: {"me": me(ctx, t).json(), "activity": activity(ctx, t).json(), "requests": requests_list(ctx, t).json()} for h, t in tokens.items()}
        a_total = total_balances(ctx, tokens)
        export_resp = export_state(ctx)
        assert export_resp.status_code == 200
        payload = export_resp.json()
        return tokens, a_state, payload, export_resp

    def test_import_preserves_everything(self):
        with running_container() as a_ctx:
            tokens, a_state, payload, _export = self.create_life(a_ctx)
            a_total = total_balances(a_ctx, tokens)
            with running_container() as b_ctx:
                r = import_state(b_ctx, payload)
                assert r.status_code == 204
                assert r.text == ""

                # Old tokens work; balances, ids, handles, currency match.
                for handle, token in tokens.items():
                    a_me = a_state[handle]["me"]
                    b_me = me(b_ctx, token).json()
                    assert b_me["user_id"] == a_me["user_id"]
                    assert b_me["handle"] == a_me["handle"]
                    assert b_me["email"] == a_me["email"]
                    assert b_me["balance"] == a_me["balance"]
                    assert b_me["currency"] == a_me["currency"]
                    assert b_me["minor_units"] == a_me["minor_units"]

                # Users can still log in with original passwords.
                for email, password in [
                    ("ada@example.com", "correct horse"),
                    ("bob@example.com", "battery stapler"),
                    ("xtra@example.com", "xtra password"),
                ]:
                    assert login(b_ctx, email, password)["token"]

                # Activity and requests match (same ids, timestamps, statuses, settlement_id).
                for handle, token in tokens.items():
                    b_activity = activity(b_ctx, token).json()
                    b_requests = requests_list(b_ctx, token).json()
                    a_activity = a_state[handle]["activity"]
                    a_requests = a_state[handle]["requests"]
                    assert len(b_activity["payments"]) == len(a_activity["payments"])
                    assert len(b_requests["requests"]) == len(a_requests["requests"])
                    assert id_keys(b_activity["payments"]) == id_keys(a_activity["payments"])
                    assert id_keys(b_requests["requests"]) == id_keys(a_requests["requests"])

                # Monetary total is unchanged.
                assert total_balances(b_ctx, tokens) == a_total


class TestIdempotentReplay:
    """Criterion 3: replaying idempotent requests after import returns original responses."""

    def test_replays_and_failed_key_reusable(self):
        with running_container() as a_ctx:
            reset(a_ctx, LIFE_FIXTURE)
            tokens = life_login_all(a_ctx)

            # Record original idempotent requests/responses.
            originals = []

            def record(resp):
                originals.append(resp.json())
                return resp

            record(pay(a_ctx, tokens["ada"], "pay-public", {"to_handle": "bob", "amount": 100}))
            req = request_post(a_ctx, tokens["ada"], "req-pending", {"payer_handle": "bob", "amount": 30}).json()
            record(request_pay(a_ctx, tokens["bob"], req["request_id"], "req-pay", {}))
            record(split(a_ctx, tokens["ada"], "split-1", {"participant_handles": ["ada", "bob", "cy"], "amount": 300}))
            record(settlement(a_ctx, tokens["op"], "settle-1", {"transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": 10}]}))
            # Failed payment key should remain usable.
            failed = pay(a_ctx, tokens["dan"], "failed-pay", {"to_handle": "ada", "amount": 1})
            assert failed.status_code == 409

            payload = export_state(a_ctx).json()

            with running_container() as b_ctx:
                assert import_state(b_ctx, payload).status_code == 204

                # Replay with same keys and bodies => 200 with original response.
                pay_r = pay(b_ctx, tokens["ada"], "pay-public", {"to_handle": "bob", "amount": 100})
                assert pay_r.status_code == 200
                assert pay_r.json() == originals[0]

                req_pay_r = request_pay(b_ctx, tokens["bob"], req["request_id"], "req-pay", {})
                assert req_pay_r.status_code == 200
                assert req_pay_r.json() == originals[1]

                split_r = split(b_ctx, tokens["ada"], "split-1", {"participant_handles": ["ada", "bob", "cy"], "amount": 300})
                assert split_r.status_code == 200
                assert split_r.json() == originals[2]

                settle_r = settlement(b_ctx, tokens["op"], "settle-1", {"transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": 10}]})
                assert settle_r.status_code == 200
                assert settle_r.json() == originals[3]

                # State did not change from replays.
                assert me(b_ctx, tokens["ada"]).json()["balance"] == 10000 - 100 - 10

                # Different body with same key -> 409.
                conflict = pay(b_ctx, tokens["ada"], "pay-public", {"to_handle": "bob", "amount": 99})
                assert conflict.status_code == 409
                assert_error_envelope(conflict.json(), "idempotency_key_reuse")

                # Failed key reusable with a valid body -> 201.
                reuse = pay(b_ctx, tokens["dan"], "failed-pay", {"to_handle": "ada", "amount": 0})
                assert reuse.status_code == 201


class TestOperatorAndNewWrites:
    """Criterion 4: operators preserved; new ids do not collide."""

    def test_operator_and_unique_new_ids(self):
        with running_container() as a_ctx:
            reset(a_ctx, LIFE_FIXTURE)
            tokens = life_login_all(a_ctx)
            settlement_body = settlement(a_ctx, tokens["op"], "settle-1", {"transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": 10}]}).json()
            exported_ids = {p["payment_id"] for p in settlement_body["payments"]}
            exported_ids.add(settlement_body["settlement_id"])
            a_total = total_balances(a_ctx, tokens)

            payload = export_state(a_ctx).json()
            with running_container() as b_ctx:
                assert import_state(b_ctx, payload).status_code == 204

                # Operator can still settle.
                new_settle = settlement(b_ctx, tokens["op"], "settle-2", {"transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": 1}]})
                assert new_settle.status_code == 201
                new_id = new_settle.json()["settlement_id"]
                assert new_id not in exported_ids

                # New direct payment id does not collide.
                new_pay = pay(b_ctx, tokens["ada"], "new-pay", {"to_handle": "cy", "amount": 5})
                assert new_pay.status_code == 201
                assert new_pay.json()["payment_id"] not in exported_ids

                assert total_balances(b_ctx, tokens) == a_total - 1 - 5


class TestImportReplacement:
    """Criteria 5 and 6: import removes previous destination state; invalid imports rejected."""

    def test_import_twice_and_removes_previous_state(self):
        with running_container() as a_ctx:
            reset(a_ctx, LIFE_FIXTURE)
            tokens = life_login_all(a_ctx)
            settlement(a_ctx, tokens["op"], "settle-1", {"transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": 10}]})
            payload = export_state(a_ctx).json()

            with running_container() as b_ctx:
                # B has its own user.
                reset(b_ctx, {
                    "currency": "EUR",
                    "minor_units": 2,
                    "users": [{
                        "id": "u_b_only",
                        "email": "bonly@example.com",
                        "password": "b secret",
                        "display_name": "BOnly",
                        "handle": "bonly",
                        "balance": 1234,
                    }],
                    "payments": [],
                    "requests": [],
                })
                bonly_token = login(b_ctx, "bonly@example.com", "b secret")["token"]

                # Import A into B.
                assert import_state(b_ctx, payload).status_code == 204
                # B-only token is dead.
                assert me(b_ctx, bonly_token).status_code == 401

                a_total = total_balances(a_ctx, tokens)
                assert total_balances(b_ctx, tokens) == a_total

                # Import again does not duplicate.
                assert import_state(b_ctx, payload).status_code == 204
                assert total_balances(b_ctx, tokens) == a_total
                all_payments = activity(b_ctx, tokens["op"]).json()["payments"]
                settlement_payments = [p for p in all_payments if p["settlement_id"]]
                assert len(settlement_payments) == 1

    def test_invalid_imports_leave_state_unchanged(self):
        with running_container() as a_ctx:
            reset(a_ctx, LIFE_FIXTURE)
            tokens = life_login_all(a_ctx)
            payload = export_state(a_ctx).json()

            with running_container() as b_ctx:
                assert import_state(b_ctx, payload).status_code == 204
                before_balance = me(b_ctx, tokens["ada"]).json()["balance"]
                before_count = len(activity(b_ctx, tokens["ada"]).json()["payments"])

                bad_cases = [
                    {},
                    {"track": "pocketful", "format_version": 1},
                    {"track": "other", "format_version": 1, "state": payload["state"]},
                    {"track": "pocketful", "format_version": 2, "state": payload["state"]},
                    {"track": "pocketful", "format_version": 1, "state": {}},
                    {"track": "pocketful", "format_version": 1, "state": {"garbage": True}},
                ]
                for bad in bad_cases:
                    r = import_state(b_ctx, bad)
                    assert r.status_code == 422, f"bad={bad} gave {r.status_code}"
                    assert_error_envelope(r.json(), "validation_failed")

                # Unparseable body -> 400.
                r = requests.post(
                    f"{b_ctx['url']}/_test/import",
                    data="not json",
                    timeout=RESET_TIMEOUT,
                )
                assert r.status_code == 400
                assert_error_envelope(r.json(), "malformed_request")

                # State unchanged.
                assert me(b_ctx, tokens["ada"]).json()["balance"] == before_balance
                assert len(activity(b_ctx, tokens["ada"]).json()["payments"]) == before_count


class TestSnapshotIsolation:
    """Criterion 7: export is a point-in-time snapshot."""

    def test_export_not_changed_by_later_writes(self):
        with running_container() as a_ctx:
            reset(a_ctx, LIFE_FIXTURE)
            tokens = life_login_all(a_ctx)
            pay(a_ctx, tokens["ada"], "pay1", {"to_handle": "bob", "amount": 100})
            payload = export_state(a_ctx).json()
            b_activity_at_export = activity(a_ctx, tokens["op"]).json()["payments"]

            # More writes on A after export.
            pay(a_ctx, tokens["ada"], "pay2", {"to_handle": "bob", "amount": 50})

            with running_container() as b_ctx:
                assert import_state(b_ctx, payload).status_code == 204
                imported = activity(b_ctx, tokens["op"]).json()["payments"]
                assert len(imported) == len(b_activity_at_export)
                assert id_keys(imported) == id_keys(b_activity_at_export)

    def test_export_under_concurrent_writes_is_consistent(self):
        with running_container() as ctx:
            reset(ctx, LIFE_FIXTURE)
            tokens = life_login_all(ctx)
            seeded_total = total_balances(ctx, tokens)

            results = []
            errors = []

            def do_payments():
                try:
                    for _ in range(10):
                        r = pay(ctx, tokens["ada"], None, {"to_handle": "bob", "amount": 1})
                        results.append(r.status_code)
                except Exception as exc:
                    errors.append(exc)

            t = threading.Thread(target=do_payments)
            t.start()
            payload = export_state(ctx).json()
            t.join()

            assert not errors
            assert not any(code >= 500 for code in results)

            with running_container() as b_ctx:
                assert import_state(b_ctx, payload).status_code == 204
                assert total_balances(b_ctx, tokens) == seeded_total


class TestResetAfterImport:
    """Part of criterion 8: reset clears imported state."""

    def test_reset_clears_imported_users(self):
        with running_container() as a_ctx:
            reset(a_ctx, LIFE_FIXTURE)
            tokens = life_login_all(a_ctx)
            payload = export_state(a_ctx).json()

            with running_container() as b_ctx:
                assert import_state(b_ctx, payload).status_code == 204
                reset(b_ctx, {
                    "currency": "EUR",
                    "minor_units": 2,
                    "users": [],
                    "payments": [],
                    "requests": [],
                })
                for token in tokens.values():
                    assert me(b_ctx, token).status_code == 401


class TestPerformance:
    """Criterion 8: export/import under 10 s for 200 users / 2,000 payments."""

    def _large_fixture(self) -> dict:
        users = []
        for i in range(200):
            uid = f"u_{i:03d}"
            users.append({
                "id": uid,
                "email": f"u{i}@example.com",
                "password": "pw",
                "display_name": f"U{i}",
                "handle": f"u{i}",
                "balance": 10000,
            })
        payments = []
        for i in range(2000):
            payments.append({
                "id": f"p_{i}",
                "from_user_id": f"u_{(i % 200):03d}",
                "to_user_id": f"u_{((i + 1) % 200):03d}",
                "amount": 1,
                "visibility": "public",
            })
        return {
            "currency": "EUR",
            "minor_units": 2,
            "users": users,
            "payments": payments,
            "requests": [],
        }

    def test_export_import_performance(self):
        with running_container() as a_ctx:
            reset(a_ctx, self._large_fixture())
            export_resp = export_state(a_ctx)
            assert export_resp.status_code == 200
            payload = export_resp.json()

            with running_container() as b_ctx:
                start = time.monotonic()
                r = import_state(b_ctx, payload)
                elapsed = time.monotonic() - start
                assert r.status_code == 204
                assert elapsed < 10, f"import took {elapsed:.2f}s"

                start = time.monotonic()
                export_state(b_ctx)
                elapsed = time.monotonic() - start
                assert elapsed < 10, f"export took {elapsed:.2f}s"