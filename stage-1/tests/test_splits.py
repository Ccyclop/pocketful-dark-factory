from __future__ import annotations

import json
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest

from app.splits import equal_split
from conftest import JSON_UTF8, assert_error, fixture
from test_payments import USERS3, Client
from test_request_actions import auth, pay
from test_requests import ids


def split(c, idem=..., raw=None, **body):
    headers = auth(c)
    if idem is ...:
        idem = uuid.uuid4().hex
    if idem is not None:
        headers["Idempotency-Key"] = idem
    if raw is not None:
        return c.http.post("/splits", content=raw, headers=headers)
    return c.http.post("/splits", json=body, headers=headers)


@pytest.fixture
def world(client):
    assert client.post("/_test/reset", json=fixture(users=USERS3, payments=[],
                                                    requests=[])).status_code == 204
    return {h: Client(client, f"{h}@example.com") for h in ("ada", "bob", "cy")}


@pytest.mark.parametrize("amount,n,shares", [
    (1000, 3, [334, 333, 333]), (1, 3, [1, 0, 0]), (10, 3, [4, 3, 3]),
    (999, 3, [333, 333, 333]), (5, 5, [1, 1, 1, 1, 1]), (3000, 3, [1000, 1000, 1000]),
    (7, 1, [7]), (1_000_000_000, 7, [142857143] * 6 + [142857142]),
])
def test_equal_split(amount, n, shares):
    assert equal_split(amount, n) == shares
    assert sum(shares) == amount


def test_split_created(world):
    ada, bob, cy = world["ada"], world["bob"], world["cy"]
    resp = split(ada, amount=3000, participant_handles=["ada", "bob", "cy"], note="dinner")
    assert resp.status_code == 201
    assert resp.headers["content-type"] == JSON_UTF8
    body = resp.json()
    assert set(body) == {"split_id", "amount", "currency", "note", "shares", "requests",
                         "created_at"}
    assert 0 < len(body["split_id"]) <= 64
    assert (body["amount"], body["currency"], body["note"]) == (3000, "EUR", "dinner")
    assert body["shares"] == [{"handle": "ada", "amount": 1000}, {"handle": "bob", "amount": 1000},
                              {"handle": "cy", "amount": 1000}]
    reqs = body["requests"]
    assert [(r["payer_handle"], r["requester_handle"], r["amount"], r["status"], r["note"],
             r["payment_id"]) for r in reqs] == [("bob", "ada", 1000, "pending", "dinner", None),
                                                 ("cy", "ada", 1000, "pending", "dinner", None)]
    assert ids(bob) == [reqs[0]["request_id"]]
    assert ids(cy) == [reqs[1]["request_id"]]
    assert sorted(ids(ada)) == sorted(r["request_id"] for r in reqs)
    listed = {r["request_id"]: r for r in ada.http.get("/requests", headers=auth(ada)).json()[
        "requests"]}
    assert all(listed[r["request_id"]] == r for r in reqs)
    for c in world.values():
        assert c.http.get("/activity", headers=auth(c)).json()["payments"] == []
    assert [c.balance() for c in world.values()] == [10000, 2500, 500]


def test_order_moves_the_extra_unit_and_caller_omitted(world):
    ada = world["ada"]
    a = split(ada, amount=1000, participant_handles=["ada", "bob", "cy"]).json()
    b = split(ada, amount=1000, participant_handles=["cy", "bob", "ada"]).json()
    assert a["shares"][0] == {"handle": "ada", "amount": 334}
    assert b["shares"] == [{"handle": "cy", "amount": 334}, {"handle": "bob", "amount": 333},
                           {"handle": "ada", "amount": 333}]
    c = split(ada, amount=10, participant_handles=["bob", "cy"]).json()
    assert c["shares"] == [{"handle": "bob", "amount": 5}, {"handle": "cy", "amount": 5}]
    assert [r["payer_handle"] for r in c["requests"]] == ["bob", "cy"]
    assert c["note"] == ""


def test_zero_share_request_is_payable(world):
    ada, cy = world["ada"], world["cy"]
    body = split(ada, amount=1, participant_handles=["ada", "bob", "cy"]).json()
    assert [s["amount"] for s in body["shares"]] == [1, 0, 0]
    assert [r["amount"] for r in body["requests"]] == [0, 0]
    resp = pay(cy, body["requests"][1]["request_id"])
    assert resp.status_code == 201 and resp.json()["amount"] == 0
    assert cy.balance() == 500


def test_only_the_caller(world):
    body = split(world["ada"], amount=999, participant_handles=["ada"]).json()
    assert body["shares"] == [{"handle": "ada", "amount": 999}] and body["requests"] == []


def test_no_balance_check(world):
    assert split(world["cy"], amount=1_000_000, participant_handles=["cy", "ada"]
                 ).status_code == 201


@pytest.mark.parametrize("body,status,code", [
    ({"amount": 100, "participant_handles": []}, 422, "validation_failed"),
    ({"amount": 100, "participant_handles": ["bob", "bob"]}, 422, "validation_failed"),
    ({"amount": 100, "participant_handles": ["bob", "nobody"]}, 404, "not_found"),
    ({"amount": 100, "participant_handles": ["BOB"]}, 404, "not_found"),
    ({"amount": 0, "participant_handles": ["bob"]}, 422, "validation_failed"),
    ({"amount": -1, "participant_handles": ["bob"]}, 422, "validation_failed"),
    ({"amount": 1_000_000_001, "participant_handles": ["bob"]}, 422, "validation_failed"),
    ({"amount": 1.5, "participant_handles": ["bob"]}, 422, "validation_failed"),
    ({"amount": "100", "participant_handles": ["bob"]}, 422, "validation_failed"),
    ({"amount": 100, "participant_handles": ["bob"], "note": "x" * 201}, 422,
     "validation_failed"),
    ({"amount": 100, "participant_handles": ["bob"], "note": None}, 422, "validation_failed"),
    ({"amount": 100, "participant_handles": "ada"}, 400, "malformed_request"),
    ({"amount": 100, "participant_handles": ["ada", 5]}, 400, "malformed_request"),
    ({"amount": 100, "participant_handles": None}, 400, "malformed_request"),
    ({"amount": 100}, 422, "validation_failed"),
    ({"participant_handles": ["bob"]}, 422, "validation_failed"),
    ({"amount": 100, "participant_handles": [f"h{i}" for i in range(1000)]}, 404, "not_found"),
    ({"amount": 100, "participant_handles": ["x"] * 1000}, 422, "validation_failed"),
])
def test_validation(world, body, status, code):
    assert_error(split(world["ada"], **body), status, code)
    assert ids(world["ada"]) == []


def test_bad_bodies(world):
    ada = world["ada"]
    assert_error(split(ada, raw=b"{nope"), 400, "malformed_request")
    assert_error(split(ada, raw=b"[]"), 400, "malformed_request")
    assert_error(split(ada, idem=None, amount=1, participant_handles=["bob"]), 400,
                 "missing_idempotency_key")
    assert_error(ada.http.post("/splits", json={}), 401, "unauthenticated")


def test_idempotency(world):
    ada = world["ada"]
    k = uuid.uuid4().hex
    first = split(ada, idem=k, amount=3000, participant_handles=["ada", "bob", "cy"])
    replay = split(ada, idem=k, raw=b'{"participant_handles":["ada","bob","cy"],"amount":3e3}')
    assert (first.status_code, replay.status_code) == (201, 200)
    assert replay.json() == first.json()
    assert len(ids(ada)) == 2
    assert_error(split(ada, idem=k, amount=3000, participant_handles=["bob", "ada", "cy"]),
                 409, "idempotency_key_reuse")


def test_concurrent_identical(world):
    ada = world["ada"]
    k = uuid.uuid4().hex
    with ThreadPoolExecutor(20) as pool:
        resps = list(pool.map(
            lambda _: split(ada, idem=k, amount=100, participant_handles=["bob", "cy"]),
            range(20)))
    assert sorted(r.status_code for r in resps) == [200] * 19 + [201]
    assert len({json.dumps(r.json(), sort_keys=True) for r in resps}) == 1
    assert len(ids(ada)) == 2


def test_paying_every_split_request_conserves_money(world):
    ada, bob, cy = world["ada"], world["bob"], world["cy"]
    bodies = [split(ada, amount=1000, participant_handles=["ada", "bob", "cy"]).json(),
              split(bob, amount=7, participant_handles=["cy", "ada", "bob"]).json(),
              split(cy, amount=400, participant_handles=["ada", "bob"]).json()]
    for body in bodies:
        for r in body["requests"]:
            payer = world[r["payer_handle"]]
            assert pay(payer, r["request_id"]).status_code == 201
    assert sum(c.balance() for c in world.values()) == 13000
