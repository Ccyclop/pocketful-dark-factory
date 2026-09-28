from __future__ import annotations

import json
import random
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest

from conftest import JSON_UTF8, assert_error, fixture
from test_payments import Client
from test_request_actions import auth, feed_ids, pay
from test_requests import ask, ids


def user(handle, balance):
    return {"id": f"u_{handle}", "email": f"{handle}@example.com", "password": "correct horse",
            "display_name": handle.title(), "handle": handle, "balance": balance}


def settle(c, idem=..., raw=None, **body):
    headers = auth(c)
    if idem is ...:
        idem = uuid.uuid4().hex
    if idem is not None:
        headers["Idempotency-Key"] = idem
    if raw is not None:
        return c.http.post("/settlements", content=raw, headers=headers)
    return c.http.post("/settlements", json=body, headers=headers)


def t(src, dst, amount, **extra):
    return {"from_handle": src, "to_handle": dst, "amount": amount, **extra}


@pytest.fixture
def world(client):
    users = [user("ada", 100), user("bob", 0), user("cy", 0), user("op", 0)]
    body = fixture(users=users, payments=[], requests=[])
    body["settlement_operator_ids"] = ["u_op"]
    assert client.post("/_test/reset", json=body).status_code == 204
    return {h: Client(client, f"{h}@example.com") for h in ("ada", "bob", "cy", "op")}


def balances(world):
    return {h: c.balance() for h, c in world.items()}


def test_net_settlement(world):
    op = world["op"]
    resp = settle(op, transfers=[t("ada", "bob", 100), t("bob", "cy", 50)])
    assert resp.status_code == 201
    assert resp.headers["content-type"] == JSON_UTF8
    body = resp.json()
    assert set(body) == {"settlement_id", "committed_at", "payments"}
    assert 0 < len(body["settlement_id"]) <= 64
    members = body["payments"]
    assert [(p["from_handle"], p["to_handle"], p["amount"]) for p in members] == [
        ("ada", "bob", 100), ("bob", "cy", 50)]
    for p in members:
        assert (p["from_user_id"], p["to_user_id"]) == (f"u_{p['from_handle']}",
                                                        f"u_{p['to_handle']}")
        assert (p["currency"], p["note"], p["visibility"], p["request_id"],
                p["settlement_id"], p["created_at"]) == (
            "EUR", "", "public", None, body["settlement_id"], body["committed_at"])
    assert balances(world) == {"ada": 0, "bob": 50, "cy": 50, "op": 0}


def test_unaffordable_changes_nothing_and_key_stays_free(world, app):
    op = world["op"]
    k = uuid.uuid4().hex
    assert_error(settle(op, idem=k, transfers=[t("ada", "bob", 100), t("bob", "cy", 150)]),
                 409, "insufficient_funds")
    assert balances(world) == {"ada": 100, "bob": 0, "cy": 0, "op": 0}
    conn = app.state.db.connection()
    assert conn.execute("SELECT count(*) FROM payments").fetchone()[0] == 0
    assert conn.execute("SELECT count(*) FROM settlements").fetchone()[0] == 0
    assert settle(op, idem=k, transfers=[t("ada", "bob", 100)]).status_code == 201


def test_auth_and_key(world, client):
    assert_error(client.post("/settlements", json={"transfers": [t("ada", "bob", 1)]}),
                 401, "unauthenticated")
    assert_error(settle(world["ada"], transfers=[t("ada", "bob", 1)]), 403, "forbidden")
    assert_error(settle(world["ada"], idem=None, raw=b"{nope"), 403, "forbidden")
    assert_error(settle(world["op"], idem=None, transfers=[t("ada", "bob", 1)]),
                 400, "missing_idempotency_key")
    assert_error(settle(world["op"], raw=b"{nope"), 400, "malformed_request")
    assert_error(settle(world["op"], raw=b"[]"), 400, "malformed_request")


@pytest.mark.parametrize("body", [
    {}, {"transfers": []}, {"transfers": "x"}, {"transfers": None}, {"transfers": [5]},
    {"transfers": [t("ada", "bob", 1)] * 33}, {"transfers": [t("ada", "bob", 1), []]},
])
def test_batch_shape_is_422(world, body):
    assert_error(settle(world["op"], **body), 422, "validation_failed")


def test_32_entries(world):
    assert settle(world["op"], transfers=[t("ada", "bob", 1)] * 32).status_code == 201
    assert world["ada"].balance() == 68


@pytest.mark.parametrize("entries,status,code", [
    ([t("ada", "nobody", 1), t("bob", "bob", 1)], 404, "not_found"),
    ([t("bob", "bob", 1), t("ada", "nobody", 1)], 422, "self_payment"),
    ([t("ada", "bob", 0), t("ada", "bob", 1000)], 422, "validation_failed"),
    ([t("ada", "bob", 1000), t("ada", "bob", 1.5)], 422, "validation_failed"),
    ([t("ada", "bob", 1, note=None)], 422, "validation_failed"),
    ([t("ada", "bob", 1, note="x" * 201)], 422, "validation_failed"),
    ([t("ada", "bob", 1, visibility="PUBLIC")], 422, "validation_failed"),
    ([{"to_handle": "bob", "amount": 1}], 422, "validation_failed"),
    ([{"from_handle": 5, "to_handle": "bob", "amount": 1}], 422, "validation_failed"),
    ([t("ADA", "bob", 1)], 404, "not_found"),
    ([t("ada", "bob", 1000)], 409, "insufficient_funds"),
])
def test_entry_errors(world, entries, status, code):
    assert_error(settle(world["op"], transfers=entries), status, code)
    assert balances(world) == {"ada": 100, "bob": 0, "cy": 0, "op": 0}


def test_unknown_fields_ignored(world):
    resp = settle(world["op"], transfers=[t("ada", "bob", 1, colour="red")], extra=True)
    assert resp.status_code == 201


def test_member_visibility_and_notes(world):
    op, ada, bob, cy = world["op"], world["ada"], world["bob"], world["cy"]
    body = settle(op, transfers=[t("ada", "bob", 10, note="rent", visibility="private"),
                                 t("ada", "cy", 5)]).json()
    private, public = body["payments"]
    assert (private["note"], private["visibility"]) == ("rent", "private")
    assert private["payment_id"] in feed_ids(ada) and private["payment_id"] in feed_ids(bob)
    assert private["payment_id"] not in feed_ids(cy)
    assert private["payment_id"] not in feed_ids(op)
    assert public["payment_id"] in feed_ids(op)
    item = [p for p in bob.http.get("/activity", headers=auth(bob)).json()["payments"]
            if p["payment_id"] == private["payment_id"]][0]
    assert item == private


def test_non_members_expose_null(world):
    ada, bob = world["ada"], world["bob"]
    assert ada.pay(to_handle="bob", amount=1).json()["settlement_id"] is None
    rid = ask(bob, payer_handle="ada", amount=1).json()["request_id"]
    assert pay(ada, rid).json()["settlement_id"] is None
    assert all(p["settlement_id"] is None for p in
               ada.http.get("/activity", headers=auth(ada)).json()["payments"])


def test_idempotency(world):
    op = world["op"]
    k = uuid.uuid4().hex
    first = settle(op, idem=k, transfers=[t("ada", "bob", 10)])
    replay = settle(op, idem=k, raw=b'{"transfers":[{"amount":10.0,"to_handle":"bob",'
                                     b'"from_handle":"ada"}]}')
    assert (first.status_code, replay.status_code) == (201, 200)
    assert replay.json() == first.json()
    assert world["ada"].balance() == 90
    assert_error(settle(op, idem=k, transfers=[t("ada", "bob", 11)]), 409,
                 "idempotency_key_reuse")


def test_concurrent_identical(world):
    op = world["op"]
    k = uuid.uuid4().hex
    with ThreadPoolExecutor(20) as pool:
        resps = list(pool.map(lambda _: settle(op, idem=k, transfers=[t("ada", "bob", 10)]),
                              range(20)))
    assert sorted(r.status_code for r in resps) == [200] * 19 + [201]
    assert len({json.dumps(r.json(), sort_keys=True) for r in resps}) == 1
    assert world["ada"].balance() == 90


def test_concurrent_settlements_and_payments(client):
    users = [user("ada", 1000), user("bob", 1000), user("cy", 1000), user("op", 0)]
    body = fixture(users=users, payments=[], requests=[])
    body["settlement_operator_ids"] = ["u_op"]
    client.post("/_test/reset", json=body)
    world = {h: Client(client, f"{h}@example.com") for h in ("ada", "bob", "cy", "op")}
    names = ["ada", "bob", "cy"]

    def one(i):
        rnd = random.Random(i)
        a, b = rnd.sample(names, 2)
        if i % 2:
            return world[a].pay(to_handle=b, amount=rnd.randint(1, 400)).status_code
        c = rnd.choice([n for n in names if n not in (a, b)])
        return settle(world["op"], transfers=[t(a, b, rnd.randint(1, 600)),
                                              t(b, c, rnd.randint(1, 600))]).status_code

    with ThreadPoolExecutor(50) as pool:
        codes = list(pool.map(one, range(100)))
    assert set(codes) <= {201, 409}
    final = balances(world)
    assert sum(final.values()) == 3000 and min(final.values()) >= 0


def test_operator_sees_only_own_requests(world):
    ask(world["bob"], payer_handle="ada", amount=1)
    assert ids(world["op"]) == []


def test_reset_can_revoke_operator(world, client):
    op = world["op"]
    users = [user("ada", 100), user("bob", 0), user("op", 0)]
    client.post("/_test/reset", json=fixture(users=users, payments=[], requests=[]))
    op = Client(client, "op@example.com")
    assert_error(settle(op, transfers=[t("ada", "bob", 1)]), 403, "forbidden")
