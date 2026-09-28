"""Black-box acceptance tests for WI-1.3 — signup."""

import threading
import time

import pytest
import requests

from conftest import (
    REQUEST_TIMEOUT,
    assert_error_envelope,
    assert_json_content_type,
    eur_fixture,
    login,
    me,
    reset,
    running_container,
    signup,
)


class TestSignupSuccess:
    """Criteria 1-3: successful signup, handle derivation, login."""

    def test_signup_basic(self):
        with running_container() as ctx:
            reset(ctx, eur_fixture())
            r = signup(ctx, "Zoe.Q+x@example.com", "correct horse", "Zoë")
            assert r.status_code == 201
            assert_json_content_type(r)
            body = r.json()
            assert set(body.keys()) == {"user_id", "display_name", "token"}
            assert isinstance(body["user_id"], str) and len(body["user_id"]) <= 64
            assert body["display_name"] == "Zoë"
            assert isinstance(body["token"], str) and body["token"]

            r = me(ctx, body["token"])
            assert r.status_code == 200
            body = r.json()
            assert body["handle"] == "zoe_q_x"
            assert body["balance"] == 0
            assert body["currency"] == "EUR"
            assert body["minor_units"] == 2

    def test_handle_truncation(self):
        with running_container() as ctx:
            reset(ctx, eur_fixture())
            local = "a_very_long_local_part_with_many_chars"
            r = signup(ctx, f"{local}@example.com", "correct horse", "Long")
            assert r.status_code == 201
            token = r.json()["token"]
            assert me(ctx, token).json()["handle"] == local[:20]

    def test_non_ascii_local_part(self):
        with running_container() as ctx:
            reset(ctx, eur_fixture())
            r = signup(ctx, "ÄBC@x.io", "correct horse", "ABC")
            assert r.status_code == 201
            token = r.json()["token"]
            assert me(ctx, token).json()["handle"] == "_bc"

    def test_new_user_can_login(self):
        with running_container() as ctx:
            reset(ctx, eur_fixture())
            signup_token = signup(ctx, "zoe@example.com", "correct horse", "Zoe").json()["token"]

            for email in ["zoe@example.com", "ZOE@EXAMPLE.COM", "Zoe@Example.com"]:
                login_resp = login(ctx, email, "correct horse")
                assert login_resp["user_id"]
                assert login_resp["display_name"] == "Zoe"

            for token in (signup_token, login_resp["token"]):
                r = me(ctx, token)
                assert r.status_code == 200
                assert r.json()["handle"] == "zoe"


class TestSignupConflict:
    """Criteria 4-5: email_taken and handle_taken."""

    def test_email_already_registered(self):
        with running_container() as ctx:
            reset(ctx, eur_fixture())
            for email in ["ada@example.com", "ADA@EXAMPLE.COM", "Ada@Example.com"]:
                r = signup(ctx, email, "correct horse", "Ada2")
                assert r.status_code == 409
                assert_error_envelope(r.json(), "email_taken")

    def test_email_taken_after_signup(self):
        with running_container() as ctx:
            reset(ctx, eur_fixture())
            assert signup(ctx, "zoe@example.com", "correct horse", "Zoe").status_code == 201
            r = signup(ctx, "zoe@example.com", "different pw", "Zoe2")
            assert r.status_code == 409
            assert_error_envelope(r.json(), "email_taken")
            r2 = signup(ctx, "ZOE@EXAMPLE.COM", "different pw", "Zoe2")
            assert r2.status_code == 409
            assert_error_envelope(r2.json(), "email_taken")

    def test_handle_taken_by_seeded_user(self):
        with running_container() as ctx:
            reset(ctx, eur_fixture())
            r = signup(ctx, "ada@other.org", "correct horse", "Other Ada")
            assert r.status_code == 409
            assert_error_envelope(r.json(), "handle_taken")

            r = requests.post(
                f"{ctx['url']}/auth/login",
                json={"email": "ada@other.org", "password": "correct horse"},
                timeout=REQUEST_TIMEOUT,
            )
            assert r.status_code == 401
            assert_error_envelope(r.json(), "unauthenticated")

    def test_handle_taken_by_signed_up_user(self):
        with running_container() as ctx:
            reset(ctx, eur_fixture())
            assert signup(ctx, "first.zoe@example.com", "correct horse", "Zoe").status_code == 201
            r = signup(ctx, "first_zoe@example.com", "correct horse", "Zoe2")
            assert r.status_code == 409
            assert_error_envelope(r.json(), "handle_taken")


class TestSignupValidation:
    """Criteria 6-7: password length, email form, types, missing fields."""

    def test_password_length(self):
        with running_container() as ctx:
            reset(ctx, eur_fixture())
            r = signup(ctx, "shortpw@example.com", "1234567", "X")
            assert r.status_code == 422
            assert_error_envelope(r.json(), "validation_failed")

            r = signup(ctx, "okpw@example.com", "12345678", "X")
            assert r.status_code == 201

    def test_invalid_email(self):
        with running_container() as ctx:
            reset(ctx, eur_fixture())
            for bad in ["noat", "@x.io", "a@", "a@@b", "a b@c.d"]:
                r = signup(ctx, bad, "correct horse", "X")
                assert r.status_code == 422, f"email {bad!r} gave {r.status_code}"
                assert_error_envelope(r.json(), "validation_failed")

    def test_wrong_field_types(self):
        with running_container() as ctx:
            reset(ctx, eur_fixture())
            for field, value in [("email", 1), ("password", None), ("display_name", [])]:
                body = {
                    "email": "type@example.com",
                    "password": "correct horse",
                    "display_name": "Type",
                }
                body[field] = value
                r = requests.post(
                    f"{ctx['url']}/auth/signup", json=body, timeout=REQUEST_TIMEOUT
                )
                assert r.status_code == 400, f"{field}={value!r} gave {r.status_code}"
                assert_error_envelope(r.json(), "malformed_request")

    def test_missing_fields(self):
        with running_container() as ctx:
            reset(ctx, eur_fixture())
            base = {"email": "missing@example.com", "password": "correct horse", "display_name": "X"}
            for field in ("email", "password", "display_name"):
                body = dict(base)
                del body[field]
                r = requests.post(
                    f"{ctx['url']}/auth/signup", json=body, timeout=REQUEST_TIMEOUT
                )
                assert r.status_code == 422, f"missing {field} gave {r.status_code}"
                assert_error_envelope(r.json(), "validation_failed")

    def test_unparseable_body(self):
        with running_container() as ctx:
            reset(ctx, eur_fixture())
            r = requests.post(
                f"{ctx['url']}/auth/signup",
                data="not json",
                headers={"Content-Type": "application/json"},
                timeout=REQUEST_TIMEOUT,
            )
            assert r.status_code == 400
            assert_error_envelope(r.json(), "malformed_request")

    def test_unknown_fields_ignored(self):
        with running_container() as ctx:
            reset(ctx, eur_fixture())
            r = requests.post(
                f"{ctx['url']}/auth/signup",
                json={
                    "email": "extra@example.com",
                    "password": "correct horse",
                    "display_name": "Extra",
                    "extra": "ignored",
                },
                timeout=REQUEST_TIMEOUT,
            )
            assert r.status_code == 201


class TestConcurrentSignup:
    """Criterion 8: concurrent signups with same email or same derived handle."""

    def test_concurrent_same_email(self):
        with running_container() as ctx:
            reset(ctx, eur_fixture())
            results, errors = [], []

            def do_signup():
                try:
                    results.append(
                        signup(ctx, "race@example.com", "correct horse", "Race")
                    )
                except Exception as exc:
                    errors.append(exc)

            threads = [threading.Thread(target=do_signup) for _ in range(20)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            assert not errors
            statuses = [r.status_code for r in results]
            assert statuses.count(201) == 1
            assert statuses.count(409) == 19
            assert all(r.json()["error"]["code"] == "email_taken" for r in results if r.status_code == 409)
            assert not any(r.status_code >= 500 for r in results)

    def test_concurrent_same_handle(self):
        with running_container() as ctx:
            reset(ctx, eur_fixture())
            results, errors = [], []

            def do_signup(i: int):
                try:
                    # Same local part on different domains -> same handle "race_x",
                    # but each email is unique.
                    results.append(
                        signup(ctx, f"race.x@{i}.example.com", "correct horse", "Race")
                    )
                except Exception as exc:
                    errors.append(exc)

            threads = [threading.Thread(target=do_signup, args=(i,)) for i in range(20)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            assert not errors
            statuses = [r.status_code for r in results]
            assert statuses.count(201) == 1
            assert statuses.count(409) == 19
            assert all(r.json()["error"]["code"] == "handle_taken" for r in results if r.status_code == 409)
            assert not any(r.status_code >= 500 for r in results)


class TestResetRemovesSignedUpUsers:
    """Criterion 9: reset clears signed-up users."""

    def test_reset_after_signup(self):
        with running_container() as ctx:
            reset(ctx, eur_fixture())
            token = signup(ctx, "zoe@example.com", "correct horse", "Zoe").json()["token"]
            assert me(ctx, token).status_code == 200

            reset(ctx, eur_fixture())
            assert me(ctx, token).status_code == 401
            r = requests.post(
                f"{ctx['url']}/auth/login",
                json={"email": "zoe@example.com", "password": "correct horse"},
                timeout=REQUEST_TIMEOUT,
            )
            assert r.status_code == 401
            assert_error_envelope(r.json(), "unauthenticated")
