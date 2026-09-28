from __future__ import annotations

import json
import random
import uuid
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal

import pytest

from app.idempotency import fingerprint
from conftest import FIXTURE, JSON_UTF8, assert_error, fixture
from app.timeutil import parse_rfc3339

USERS3 = [
    {"id": "u_ada", "email": "ada@example.com", "password": "correct horse",
     "display_name": "Ada", "handle": "ada", "balance": 10000},
    {"id": "u_bob", "email": "bob@example.com", "password": "correct horse",
     "display_name": "Bob", "handle": "bob", "balance": 2500},
    {"id": "u_cy", "email": "cy@example.com", "password": "correct horse",
     "display_name": "Cy", "handle": "cy", "balance": 500},
]


def key():
    return uuid.uuid4().hex


class Client:
    def __init__(self, http, email):
        resp = http.post("/auth/login", json={"email": email, "password": "correct horse"})
        assert resp.status_code == 200, resp.text
        self.http, self.token = http, resp.json()["token"]

    def pay(self, idem=..., raw=None, **body):
        headers = {"Authorization": f"Bearer {self.token}"}
        if idem is ...:
            idem = key()
        if idem is not None:
            headers["Idempotency-Key"] = idem
        if raw is not None:
            return self.http.post("/payments", content=raw, headers=headers)
        return self.http.post("/payments", json=body, headers=headers)

    def balance(self):
        return self.http.get("/me", headers={"Authorization": f"Bearer {self.token}"}).json()[
            "balance"]


@pytest.fixture
def world(client):
    assert client.post("/_test/reset", json=fixture(users=USERS3, payments=[],
                                                    requests=[])).status_code == 204
    return {h: Client(client, f"{h}@example.com") for h in ("ada", "bob", "cy")}


def test_payment_created(world):
    ada, bob = world["ada"], world["bob"]
    resp = ada.pay(to_handle="bob", amount=1500, note="dinner", visibility="public")
    assert resp.status_code == 201
    assert resp.headers["content-type"] == JSON_UTF8
    body = resp.json()
    assert set(body) == {"payment_id", "from_user_id", "from_handle", "to_user_id", "to_handle",
                         "amount", "currency", "note", "visibility", "request_id",
                         "settlement_id", "created_at"}
    assert body["payment_id"] and len(body["payment_id"]) <= 64
    assert {k: body[k] for k in body if k not in ("payment_id", "created_at")} == {
        "from_user_id": "u_ada", "from_handle": "ada", "to_user_id": "u_bob",
        "to_handle": "bob", "amount": 1500, "currency": "EUR", "note": "dinner",
        "visibility": "public", "request_id": None, "settlement_id": None}
    assert parse_rfc3339(body["created_at"]) and body["created_at"].endswith("+00:00")
    assert (ada.balance(), bob.balance()) == (8500, 4000)


def test_defaults_and_verbatim_note(world):
    body = world["ada"].pay(to_handle="bob", amount=1).json()
    assert (body["note"], body["visibility"]) == ("", "public")
    note = "  héllo 👋🏽\n<b>&amp;"
    assert world["ada"].pay(to_handle="bob", amount=1, note=note).json()["note"] == note
    assert world["ada"].pay(to_handle="bob", amount=1, note="😀" * 200).status_code == 201
    assert_error(world["ada"].pay(to_handle="bob", amount=1, note="x" * 201),
                 422, "validation_failed")


@pytest.mark.parametrize("amount", [0, -1, 1_000_000_001, 1.5, "10", True, None, [], {},
                                    1e-3])
def test_bad_amounts(world, amount):
    assert_error(world["ada"].pay(to_handle="bob", amount=amount), 422, "validation_failed")
    assert world["ada"].balance() == 10000


@pytest.mark.parametrize("raw", [b'{"to_handle":"bob","amount":1000.0}',
                                 b'{"to_handle":"bob","amount":1e3}',
                                 b'{"to_handle":"bob","amount":10E2}'])
def test_integral_amounts(world, raw):
    resp = world["ada"].pay(raw=raw)
    assert resp.status_code == 201 and resp.json()["amount"] == 1000
    assert '"amount":1000,' in resp.text


def test_huge_precision_amount_rejected(world):
    raw = b'{"to_handle":"bob","amount":1000000000.0000000000000001}'
    assert_error(world["ada"].pay(raw=raw), 422, "validation_failed")


@pytest.mark.parametrize("extra", [{"visibility": "PUBLIC"}, {"visibility": None},
                                   {"visibility": 1}, {"note": None}, {"note": 5}])
def test_bad_note_or_visibility(world, extra):
    assert_error(world["ada"].pay(to_handle="bob", amount=1, **extra), 422, "validation_failed")


def test_handle_errors(world):
    ada = world["ada"]
    assert_error(ada.pay(to_handle="ada", amount=1), 422, "self_payment")
    for handle in ("nobody", "ADA", "@ada", ""):
        assert_error(ada.pay(to_handle=handle, amount=1), 404, "not_found")
    assert_error(ada.pay(to_handle=5, amount=1), 400, "malformed_request")
    assert_error(ada.pay(to_handle=None, amount=1), 400, "malformed_request")
    assert_error(ada.pay(amount=1), 422, "validation_failed")
    assert_error(ada.pay(raw=b"{nope"), 400, "malformed_request")
    assert_error(ada.pay(raw=b"[]"), 400, "malformed_request")
    assert ada.pay(to_handle="bob", amount=1, colour="blue").status_code == 201


def test_insufficient_funds_and_exact_balance(world):
    cy, bob = world["cy"], world["bob"]
    assert_error(cy.pay(to_handle="bob", amount=501), 409, "insufficient_funds")
    assert (cy.balance(), bob.balance()) == (500, 2500)
    assert cy.pay(to_handle="bob", amount=500).status_code == 201
    assert (cy.balance(), bob.balance()) == (0, 3000)


def test_key_header_rules(world, client):
    ada = world["ada"]
    assert_error(ada.pay(idem=None, to_handle="bob", amount=1), 400, "missing_idempotency_key")
    assert_error(ada.pay(idem="", to_handle="bob", amount=1), 400, "missing_idempotency_key")
    assert_error(ada.pay(idem="k" * 256, to_handle="bob", amount=1), 422, "validation_failed")
    assert_error(ada.pay(idem="k" * 10_000, to_handle="bob", amount=1), 422, "validation_failed")
    assert ada.pay(idem="k" * 255, to_handle="bob", amount=1).status_code == 201
    # 401 outranks everything else.
    assert_error(client.post("/payments", content=b"{nope"), 401, "unauthenticated")


def test_key_length_counts_code_points(world):
    idem = "é" * 255  # 510 bytes of UTF-8
    resp = world["ada"].http.post(
        "/payments", json={"to_handle": "bob", "amount": 1},
        headers={"Authorization": f"Bearer {world['ada'].token}",
                 "Idempotency-Key": idem.encode("utf-8")})
    assert resp.status_code == 201


def test_replay_and_reuse(world):
    ada, bob = world["ada"], world["bob"]
    k = key()
    first = ada.pay(idem=k, to_handle="bob", amount=1500, note="n")
    assert first.status_code == 201
    for raw in (b'{"amount":1500,"note":"n","to_handle":"bob"}',
                b'{ "to_handle" : "bob",\n "amount" : 1500.0, "note":"n" }',
                b'{"to_handle":"bob","amount":15e2,"note":"n"}'):
        replay = ada.pay(idem=k, raw=raw)
        assert replay.status_code == 200
        assert replay.json() == first.json()
    assert (ada.balance(), bob.balance()) == (8500, 4000)
    assert_error(ada.pay(idem=k, to_handle="bob", amount=1501, note="n"),
                 409, "idempotency_key_reuse")
    assert_error(ada.pay(idem=k, to_handle="bob", amount=-5, note="n"),
                 409, "idempotency_key_reuse")
    assert_error(ada.pay(idem=k, to_handle="bob", amount=1500), 409, "idempotency_key_reuse")
    assert (ada.balance(), bob.balance()) == (8500, 4000)


def test_failed_key_is_reusable(world):
    cy, ada = world["cy"], world["ada"]
    k = key()
    assert_error(cy.pay(idem=k, to_handle="bob", amount=1000), 409, "insufficient_funds")
    assert_error(cy.pay(idem=k, to_handle="nobody", amount=1000), 404, "not_found")
    assert_error(cy.pay(idem=k, to_handle="bob", amount=0), 422, "validation_failed")
    ada.pay(to_handle="cy", amount=600)
    assert cy.pay(idem=k, to_handle="bob", amount=1000).status_code == 201
    assert cy.balance() == 100


def test_same_key_two_users(world):
    k = key()
    assert world["ada"].pay(idem=k, to_handle="cy", amount=10).status_code == 201
    assert world["bob"].pay(idem=k, to_handle="cy", amount=10).status_code == 201
    assert world["cy"].balance() == 520


def test_concurrent_identical_requests(world):
    ada, bob = world["ada"], world["bob"]
    k = key()
    with ThreadPoolExecutor(20) as pool:
        resps = list(pool.map(lambda _: ada.pay(idem=k, to_handle="bob", amount=100),
                              range(20)))
    assert sorted(r.status_code for r in resps) == [200] * 19 + [201]
    assert len({json.dumps(r.json(), sort_keys=True) for r in resps}) == 1
    assert (ada.balance(), bob.balance()) == (9900, 2600)


def test_concurrent_drain(client):
    users = [dict(USERS3[0], balance=1000), dict(USERS3[1], balance=0)]
    client.post("/_test/reset", json=fixture(users=users, payments=[], requests=[]))
    ada, bob = Client(client, "ada@example.com"), Client(client, "bob@example.com")
    with ThreadPoolExecutor(50) as pool:
        codes = list(pool.map(lambda _: ada.pay(to_handle="bob", amount=100).status_code,
                              range(50)))
    assert sorted(codes) == [201] * 10 + [409] * 40
    assert (ada.balance(), bob.balance()) == (0, 1000)


def test_random_burst_conserves_money(world):
    clients = list(world.values())
    handles = list(world)

    def one(i):
        rnd = random.Random(i)
        src = rnd.randrange(3)
        dst = (src + 1 + rnd.randrange(2)) % 3
        return clients[src].pay(to_handle=handles[dst], amount=rnd.randint(1, 3000)).status_code

    with ThreadPoolExecutor(50) as pool:
        codes = list(pool.map(one, range(50)))
    assert set(codes) <= {201, 409}
    balances = [c.balance() for c in clients]
    assert sum(balances) == 13000 and min(balances) >= 0


def test_exact_near_2_53(client):
    users = [dict(USERS3[0], balance=9007199254740000), dict(USERS3[1], balance=0)]
    client.post("/_test/reset", json=fixture(users=users, payments=[], requests=[]))
    ada, bob = Client(client, "ada@example.com"), Client(client, "bob@example.com")
    assert ada.pay(to_handle="bob", amount=1_000_000_000).status_code == 201
    assert (ada.balance(), bob.balance()) == (9007198254740000, 1000000000)


def test_reset_clears_idempotency(world, client):
    k = key()
    assert world["ada"].pay(idem=k, to_handle="bob", amount=1).status_code == 201
    client.post("/_test/reset", json=fixture(users=USERS3, payments=[], requests=[]))
    ada = Client(client, "ada@example.com")
    assert ada.pay(idem=k, to_handle="bob", amount=1).status_code == 201


@pytest.mark.parametrize("a,b,same", [
    ({"x": 1000}, {"x": Decimal("1000.0")}, True),
    ({"x": 1000}, {"x": Decimal("1E+3")}, True),
    ({"a": 1, "b": 2}, {"b": 2, "a": 1}, True),
    ({"x": 0}, {"x": Decimal("-0.0")}, True),
    ({"x": True}, {"x": 1}, False),
    ({"x": None}, {"x": False}, False),
    ({"x": "1"}, {"x": 1}, False),
    ({"x": [1, 2]}, {"x": [2, 1]}, False),
    ({}, {"visibility": "public"}, False),
])
def test_fingerprint(a, b, same):
    assert (fingerprint(a) == fingerprint(b)) is same
