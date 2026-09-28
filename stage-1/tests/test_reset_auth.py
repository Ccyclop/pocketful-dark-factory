from __future__ import annotations

import copy
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from conftest import FIXTURE, JSON_UTF8, assert_error, fixture

ADA = {"email": "ada@example.com", "password": "correct horse"}


def reset(client, body):
    return client.post("/_test/reset", json=body)


def login(client, email="ada@example.com", password="correct horse"):
    return client.post("/auth/login", json={"email": email, "password": password})


def token_for(client, email="ada@example.com"):
    resp = login(client, email)
    assert resp.status_code == 200, resp.text
    return resp.json()["token"]


def me(client, token):
    return client.get("/me", headers={"Authorization": f"Bearer {token}"})


def test_reset_login_me(client):
    resp = reset(client, FIXTURE)
    assert resp.status_code == 204 and resp.content == b""
    resp = login(client)
    assert resp.status_code == 200
    assert resp.headers["content-type"] == JSON_UTF8
    body = resp.json()
    assert set(body) == {"user_id", "display_name", "token"}
    assert body["user_id"] == "u_ada" and body["display_name"] == "Ada"
    assert isinstance(body["token"], str) and body["token"]
    resp = me(client, body["token"])
    assert resp.status_code == 200
    assert resp.json() == {"user_id": "u_ada", "display_name": "Ada", "handle": "ada",
                           "balance": 10000, "currency": "EUR", "minor_units": 2}


@pytest.mark.parametrize("currency,minor_units", [("JPY", 0), ("BHD", 3)])
def test_currency_reflected(client, currency, minor_units):
    assert reset(client, fixture(currency=currency, minor_units=minor_units)).status_code == 204
    body = me(client, token_for(client)).json()
    assert (body["currency"], body["minor_units"]) == (currency, minor_units)


def test_reset_replaces_everything(client):
    reset(client, FIXTURE)
    old = token_for(client)
    other = fixture(users=[{"id": "u_cy", "email": "cy@example.com", "password": "pw-cy-123",
                            "display_name": "Cy", "handle": "cy", "balance": 7}],
                    payments=[], requests=[])
    assert reset(client, other).status_code == 204
    assert_error(login(client), 401, "unauthenticated")
    assert_error(me(client, old), 401, "unauthenticated")
    token = token_for_pw(client, "cy@example.com", "pw-cy-123")
    assert me(client, token).json()["balance"] == 7


def token_for_pw(client, email, password):
    resp = login(client, email, password)
    assert resp.status_code == 200, resp.text
    return resp.json()["token"]


def _users(*changes):
    users = copy.deepcopy(FIXTURE["users"])
    for i, key, value in changes:
        if value is _DROP:
            users[i].pop(key)
        else:
            users[i][key] = value
    return users


_DROP = object()

INVALID_FIXTURES = {
    "negative balance": fixture(users=_users((0, "balance", -1))),
    "fractional balance": fixture(users=_users((0, "balance", 1.5))),
    "string balance": fixture(users=_users((0, "balance", "100"))),
    "bool balance": fixture(users=_users((0, "balance", True))),
    "minor_units 1": fixture(minor_units=1),
    "minor_units string": fixture(minor_units="2"),
    "missing currency": {k: v for k, v in FIXTURE.items() if k != "currency"},
    "missing minor_units": {k: v for k, v in FIXTURE.items() if k != "minor_units"},
    "missing users": {k: v for k, v in FIXTURE.items() if k != "users"},
    "users not array": fixture(users={}),
    "user not object": fixture(users=["u_ada"]),
    "user missing id": fixture(users=_users((0, "id", _DROP))),
    "user missing email": fixture(users=_users((0, "email", _DROP))),
    "user missing password": fixture(users=_users((0, "password", _DROP))),
    "user missing handle": fixture(users=_users((0, "handle", _DROP))),
    "user missing balance": fixture(users=_users((0, "balance", _DROP))),
    "bad handle upper": fixture(users=_users((0, "handle", "Ada"))),
    "bad handle long": fixture(users=_users((0, "handle", "a" * 21))),
    "bad handle newline": fixture(users=_users((0, "handle", "ada\n"))),
    "duplicate id": fixture(users=_users((1, "id", "u_ada")), payments=[], requests=[]),
    "duplicate handle": fixture(users=_users((1, "handle", "ada"))),
    "duplicate email": fixture(users=_users((1, "email", "ADA@example.com"))),
    "total above 2^53": fixture(users=_users((0, "balance", 2 ** 53), (1, "balance", 1))),
    "payment unknown user": fixture(payments=[dict(FIXTURE["payments"][0], to_user_id="u_x")]),
    "payment bad amount": fixture(payments=[dict(FIXTURE["payments"][0], amount=0)]),
    "payment bad visibility": fixture(payments=[dict(FIXTURE["payments"][0],
                                                     visibility="friends")]),
    "request unknown user": fixture(requests=[dict(FIXTURE["requests"][0], payer_id="u_x")]),
    "request bad amount": fixture(requests=[dict(FIXTURE["requests"][0], amount=-5)]),
    "request bad status": fixture(requests=[dict(FIXTURE["requests"][0], status="open")]),
}


@pytest.mark.parametrize("name", INVALID_FIXTURES)
def test_invalid_fixture_changes_nothing(client, name):
    reset(client, FIXTURE)
    token = token_for(client)
    assert_error(reset(client, INVALID_FIXTURES[name]), 422, "validation_failed")
    assert me(client, token).json()["balance"] == 10000
    assert login(client).status_code == 200


@pytest.mark.parametrize("raw", [b"{", b"[]", b"\"x\"", b"\xff\xfe", b"", b"NaN"])
def test_unparseable_reset_is_400(client, raw):
    reset(client, FIXTURE)
    token = token_for(client)
    assert_error(client.post("/_test/reset", content=raw), 400, "malformed_request")
    assert me(client, token).status_code == 200


def test_fixture_defaults_and_integral_numbers(client):
    body = fixture(minor_units=2.0, users=_users((0, "balance", 1e4)))
    del body["payments"], body["requests"]
    body["unknown"] = {"x": 1}
    assert reset(client, body).status_code == 204
    assert me(client, token_for(client)).json()["balance"] == 10000


def test_seeded_rows_stored(app, client):
    reset(client, fixture(settlement_operator_ids=["u_bob", "u_nobody"]))
    conn = app.state.db.connection()
    payment = conn.execute("SELECT * FROM payments").fetchone()
    assert (payment["id"], payment["amount"], payment["request_id"],
            payment["settlement_id"]) == ("p_1", 500, None, None)
    request = conn.execute("SELECT * FROM requests").fetchone()
    assert (request["id"], request["status"], request["payment_id"]) == ("rq_1", "pending",
                                                                         None)
    ops = [r["id"] for r in conn.execute("SELECT id FROM users WHERE is_operator = 1")]
    assert ops == ["u_bob"]
    stored = [r["password_hash"] for r in conn.execute("SELECT password_hash FROM users")]
    assert all(h.startswith("scrypt$") and "correct horse" not in h for h in stored)
    assert len(set(stored)) == len(stored)  # salted


def test_login_errors(client):
    reset(client, FIXTURE)
    assert_error(login(client, password="wrong horse"), 401, "unauthenticated")
    assert_error(login(client, email="nobody@example.com"), 401, "unauthenticated")
    assert_error(client.post("/auth/login", json={"email": 5, "password": "x"}),
                 400, "malformed_request")
    assert_error(client.post("/auth/login", json={"email": None, "password": "x"}),
                 400, "malformed_request")
    assert_error(client.post("/auth/login", json={"email": "ada@example.com"}),
                 422, "validation_failed")
    assert_error(client.post("/auth/login", content=b"{nope"), 400, "malformed_request")
    assert_error(client.post("/auth/login", json=["x"]), 400, "malformed_request")
    resp = client.post("/auth/login", json={**ADA, "extra": [1, 2]})
    assert resp.status_code == 200
    assert login(client, email="ADA@Example.com").status_code == 200


@pytest.mark.parametrize("header", [None, "Bearer", "Bearer ", "Basic xyz", "Bearer nope",
                                    "Bearer a b", "token"])
def test_me_rejects_bad_auth(client, header):
    reset(client, FIXTURE)
    headers = {} if header is None else {"Authorization": header}
    assert_error(client.get("/me", headers=headers), 401, "unauthenticated")


def test_two_tokens_both_work(client):
    reset(client, FIXTURE)
    a, b = token_for(client), token_for(client)
    assert a != b
    with ThreadPoolExecutor(8) as pool:
        results = list(pool.map(lambda t: me(client, t).status_code, [a, b] * 10))
    assert results == [200] * 20


def test_reset_200_users_is_fast(client):
    users = [{"id": f"u_{i}", "email": f"user{i}@example.com", "password": "correct horse",
              "display_name": f"User {i}", "handle": f"user_{i}", "balance": 100}
             for i in range(200)]
    started = time.monotonic()
    assert reset(client, {"currency": "EUR", "minor_units": 2, "users": users}).status_code == 204
    assert time.monotonic() - started < 10
    assert login(client, "user199@example.com").status_code == 200
