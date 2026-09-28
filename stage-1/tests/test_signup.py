from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest

from app.users import derive_handle, is_valid_email
from conftest import FIXTURE, JSON_UTF8, assert_error, fixture


@pytest.fixture
def seeded(client):
    assert client.post("/_test/reset", json=FIXTURE).status_code == 204
    return client


def signup(client, email="Zoe.Q+x@example.com", password="correct horse", display_name="Zoë"):
    return client.post("/auth/signup", json={"email": email, "password": password,
                                             "display_name": display_name})


def me(client, token):
    return client.get("/me", headers={"Authorization": f"Bearer {token}"})


@pytest.mark.parametrize("email,handle", [
    ("Zoe.Q+x@example.com", "zoe_q_x"),
    ("ÄBC@x.io", "_bc"),
    ("abcdefghijklmnopqrstuvwxyz@x.io", "abcdefghijklmnopqrst"),
    ("a_1@x.io", "a_1"),
])
def test_derive_handle(email, handle):
    assert derive_handle(email) == handle


@pytest.mark.parametrize("email,ok", [
    ("a@b", True), ("a.b+c@d.e", True), ("noat", False), ("@x.io", False), ("a@", False),
    ("a@@b", False), ("a@b@c", False), ("a b@c.d", False), ("a@c.d\t", False), ("", False),
])
def test_email_form(email, ok):
    assert is_valid_email(email) is ok


def test_signup_then_me(seeded):
    resp = signup(seeded)
    assert resp.status_code == 201
    assert resp.headers["content-type"] == JSON_UTF8
    body = resp.json()
    assert set(body) == {"user_id", "display_name", "token"}
    assert isinstance(body["user_id"], str) and 0 < len(body["user_id"]) <= 64
    assert body["display_name"] == "Zoë" and body["token"]
    assert me(seeded, body["token"]).json() == {
        "user_id": body["user_id"], "display_name": "Zoë", "handle": "zoe_q_x",
        "balance": 0, "currency": "EUR", "minor_units": 2}


def test_signup_login_any_case_and_both_tokens_work(seeded):
    first = signup(seeded).json()
    for email in ("Zoe.Q+x@example.com", "zoe.q+X@EXAMPLE.com"):
        resp = seeded.post("/auth/login", json={"email": email, "password": "correct horse"})
        assert resp.status_code == 200
        assert resp.json()["user_id"] == first["user_id"]
        assert resp.json()["token"] != first["token"]
        assert me(seeded, resp.json()["token"]).status_code == 200
    assert me(seeded, first["token"]).status_code == 200


@pytest.mark.parametrize("email", ["ada@example.com", "ADA@Example.COM"])
def test_seeded_email_taken(seeded, email):
    assert_error(signup(seeded, email=email), 409, "email_taken")


def test_signed_up_email_taken_any_case(seeded):
    assert signup(seeded).status_code == 201
    assert_error(signup(seeded, email="ZOE.q+x@example.com"), 409, "email_taken")


def test_handle_taken_creates_nothing(seeded):
    assert_error(signup(seeded, email="ada@other.org"), 409, "handle_taken")
    resp = seeded.post("/auth/login", json={"email": "ada@other.org", "password": "correct horse"})
    assert_error(resp, 401, "unauthenticated")


def test_email_taken_outranks_handle_taken(seeded):
    # ada@example.com is both a taken email and a taken handle.
    assert_error(signup(seeded, email="ada@example.com"), 409, "email_taken")


def test_password_length(seeded):
    assert_error(signup(seeded, password="1234567"), 422, "validation_failed")
    assert_error(signup(seeded, password="😀" * 7), 422, "validation_failed")
    assert signup(seeded, password="😀" * 8).status_code == 201


def test_password_exactly_8(seeded):
    assert signup(seeded, password="12345678").status_code == 201


@pytest.mark.parametrize("email", ["noat", "@x.io", "a@", "a@@b", "a b@c.d"])
def test_bad_email_form(seeded, email):
    assert_error(signup(seeded, email=email), 422, "validation_failed")


@pytest.mark.parametrize("body", [
    {"email": 1, "password": "correct horse", "display_name": "Z"},
    {"email": "z@x.io", "password": None, "display_name": "Z"},
    {"email": "z@x.io", "password": "correct horse", "display_name": []},
    {"email": "z@x.io", "display_name": 5},  # wrong type outranks missing
])
def test_wrong_types_are_400(seeded, body):
    assert_error(seeded.post("/auth/signup", json=body), 400, "malformed_request")


@pytest.mark.parametrize("missing", ["email", "password", "display_name"])
def test_missing_field_is_422(seeded, missing):
    body = {"email": "z@x.io", "password": "correct horse", "display_name": "Z"}
    del body[missing]
    assert_error(seeded.post("/auth/signup", json=body), 422, "validation_failed")


@pytest.mark.parametrize("raw", [b"{", b"[1]", b"\xff"])
def test_unparseable_is_400(seeded, raw):
    assert_error(seeded.post("/auth/signup", content=raw), 400, "malformed_request")


def test_unknown_fields_ignored_and_empty_display_name(seeded):
    resp = seeded.post("/auth/signup", json={"email": "z@x.io", "password": "correct horse",
                                             "display_name": "", "handle": "nope"})
    assert resp.status_code == 201
    assert me(seeded, resp.json()["token"]).json()["handle"] == "z"


def test_generated_id_avoids_seeded_ids(client):
    users = [dict(FIXTURE["users"][0], id="u_1")]
    assert client.post("/_test/reset", json=fixture(users=users, payments=[],
                                                    requests=[])).status_code == 204
    assert signup(client).json()["user_id"] != "u_1"


def test_concurrent_same_email(seeded):
    with ThreadPoolExecutor(20) as pool:
        codes = list(pool.map(lambda _: signup(seeded).status_code, range(20)))
    assert sorted(codes) == [201] + [409] * 19


def test_concurrent_same_handle(seeded):
    emails = [f"Zed@host{i}.io" for i in range(20)]
    with ThreadPoolExecutor(20) as pool:
        resps = list(pool.map(lambda e: signup(seeded, email=e), emails))
    assert sorted(r.status_code for r in resps) == [201] + [409] * 19
    assert {r.json()["error"]["code"] for r in resps if r.status_code == 409} == {"handle_taken"}


def test_reset_removes_signed_up_users(seeded):
    token = signup(seeded).json()["token"]
    assert seeded.post("/_test/reset", json=FIXTURE).status_code == 204
    assert_error(me(seeded, token), 401, "unauthenticated")
    resp = seeded.post("/auth/login", json={"email": "Zoe.Q+x@example.com",
                                            "password": "correct horse"})
    assert_error(resp, 401, "unauthenticated")
