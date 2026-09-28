"""Black-box acceptance tests for WI-1.2 — reset, login and /me."""

import json
import threading
import time

import pytest
import requests

from conftest import (
    REQUEST_TIMEOUT,
    RESET_TIMEOUT,
    assert_error_envelope,
    assert_json_content_type,
    docker,
    login,
    me,
    reset,
    running_container,
)


def eur_fixture():
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
        "payments": [
            {
                "id": "p_1",
                "from_user_id": "u_ada",
                "to_user_id": "u_bob",
                "amount": 500,
                "note": "coffee",
                "visibility": "public",
            }
        ],
        "requests": [
            {
                "id": "rq_1",
                "requester_id": "u_bob",
                "payer_id": "u_ada",
                "amount": 1200,
                "note": "taxi",
                "status": "pending",
            }
        ],
    }


def fixture_b():
    return {
        "currency": "EUR",
        "minor_units": 2,
        "users": [
            {
                "id": "u_cy",
                "email": "cy@example.com",
                "password": "cy pass",
                "display_name": "Cy",
                "handle": "cy",
                "balance": 500,
            }
        ],
    }


class TestResetAndLogin:
    """Criterion 1: reset → login → /me."""

    def test_reset_login_me(self):
        with running_container() as ctx:
            r = requests.post(
                f"{ctx['url']}/_test/reset",
                json=eur_fixture(),
                timeout=RESET_TIMEOUT,
            )
            assert r.status_code == 204
            assert r.text == ""

            login_resp = login(ctx, "ada@example.com", "correct horse")
            assert login_resp["user_id"] == "u_ada"
            assert login_resp["display_name"] == "Ada"
            assert isinstance(login_resp["token"], str) and login_resp["token"]

            r = me(ctx, login_resp["token"])
            assert r.status_code == 200
            assert_json_content_type(r)
            assert r.json() == {
                "user_id": "u_ada",
                "display_name": "Ada",
                "handle": "ada",
                "balance": 10000,
                "currency": "EUR",
                "minor_units": 2,
            }

    def test_reset_with_no_token(self):
        with running_container() as ctx:
            r = requests.post(
                f"{ctx['url']}/_test/reset", json=eur_fixture(), timeout=RESET_TIMEOUT
            )
            assert r.status_code == 204


class TestCurrencies:
    """Criterion 2: JPY and BHD minor_units reflected in /me."""

    @pytest.mark.parametrize(
        "currency, minor_units, balance",
        [
            ("JPY", 0, 5000),
            ("BHD", 3, 1234567),
        ],
    )
    def test_currency_and_minor_units(self, currency, minor_units, balance):
        with running_container() as ctx:
            fixture = {
                "currency": currency,
                "minor_units": minor_units,
                "users": [
                    {
                        "id": "u_x",
                        "email": "x@example.com",
                        "password": "pass word",
                        "display_name": "X",
                        "handle": "x",
                        "balance": balance,
                    }
                ],
            }
            reset(ctx, fixture)
            token = login(ctx, "x@example.com", "pass word")["token"]
            r = me(ctx, token)
            assert r.status_code == 200
            body = r.json()
            assert body["currency"] == currency
            assert body["minor_units"] == minor_units
            assert body["balance"] == balance
            assert body["handle"] == "x"


class TestResetReplacesState:
    """Criterion 3: reset A then reset B; A is gone, B works."""

    def test_reset_replace_state(self):
        with running_container() as ctx:
            reset(ctx, eur_fixture())
            ada_token = login(ctx, "ada@example.com", "correct horse")["token"]
            bob_token = login(ctx, "bob@example.com", "battery stapler")["token"]
            assert me(ctx, ada_token).status_code == 200
            assert me(ctx, bob_token).status_code == 200

            reset(ctx, fixture_b())

            for email, password in [
                ("ada@example.com", "correct horse"),
                ("bob@example.com", "battery stapler"),
            ]:
                r = requests.post(
                    f"{ctx['url']}/auth/login",
                    json={"email": email, "password": password},
                    timeout=REQUEST_TIMEOUT,
                )
                assert r.status_code == 401
                assert_error_envelope(r.json(), "unauthenticated")

            for token in (ada_token, bob_token):
                r = me(ctx, token)
                assert r.status_code == 401
                assert_error_envelope(r.json(), "unauthenticated")

            cy_token = login(ctx, "cy@example.com", "cy pass")["token"]
            r = me(ctx, cy_token)
            assert r.status_code == 200
            assert r.json()["user_id"] == "u_cy"


class TestInvalidFixtures:
    """Criterion 4: invalid fixtures return 400/422 and change nothing."""

    def _assert_state_unchanged(self, ctx, token):
        r = me(ctx, token)
        assert r.status_code == 200
        assert r.json()["user_id"] == "u_ada"

    def test_negative_balance(self):
        with running_container() as ctx:
            reset(ctx, eur_fixture())
            token = login(ctx, "ada@example.com", "correct horse")["token"]
            fixture = eur_fixture()
            fixture["users"][0]["balance"] = -1
            r = requests.post(
                f"{ctx['url']}/_test/reset", json=fixture, timeout=RESET_TIMEOUT
            )
            assert r.status_code == 422
            assert_json_content_type(r)
            assert_error_envelope(r.json(), "validation_failed")
            self._assert_state_unchanged(ctx, token)

    def test_non_integer_balance(self):
        with running_container() as ctx:
            reset(ctx, eur_fixture())
            token = login(ctx, "ada@example.com", "correct horse")["token"]
            fixture = eur_fixture()
            fixture["users"][0]["balance"] = 100.5
            r = requests.post(
                f"{ctx['url']}/_test/reset", json=fixture, timeout=RESET_TIMEOUT
            )
            assert r.status_code == 422
            assert_error_envelope(r.json(), "validation_failed")
            self._assert_state_unchanged(ctx, token)

    def test_invalid_minor_units(self):
        with running_container() as ctx:
            reset(ctx, eur_fixture())
            token = login(ctx, "ada@example.com", "correct horse")["token"]
            for bad in [1, -1, 4, "2"]:
                fixture = eur_fixture()
                fixture["minor_units"] = bad
                r = requests.post(
                    f"{ctx['url']}/_test/reset", json=fixture, timeout=RESET_TIMEOUT
                )
                assert r.status_code == 422, f"minor_units={bad} gave {r.status_code}"
                assert_error_envelope(r.json(), "validation_failed")
                self._assert_state_unchanged(ctx, token)

    def test_missing_currency(self):
        with running_container() as ctx:
            reset(ctx, eur_fixture())
            token = login(ctx, "ada@example.com", "correct horse")["token"]
            fixture = eur_fixture()
            del fixture["currency"]
            r = requests.post(
                f"{ctx['url']}/_test/reset", json=fixture, timeout=RESET_TIMEOUT
            )
            assert r.status_code == 422
            assert_error_envelope(r.json(), "validation_failed")
            self._assert_state_unchanged(ctx, token)

    def test_missing_users(self):
        with running_container() as ctx:
            reset(ctx, eur_fixture())
            token = login(ctx, "ada@example.com", "correct horse")["token"]
            fixture = {"currency": "EUR", "minor_units": 2}
            r = requests.post(
                f"{ctx['url']}/_test/reset", json=fixture, timeout=RESET_TIMEOUT
            )
            assert r.status_code == 422
            assert_error_envelope(r.json(), "validation_failed")
            self._assert_state_unchanged(ctx, token)

    def test_user_missing_required_field(self):
        with running_container() as ctx:
            reset(ctx, eur_fixture())
            token = login(ctx, "ada@example.com", "correct horse")["token"]
            for field in ("id", "email", "password", "handle", "balance"):
                fixture = eur_fixture()
                del fixture["users"][0][field]
                r = requests.post(
                    f"{ctx['url']}/_test/reset", json=fixture, timeout=RESET_TIMEOUT
                )
                assert r.status_code == 422, f"missing {field} gave {r.status_code}"
                assert_error_envelope(r.json(), "validation_failed")
                self._assert_state_unchanged(ctx, token)

    def test_invalid_handle(self):
        with running_container() as ctx:
            reset(ctx, eur_fixture())
            token = login(ctx, "ada@example.com", "correct horse")["token"]
            for bad in ["Ada", "ada-lovelace", "ada@example", "", "a" * 21]:
                fixture = eur_fixture()
                fixture["users"][0]["handle"] = bad
                r = requests.post(
                    f"{ctx['url']}/_test/reset", json=fixture, timeout=RESET_TIMEOUT
                )
                assert r.status_code == 422, f"handle={bad!r} gave {r.status_code}"
                assert_error_envelope(r.json(), "validation_failed")
                self._assert_state_unchanged(ctx, token)

    def test_duplicate_user_ids(self):
        with running_container() as ctx:
            reset(ctx, eur_fixture())
            token = login(ctx, "ada@example.com", "correct horse")["token"]
            fixture = eur_fixture()
            fixture["users"][1]["id"] = fixture["users"][0]["id"]
            r = requests.post(
                f"{ctx['url']}/_test/reset", json=fixture, timeout=RESET_TIMEOUT
            )
            assert r.status_code == 422
            assert_error_envelope(r.json(), "validation_failed")
            self._assert_state_unchanged(ctx, token)

    def test_duplicate_handles(self):
        with running_container() as ctx:
            reset(ctx, eur_fixture())
            token = login(ctx, "ada@example.com", "correct horse")["token"]
            fixture = eur_fixture()
            fixture["users"][1]["handle"] = fixture["users"][0]["handle"]
            r = requests.post(
                f"{ctx['url']}/_test/reset", json=fixture, timeout=RESET_TIMEOUT
            )
            assert r.status_code == 422
            assert_error_envelope(r.json(), "validation_failed")
            self._assert_state_unchanged(ctx, token)

    def test_duplicate_emails(self):
        with running_container() as ctx:
            reset(ctx, eur_fixture())
            token = login(ctx, "ada@example.com", "correct horse")["token"]
            fixture = eur_fixture()
            fixture["users"][1]["email"] = fixture["users"][0]["email"]
            r = requests.post(
                f"{ctx['url']}/_test/reset", json=fixture, timeout=RESET_TIMEOUT
            )
            assert r.status_code == 422
            assert_error_envelope(r.json(), "validation_failed")
            self._assert_state_unchanged(ctx, token)

    def test_payment_unknown_user(self):
        with running_container() as ctx:
            reset(ctx, eur_fixture())
            token = login(ctx, "ada@example.com", "correct horse")["token"]
            fixture = eur_fixture()
            fixture["payments"][0]["from_user_id"] = "u_nobody"
            r = requests.post(
                f"{ctx['url']}/_test/reset", json=fixture, timeout=RESET_TIMEOUT
            )
            assert r.status_code == 422
            assert_error_envelope(r.json(), "validation_failed")
            self._assert_state_unchanged(ctx, token)

    def test_payment_invalid_amount(self):
        with running_container() as ctx:
            reset(ctx, eur_fixture())
            token = login(ctx, "ada@example.com", "correct horse")["token"]
            for bad in [-1, "500", 1.5, 1000000001]:
                fixture = eur_fixture()
                fixture["payments"][0]["amount"] = bad
                r = requests.post(
                    f"{ctx['url']}/_test/reset", json=fixture, timeout=RESET_TIMEOUT
                )
                assert r.status_code == 422, f"amount={bad} gave {r.status_code}"
                assert_error_envelope(r.json(), "validation_failed")
                self._assert_state_unchanged(ctx, token)

    def test_payment_invalid_visibility(self):
        with running_container() as ctx:
            reset(ctx, eur_fixture())
            token = login(ctx, "ada@example.com", "correct horse")["token"]
            for bad in ["secret", "", None]:
                fixture = eur_fixture()
                fixture["payments"][0]["visibility"] = bad
                r = requests.post(
                    f"{ctx['url']}/_test/reset", json=fixture, timeout=RESET_TIMEOUT
                )
                assert r.status_code == 422, f"visibility={bad!r} gave {r.status_code}"
                assert_error_envelope(r.json(), "validation_failed")
                self._assert_state_unchanged(ctx, token)

    def test_request_unknown_user(self):
        with running_container() as ctx:
            reset(ctx, eur_fixture())
            token = login(ctx, "ada@example.com", "correct horse")["token"]
            fixture = eur_fixture()
            fixture["requests"][0]["payer_id"] = "u_nobody"
            r = requests.post(
                f"{ctx['url']}/_test/reset", json=fixture, timeout=RESET_TIMEOUT
            )
            assert r.status_code == 422
            assert_error_envelope(r.json(), "validation_failed")
            self._assert_state_unchanged(ctx, token)

    def test_request_invalid_amount(self):
        with running_container() as ctx:
            reset(ctx, eur_fixture())
            token = login(ctx, "ada@example.com", "correct horse")["token"]
            for bad in [-1, "1200", 1.5, 1000000001]:
                fixture = eur_fixture()
                fixture["requests"][0]["amount"] = bad
                r = requests.post(
                    f"{ctx['url']}/_test/reset", json=fixture, timeout=RESET_TIMEOUT
                )
                assert r.status_code == 422, f"amount={bad} gave {r.status_code}"
                assert_error_envelope(r.json(), "validation_failed")
                self._assert_state_unchanged(ctx, token)

    def test_request_invalid_status(self):
        with running_container() as ctx:
            reset(ctx, eur_fixture())
            token = login(ctx, "ada@example.com", "correct horse")["token"]
            for bad in ["done", "", None]:
                fixture = eur_fixture()
                fixture["requests"][0]["status"] = bad
                r = requests.post(
                    f"{ctx['url']}/_test/reset", json=fixture, timeout=RESET_TIMEOUT
                )
                assert r.status_code == 422, f"status={bad!r} gave {r.status_code}"
                assert_error_envelope(r.json(), "validation_failed")
                self._assert_state_unchanged(ctx, token)

    def test_total_balance_above_2_53(self):
        with running_container() as ctx:
            reset(ctx, eur_fixture())
            token = login(ctx, "ada@example.com", "correct horse")["token"]
            fixture = eur_fixture()
            fixture["users"][0]["balance"] = 2**53
            fixture["users"][1]["balance"] = 1
            r = requests.post(
                f"{ctx['url']}/_test/reset", json=fixture, timeout=RESET_TIMEOUT
            )
            assert r.status_code == 422
            assert_error_envelope(r.json(), "validation_failed")
            self._assert_state_unchanged(ctx, token)

    def test_unparseable_body(self):
        with running_container() as ctx:
            reset(ctx, eur_fixture())
            token = login(ctx, "ada@example.com", "correct horse")["token"]
            r = requests.post(
                f"{ctx['url']}/_test/reset",
                data="not json",
                headers={"Content-Type": "application/json"},
                timeout=RESET_TIMEOUT,
            )
            assert r.status_code == 400
            assert_json_content_type(r)
            assert_error_envelope(r.json(), "malformed_request")
            self._assert_state_unchanged(ctx, token)

    def test_body_not_an_object(self):
        with running_container() as ctx:
            reset(ctx, eur_fixture())
            token = login(ctx, "ada@example.com", "correct horse")["token"]
            for bad in ([], "string", 123):
                r = requests.post(
                    f"{ctx['url']}/_test/reset", json=bad, timeout=RESET_TIMEOUT
                )
                assert r.status_code == 400, f"body={bad!r} gave {r.status_code}"
                assert_error_envelope(r.json(), "malformed_request")
                self._assert_state_unchanged(ctx, token)

    def test_unknown_fields_ignored_on_reset(self):
        with running_container() as ctx:
            fixture = eur_fixture()
            fixture["extra_field"] = "ignored"
            fixture["users"][0]["extra"] = "ignored"
            r = requests.post(
                f"{ctx['url']}/_test/reset", json=fixture, timeout=RESET_TIMEOUT
            )
            assert r.status_code == 204


class TestLoginValidation:
    """Criterion 5: login error cases."""

    def test_wrong_password(self):
        with running_container() as ctx:
            reset(ctx, eur_fixture())
            r = requests.post(
                f"{ctx['url']}/auth/login",
                json={"email": "ada@example.com", "password": "wrong"},
                timeout=REQUEST_TIMEOUT,
            )
            assert r.status_code == 401
            assert_error_envelope(r.json(), "unauthenticated")

    def test_unknown_email(self):
        with running_container() as ctx:
            reset(ctx, eur_fixture())
            r = requests.post(
                f"{ctx['url']}/auth/login",
                json={"email": "nobody@example.com", "password": "correct horse"},
                timeout=REQUEST_TIMEOUT,
            )
            assert r.status_code == 401
            assert_error_envelope(r.json(), "unauthenticated")

    def test_email_wrong_type(self):
        with running_container() as ctx:
            reset(ctx, eur_fixture())
            r = requests.post(
                f"{ctx['url']}/auth/login",
                json={"email": 5, "password": "correct horse"},
                timeout=REQUEST_TIMEOUT,
            )
            assert r.status_code == 400
            assert_error_envelope(r.json(), "malformed_request")

    def test_missing_password(self):
        with running_container() as ctx:
            reset(ctx, eur_fixture())
            r = requests.post(
                f"{ctx['url']}/auth/login",
                json={"email": "ada@example.com"},
                timeout=REQUEST_TIMEOUT,
            )
            assert r.status_code == 422
            assert_error_envelope(r.json(), "validation_failed")

    def test_unknown_fields_ignored_on_login(self):
        with running_container() as ctx:
            reset(ctx, eur_fixture())
            r = requests.post(
                f"{ctx['url']}/auth/login",
                json={
                    "email": "ada@example.com",
                    "password": "correct horse",
                    "extra": "ignored",
                },
                timeout=REQUEST_TIMEOUT,
            )
            assert r.status_code == 200
            assert "token" in r.json()

    def test_case_insensitive_email_lookup(self):
        with running_container() as ctx:
            reset(ctx, eur_fixture())
            for email in ["ADA@EXAMPLE.COM", "Ada@Example.COM", "ada@example.com"]:
                r = requests.post(
                    f"{ctx['url']}/auth/login",
                    json={"email": email, "password": "correct horse"},
                    timeout=REQUEST_TIMEOUT,
                )
                assert r.status_code == 200, f"email {email!r} failed"
                assert r.json()["user_id"] == "u_ada"


class TestMeAuthentication:
    """Criterion 6: /me rejects bad/missing auth."""

    def test_no_authorization(self):
        with running_container() as ctx:
            reset(ctx, eur_fixture())
            r = requests.get(f"{ctx['url']}/me", timeout=REQUEST_TIMEOUT)
            assert r.status_code == 401
            assert_error_envelope(r.json(), "unauthenticated")

    def test_bearer_no_token(self):
        with running_container() as ctx:
            reset(ctx, eur_fixture())
            r = requests.get(
                f"{ctx['url']}/me",
                headers={"Authorization": "Bearer"},
                timeout=REQUEST_TIMEOUT,
            )
            assert r.status_code == 401
            assert_error_envelope(r.json(), "unauthenticated")

    def test_basic_auth_rejected(self):
        with running_container() as ctx:
            reset(ctx, eur_fixture())
            r = requests.get(
                f"{ctx['url']}/me",
                headers={"Authorization": "Basic dXNlcjpwYXNz"},
                timeout=REQUEST_TIMEOUT,
            )
            assert r.status_code == 401
            assert_error_envelope(r.json(), "unauthenticated")

    def test_unknown_token(self):
        with running_container() as ctx:
            reset(ctx, eur_fixture())
            r = requests.get(
                f"{ctx['url']}/me",
                headers={"Authorization": "Bearer not_a_real_token"},
                timeout=REQUEST_TIMEOUT,
            )
            assert r.status_code == 401
            assert_error_envelope(r.json(), "unauthenticated")


class TestConcurrentSessions:
    """Criterion 7: multiple tokens for the same user work concurrently."""

    def test_two_logins_both_work(self):
        with running_container() as ctx:
            reset(ctx, eur_fixture())
            t1 = login(ctx, "ada@example.com", "correct horse")["token"]
            t2 = login(ctx, "ada@example.com", "correct horse")["token"]
            assert t1 != t2

            for token in (t1, t2):
                r = me(ctx, token)
                assert r.status_code == 200
                assert r.json()["user_id"] == "u_ada"


class TestPasswordStorage:
    """Criterion 8: no plaintext password in DB (black-box + code review)."""

    def test_no_plaintext_password_in_database(self):
        with running_container() as ctx:
            reset(ctx, eur_fixture())
            probe = docker(
                [
                    "exec",
                    ctx["container_id"],
                    "python",
                    "-c",
                    (
                        "import sqlite3; conn = sqlite3.connect('/tmp/pocketful/pocketful.sqlite3'); "
                        "cur = conn.execute('SELECT sql FROM sqlite_master WHERE type=\\'table\\''); "
                        "tables = [r[0] for r in cur.fetchall()]; "
                        "cur = conn.execute(\"SELECT name FROM sqlite_master WHERE type='table' AND name='users'\"); "
                        "print('users' if cur.fetchone() else 'no users table')"
                    ),
                ],
                timeout=5,
            )
            assert probe.returncode == 0
            assert "users" in probe.stdout
            probe = docker(
                [
                    "exec",
                    ctx["container_id"],
                    "python",
                    "-c",
                    (
                        "import sqlite3; conn = sqlite3.connect('/tmp/pocketful/pocketful.sqlite3'); "
                        "cur = conn.execute('SELECT password_hash FROM users WHERE email=\\'ada@example.com\\''); "
                        "row = cur.fetchone(); print(row[0] if row else 'missing')"
                    ),
                ],
                timeout=5,
            )
            assert probe.returncode == 0
            stored = probe.stdout.strip()
            assert stored != "correct horse"
            assert stored != "missing"


class TestPerformance:
    """Criterion 9: 200-user reset under 10 s; 50 concurrent logins under 5 s each."""

    def _fixture_with_n_users(self, n: int):
        users = []
        for i in range(n):
            users.append(
                {
                    "id": f"u_{i}",
                    "email": f"user{i}@example.com",
                    "password": f"password{i}",
                    "display_name": f"User {i}",
                    "handle": f"user{i}",
                    "balance": 1000,
                }
            )
        return {
            "currency": "EUR",
            "minor_units": 2,
            "users": users,
        }

    def test_reset_200_users(self):
        with running_container() as ctx:
            fixture = self._fixture_with_n_users(200)
            start = time.monotonic()
            reset(ctx, fixture)
            elapsed = time.monotonic() - start
            assert elapsed < 10, f"200-user reset took {elapsed:.2f}s"

    def test_50_concurrent_logins(self):
        with running_container() as ctx:
            fixture = self._fixture_with_n_users(50)
            reset(ctx, fixture)
            results, errors = [], []

            def do_login(i: int):
                try:
                    results.append(
                        requests.post(
                            f"{ctx['url']}/auth/login",
                            json={
                                "email": f"user{i}@example.com",
                                "password": f"password{i}",
                            },
                            timeout=REQUEST_TIMEOUT,
                        )
                    )
                except Exception as exc:
                    errors.append(exc)

            start = time.monotonic()
            threads = [threading.Thread(target=do_login, args=(i,)) for i in range(50)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
            elapsed = time.monotonic() - start
            assert elapsed <= REQUEST_TIMEOUT, f"50 concurrent logins took {elapsed:.2f}s"
            assert not errors
            assert len(results) == 50
            for r in results:
                assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
                assert "token" in r.json()


class TestPublicEndpointsRequireNoToken:
    """Criterion 10: /health and /_test/reset need no token."""

    def test_health_no_token(self):
        with running_container() as ctx:
            r = requests.get(f"{ctx['url']}/health", timeout=REQUEST_TIMEOUT)
            assert r.status_code == 200
            assert r.json() == {"status": "ok"}

    def test_reset_no_token(self):
        with running_container() as ctx:
            r = requests.post(
                f"{ctx['url']}/_test/reset", json=eur_fixture(), timeout=RESET_TIMEOUT
            )
            assert r.status_code == 204