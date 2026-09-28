from __future__ import annotations

import json
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest

from conftest import assert_error, fixture
from test_payments import USERS3, Client
from test_requests import SEEDED, ask, ids


def key():
    return uuid.uuid4().hex


def auth(c):
    return {"Authorization": f"Bearer {c.token}"}


def pay(c, rid, body=..., idem=..., raw=None):
    headers = auth(c)
    if idem is ...:
        idem = key()
    if idem is not None:
        headers["Idempotency-Key"] = idem
    if raw is not None:
        return c.http.post(f"/requests/{rid}/pay", content=raw, headers=headers)
    return c.http.post(f"/requests/{rid}/pay", json={} if body is ... else body,
                       headers=headers)


def act(c, rid, action, **kw):
    return c.http.post(f"/requests/{rid}/{action}", headers=auth(c), **kw)


def status_of(c, rid):
    return {r["request_id"]: r for r in c.http.get(
        "/requests", params={"limit": 200}, headers=auth(c)).json()["requests"]}[rid]


def feed_ids(c):
    return [p["payment_id"] for p in c.http.get("/activity", headers=auth(c)).json()["payments"]]


@pytest.fixture
def world(client):
    assert client.post("/_test/reset", json=fixture(users=USERS3, payments=[],
                                                    requests=[])).status_code == 204
    return {h: Client(client, f"{h}@example.com") for h in ("ada", "bob", "cy")}


def new_request(world, amount=1200, note="taxi", requester="bob", payer="ada"):
    resp = ask(world[requester], payer_handle=payer, amount=amount, note=note)
    assert resp.status_code == 201
    return resp.json()["request_id"]


def test_pay_private(world):
    ada, bob, cy = world["ada"], world["bob"], world["cy"]
    rid = new_request(world)
    resp = pay(ada, rid, {"visibility": "private"})
    assert resp.status_code == 201
    p = resp.json()
    assert {k: p[k] for k in p if k not in ("payment_id", "created_at")} == {
        "from_user_id": "u_ada", "from_handle": "ada", "to_user_id": "u_bob",
        "to_handle": "bob", "amount": 1200, "currency": "EUR", "note": "taxi",
        "visibility": "private", "request_id": rid, "settlement_id": None}
    assert (ada.balance(), bob.balance()) == (8800, 3700)
    listed = status_of(ada, rid)
    assert (listed["status"], listed["payment_id"]) == ("paid", p["payment_id"])
    assert feed_ids(ada) == feed_ids(bob) == [p["payment_id"]]
    assert feed_ids(cy) == []


def test_pay_default_public_replay_and_reuse(world):
    ada, bob = world["ada"], world["bob"]
    rid = new_request(world)
    k = key()
    first = pay(ada, rid, {}, idem=k)
    assert first.status_code == 201 and first.json()["visibility"] == "public"
    replay = pay(ada, rid, {}, idem=k)
    assert replay.status_code == 200 and replay.json() == first.json()
    assert pay(ada, rid, raw=b"", idem=k).status_code == 200  # empty body is {} (D14)
    assert (ada.balance(), bob.balance()) == (8800, 3700)
    assert_error(pay(ada, rid, {"visibility": "public"}, idem=k), 409, "idempotency_key_reuse")


def test_pay_errors(world):
    ada, bob, cy = world["ada"], world["bob"], world["cy"]
    rid = new_request(world)
    assert_error(pay(ada, rid, {"visibility": "x"}), 422, "validation_failed")
    assert_error(pay(bob, rid), 403, "forbidden")
    assert_error(pay(cy, rid), 403, "forbidden")
    assert_error(pay(ada, "rq_nope"), 404, "not_found")
    assert_error(pay(ada, rid, idem=None), 400, "missing_idempotency_key")
    assert_error(pay(ada, rid, raw=b"[]"), 400, "malformed_request")
    assert_error(pay(ada, rid, raw=b"{nope"), 400, "malformed_request")
    assert pay(ada, rid).status_code == 201
    assert_error(pay(ada, rid), 409, "request_not_pending")
    assert_error(ada.http.post(f"/requests/{rid}/pay", json={}), 401, "unauthenticated")


def test_pay_order_visibility_before_404(world):
    assert_error(pay(world["ada"], "rq_nope", {"visibility": "x"}), 422, "validation_failed")


def test_short_then_funded_same_key(world):
    cy, ada, bob = world["cy"], world["ada"], world["bob"]
    rid = new_request(world, amount=1000, payer="cy")
    k = key()
    assert_error(pay(cy, rid, idem=k), 409, "insufficient_funds")
    assert status_of(cy, rid)["status"] == "pending"
    assert (cy.balance(), bob.balance()) == (500, 2500)
    assert ada.pay(to_handle="cy", amount=600).status_code == 201
    assert pay(cy, rid, idem=k).status_code == 201
    assert (cy.balance(), bob.balance()) == (100, 3500)


def test_same_key_on_two_requests(world):
    ada = world["ada"]
    a, b = new_request(world, amount=1), new_request(world, amount=2)
    k = key()
    assert pay(ada, a, idem=k).status_code == 201
    assert pay(ada, b, idem=k).status_code == 201


def test_decline(world):
    ada, bob, cy = world["ada"], world["bob"], world["cy"]
    rid = new_request(world)
    assert_error(act(bob, rid, "decline"), 403, "forbidden")
    assert_error(act(cy, rid, "decline"), 403, "forbidden")
    resp = act(ada, rid, "decline", json={"anything": 1})
    assert resp.status_code == 200 and resp.json()["status"] == "declined"
    again = act(ada, rid, "decline", content=b"not json")
    assert again.status_code == 200 and again.json() == resp.json()
    assert_error(pay(ada, rid), 409, "request_not_pending")
    assert_error(act(bob, rid, "cancel"), 409, "request_not_pending")
    assert_error(act(ada, "rq_nope", "decline"), 404, "not_found")
    assert (ada.balance(), bob.balance()) == (10000, 2500)


def test_cancel(world):
    ada, bob = world["ada"], world["bob"]
    rid = new_request(world)
    assert_error(act(ada, rid, "cancel"), 403, "forbidden")
    resp = act(bob, rid, "cancel")
    assert resp.status_code == 200 and resp.json()["status"] == "cancelled"
    assert act(bob, rid, "cancel").json()["status"] == "cancelled"
    assert_error(pay(ada, rid), 409, "request_not_pending")
    assert_error(act(ada, rid, "decline"), 409, "request_not_pending")


def test_paid_cannot_be_declined_or_cancelled(world):
    ada, bob = world["ada"], world["bob"]
    rid = new_request(world)
    k = key()
    original = pay(ada, rid, idem=k).json()
    assert_error(act(ada, rid, "decline"), 409, "request_not_pending")
    assert_error(act(bob, rid, "cancel"), 409, "request_not_pending")
    replay = pay(ada, rid, idem=k)
    assert replay.status_code == 200 and replay.json() == original


def test_concurrent_pays_distinct_keys(world):
    ada, bob = world["ada"], world["bob"]
    rid = new_request(world, amount=100)
    with ThreadPoolExecutor(20) as pool:
        resps = list(pool.map(lambda _: pay(ada, rid), range(20)))
    assert sorted(r.status_code for r in resps) == [201] + [409] * 19
    assert {r.json()["error"]["code"] for r in resps if r.status_code == 409} == {
        "request_not_pending"}
    assert (ada.balance(), bob.balance()) == (9900, 2600)


def test_concurrent_pays_one_key(world):
    ada, bob = world["ada"], world["bob"]
    rid = new_request(world, amount=100)
    k = key()
    with ThreadPoolExecutor(20) as pool:
        resps = list(pool.map(lambda _: pay(ada, rid, idem=k), range(20)))
    assert sorted(r.status_code for r in resps) == [200] * 19 + [201]
    assert len({json.dumps(r.json(), sort_keys=True) for r in resps}) == 1
    assert (ada.balance(), bob.balance()) == (9900, 2600)


def test_concurrent_pay_cancel_decline(world):
    ada, bob = world["ada"], world["bob"]
    for _ in range(10):
        before = (ada.balance(), bob.balance())
        rid = new_request(world, amount=100)
        calls = [lambda: pay(ada, rid), lambda: act(bob, rid, "cancel"),
                 lambda: act(ada, rid, "decline")] * 3
        with ThreadPoolExecutor(9) as pool:
            codes = [r.status_code for r in pool.map(lambda f: f(), calls)]
        assert all(c in (200, 201, 409) for c in codes)
        final = status_of(ada, rid)["status"]
        moved = before != (ada.balance(), bob.balance())
        assert moved == (final == "paid")
        if moved:
            assert (ada.balance(), bob.balance()) == (before[0] - 100, before[1] + 100)


def test_seeded_statuses(client):
    client.post("/_test/reset", json=fixture(users=USERS3, payments=[], requests=SEEDED))
    ada, bob = Client(client, "ada@example.com"), Client(client, "bob@example.com")
    assert pay(ada, "rq_p").status_code == 201
    assert_error(pay(bob, "rq_paid"), 409, "request_not_pending")
    assert_error(pay(ada, "rq_d"), 409, "request_not_pending")
    assert act(ada, "rq_d", "decline").json()["status"] == "declined"
    assert act(ada, "rq_c", "cancel").json()["status"] == "cancelled"
    assert_error(act(bob, "rq_paid", "decline"), 409, "request_not_pending")


def test_zero_amount_request_is_payable(world, app):
    # Splits create 0-amount requests (D16); seed one directly.
    with app.state.db.transaction() as conn:
        conn.execute("INSERT INTO requests (id, requester_id, payer_id, amount, note, status,"
                     " created_at, created_ts) VALUES ('rq_zero', 'u_bob', 'u_cy', 0, '',"
                     " 'pending', '2026-01-01T00:00:00+00:00', 0)")
    cy = world["cy"]
    resp = pay(cy, "rq_zero")
    assert resp.status_code == 201 and resp.json()["amount"] == 0
    assert cy.balance() == 500
