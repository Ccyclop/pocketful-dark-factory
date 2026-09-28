from __future__ import annotations

import json
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest

from app.timeutil import parse_rfc3339
from conftest import JSON_UTF8, assert_error, fixture
from test_payments import USERS3, Client

SEEDED = [
    {"id": "rq_p", "requester_id": "u_bob", "payer_id": "u_ada", "amount": 10, "status": "pending"},
    {"id": "rq_paid", "requester_id": "u_ada", "payer_id": "u_bob", "amount": 20,
     "status": "paid"},
    {"id": "rq_d", "requester_id": "u_bob", "payer_id": "u_ada", "amount": 30,
     "status": "declined"},
    {"id": "rq_c", "requester_id": "u_ada", "payer_id": "u_bob", "amount": 40,
     "status": "cancelled"},
]


def ask(c, idem=..., raw=None, **body):
    headers = {"Authorization": f"Bearer {c.token}"}
    if idem is ...:
        idem = uuid.uuid4().hex
    if idem is not None:
        headers["Idempotency-Key"] = idem
    if raw is not None:
        return c.http.post("/requests", content=raw, headers=headers)
    return c.http.post("/requests", json=body, headers=headers)


def listing(c, **params):
    return c.http.get("/requests", params=params, headers={"Authorization": f"Bearer {c.token}"})


def ids(c, **params):
    resp = listing(c, **params)
    assert resp.status_code == 200, resp.text
    return [r["request_id"] for r in resp.json()["requests"]]


@pytest.fixture
def world(client):
    users = [dict(u) for u in USERS3]
    users[0]["balance"] = 100
    assert client.post("/_test/reset", json=fixture(users=users, payments=[],
                                                    requests=[])).status_code == 204
    return {h: Client(client, f"{h}@example.com") for h in ("ada", "bob", "cy")}


@pytest.fixture
def seeded(client):
    assert client.post("/_test/reset", json=fixture(users=USERS3, payments=[],
                                                    requests=SEEDED)).status_code == 204
    return {h: Client(client, f"{h}@example.com") for h in ("ada", "bob", "cy")}


def test_create_request(world):
    bob, ada = world["bob"], world["ada"]
    resp = ask(bob, payer_handle="ada", amount=1200, note="taxi")
    assert resp.status_code == 201
    assert resp.headers["content-type"] == JSON_UTF8
    body = resp.json()
    assert set(body) == {"request_id", "requester_id", "requester_handle", "payer_id",
                         "payer_handle", "amount", "currency", "note", "status", "payment_id",
                         "created_at"}
    assert 0 < len(body["request_id"]) <= 64
    assert {k: v for k, v in body.items() if k not in ("request_id", "created_at")} == {
        "requester_id": "u_bob", "requester_handle": "bob", "payer_id": "u_ada",
        "payer_handle": "ada", "amount": 1200, "currency": "EUR", "note": "taxi",
        "status": "pending", "payment_id": None}
    assert parse_rfc3339(body["created_at"])
    assert (ada.balance(), bob.balance()) == (100, 2500)
    assert ask(bob, payer_handle="ada", amount=5).json()["note"] == ""


@pytest.mark.parametrize("extra,status,code", [
    ({"amount": 0}, 422, "validation_failed"),
    ({"amount": 1_000_000_001}, 422, "validation_failed"),
    ({"amount": 1.5}, 422, "validation_failed"),
    ({"amount": "5"}, 422, "validation_failed"),
    ({"amount": True}, 422, "validation_failed"),
    ({"payer_handle": "bob"}, 422, "self_request"),
    ({"payer_handle": "nobody"}, 404, "not_found"),
    ({"payer_handle": "ADA"}, 404, "not_found"),
    ({"note": "x" * 201}, 422, "validation_failed"),
    ({"note": None}, 422, "validation_failed"),
    ({"payer_handle": 7}, 400, "malformed_request"),
    ({"payer_handle": None}, 400, "malformed_request"),
])
def test_validation(world, extra, status, code):
    body = {"payer_handle": "ada", "amount": 100, **extra}
    assert_error(ask(world["bob"], **body), status, code)


def test_missing_fields_and_bad_bodies(world):
    bob = world["bob"]
    assert_error(ask(bob, payer_handle="ada"), 422, "validation_failed")
    assert_error(ask(bob, amount=5), 422, "validation_failed")
    assert_error(ask(bob, raw=b"{nope"), 400, "malformed_request")
    assert_error(ask(bob, raw=b"[]"), 400, "malformed_request")
    assert_error(ask(bob, idem=None, payer_handle="ada", amount=5), 400,
                 "missing_idempotency_key")
    assert ask(bob, payer_handle="ada", amount=5, colour="blue").status_code == 201


def test_idempotency(world):
    bob = world["bob"]
    k = uuid.uuid4().hex
    first = ask(bob, idem=k, payer_handle="ada", amount=100)
    replay = ask(bob, idem=k, raw=b'{"amount": 100.0, "payer_handle": "ada"}')
    assert (first.status_code, replay.status_code) == (201, 200)
    assert replay.json() == first.json()
    assert len(ids(bob)) == 1
    assert_error(ask(bob, idem=k, payer_handle="ada", amount=101), 409, "idempotency_key_reuse")
    assert_error(ask(bob, idem=k, payer_handle="ada", amount=0), 409, "idempotency_key_reuse")


def test_same_key_and_body_on_payments_and_requests(world):
    bob = world["bob"]
    k = uuid.uuid4().hex
    assert bob.pay(idem=k, raw=b'{"to_handle":"ada","payer_handle":"ada","amount":10}'
                   ).status_code == 201
    assert ask(bob, idem=k, raw=b'{"to_handle":"ada","payer_handle":"ada","amount":10}'
               ).status_code == 201


def test_concurrent_identical(world):
    bob = world["bob"]
    k = uuid.uuid4().hex
    with ThreadPoolExecutor(20) as pool:
        resps = list(pool.map(lambda _: ask(bob, idem=k, payer_handle="ada", amount=7),
                              range(20)))
    assert sorted(r.status_code for r in resps) == [200] * 19 + [201]
    assert len({json.dumps(r.json(), sort_keys=True) for r in resps}) == 1
    assert len(ids(bob)) == 1


def test_directions_and_statuses(seeded):
    ada, cy = seeded["ada"], seeded["cy"]
    assert ids(ada) == ["rq_c", "rq_d", "rq_paid", "rq_p"]
    assert ids(ada, direction="incoming") == ["rq_d", "rq_p"]
    assert ids(ada, direction="outgoing") == ["rq_c", "rq_paid"]
    for status, expected in (("pending", ["rq_p"]), ("paid", ["rq_paid"]),
                             ("declined", ["rq_d"]), ("cancelled", ["rq_c"])):
        assert ids(ada, status=status) == expected
    assert ids(ada, direction="incoming", status="declined") == ["rq_d"]
    assert ids(ada, direction="outgoing", status="declined") == []
    for params in ({}, {"direction": "incoming"}, {"direction": "outgoing"},
                   {"status": "pending"}, {"status": "paid"}, {"limit": 200}):
        assert ids(cy, **params) == []
    body = listing(ada, status="paid").json()["requests"][0]
    assert (body["requester_handle"], body["payer_handle"], body["amount"], body["note"],
            body["payment_id"], body["currency"]) == ("ada", "bob", 20, "", None, "EUR")


@pytest.mark.parametrize("params", [
    {"direction": "sideways"}, {"direction": "both"}, {"direction": ""},
    {"status": "open"}, {"status": "PENDING"}, {"status": ""},
    {"limit": "0"}, {"limit": "201"}, {"limit": "-5"}, {"limit": "1e2"}, {"limit": "4.0"},
    {"limit": "+4"}, {"offset": "-1"}, {"offset": "abc"},
])
def test_bad_list_params(seeded, params):
    assert_error(listing(seeded["ada"], **params), 422, "validation_failed")


def test_unknown_params_ignored(seeded):
    assert len(ids(seeded["ada"], foo="bar", visibility="x")) == 4


def test_paging_and_newest_first(world):
    bob, ada = world["bob"], world["ada"]
    made = [ask(bob, payer_handle="ada", amount=100 + i).json()["request_id"] for i in range(5)]
    newest_first = list(reversed(made))
    assert ids(ada) == newest_first
    pages = [listing(ada, limit=2, offset=o).json() for o in (0, 2, 4)]
    assert [r["request_id"] for p in pages for r in p["requests"]] == newest_first
    assert [p["has_more"] for p in pages] == [True, True, False]
    assert listing(ada, limit=5).json()["has_more"] is False
    assert listing(ada, limit=4).json()["has_more"] is True
    assert listing(ada, offset=5).json() == {"requests": [], "has_more": False}


def test_requests_never_in_feed(world):
    ask(world["bob"], payer_handle="ada", amount=5)
    for c in world.values():
        feed = c.http.get("/activity", headers={"Authorization": f"Bearer {c.token}"}).json()
        assert feed == {"payments": [], "has_more": False}


def test_needs_token(client, world):
    assert_error(client.get("/requests"), 401, "unauthenticated")
    assert_error(client.post("/requests", json={"payer_handle": "ada", "amount": 1}),
                 401, "unauthenticated")
