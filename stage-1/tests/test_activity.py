from __future__ import annotations

import pytest

from conftest import JSON_UTF8, assert_error, fixture
from test_payments import USERS3, Client


@pytest.fixture
def world(client):
    seeded = [{"id": "p_1", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 500,
               "note": "coffee", "visibility": "public"}]
    assert client.post("/_test/reset", json=fixture(users=USERS3, payments=seeded,
                                                    requests=[])).status_code == 204
    return {h: Client(client, f"{h}@example.com") for h in ("ada", "bob", "cy")}


def feed(c, **params):
    return c.http.get("/activity", params=params,
                      headers={"Authorization": f"Bearer {c.token}"})


def ids(c, **params):
    resp = feed(c, **params)
    assert resp.status_code == 200, resp.text
    return [p["payment_id"] for p in resp.json()["payments"]]


def test_feed_contract(world):
    ada, bob, cy = world["ada"], world["bob"], world["cy"]
    private = ada.pay(to_handle="bob", amount=100, visibility="private").json()
    public = bob.pay(to_handle="cy", amount=200).json()
    assert ids(ada) == [public["payment_id"], private["payment_id"], "p_1"]
    assert ids(bob) == [public["payment_id"], private["payment_id"], "p_1"]
    assert ids(cy) == [public["payment_id"], "p_1"]
    resp = feed(bob)
    assert resp.headers["content-type"] == JSON_UTF8
    body = resp.json()
    assert set(body) == {"payments", "has_more"} and body["has_more"] is False
    assert body["payments"][0] == public
    assert body["payments"][1] == private and body["payments"][1]["visibility"] == "private"
    assert feed(ada).json()["payments"][1] == private
    seeded = body["payments"][2]
    assert (seeded["from_handle"], seeded["to_handle"], seeded["amount"], seeded["note"],
            seeded["currency"], seeded["request_id"], seeded["settlement_id"]) == (
        "ada", "bob", 500, "coffee", "EUR", None, None)


def test_private_between_others_is_hidden(world):
    world["ada"].pay(to_handle="bob", amount=1, visibility="private")
    assert ids(world["cy"]) == ["p_1"]


def test_paging(world):
    ada = world["ada"]
    made = [ada.pay(to_handle="bob", amount=1).json()["payment_id"] for _ in range(4)]
    everything = list(reversed(made)) + ["p_1"]
    assert ids(ada) == everything
    first = feed(ada, limit=2, offset=0).json()
    assert [p["payment_id"] for p in first["payments"]] == everything[:2] and first["has_more"]
    last = feed(ada, limit=2, offset=4).json()
    assert [p["payment_id"] for p in last["payments"]] == everything[4:]
    assert last["has_more"] is False
    assert feed(ada, offset=5).json() == {"payments": [], "has_more": False}
    assert feed(ada, limit=5).json()["has_more"] is False
    assert feed(ada, limit=4).json()["has_more"] is True
    assert feed(ada, limit=200).status_code == 200
    assert feed(ada, limit="007", offset="00").status_code == 200


def test_default_limit_is_50(world):
    ada = world["ada"]
    for _ in range(50):
        ada.pay(to_handle="bob", amount=1)
    body = feed(ada).json()
    assert len(body["payments"]) == 50 and body["has_more"] is True


@pytest.mark.parametrize("params", [
    {"limit": "0"}, {"limit": "201"}, {"limit": "-1"}, {"limit": "1e2"}, {"limit": "4.0"},
    {"limit": "+4"}, {"limit": "abc"}, {"limit": ""}, {"limit": " 4"}, {"limit": "٤"},
    {"offset": "-1"}, {"offset": "1.0"}, {"offset": ""}, {"limit": "9" * 5000},
])
def test_bad_paging_is_422(world, params):
    assert_error(feed(world["ada"], **params), 422, "validation_failed")


def test_huge_offset_is_empty(world):
    assert feed(world["ada"], offset="9" * 5000).json() == {"payments": [], "has_more": False}


def test_unknown_params_ignored(world):
    assert ids(world["ada"], foo="bar", direction="both", status="open") == ["p_1"]


def test_needs_token(client, world):
    assert_error(client.get("/activity"), 401, "unauthenticated")
    assert_error(client.get("/activity", params={"limit": "0"}), 401, "unauthenticated")


def test_newest_first_within_one_second(world):
    ada = world["ada"]
    a = ada.pay(to_handle="bob", amount=1).json()
    b = ada.pay(to_handle="bob", amount=2).json()
    assert a["created_at"] <= b["created_at"]
    assert ids(ada)[:2] == [b["payment_id"], a["payment_id"]]


def test_seeded_created_at_orders_by_time_not_text(client):
    seeded = [
        {"id": "p_old", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 1,
         "created_at": "2026-01-01T12:00:00+02:00"},  # 10:00Z
        {"id": "p_new", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 1,
         "created_at": "2026-01-01T11:00:00+00:00"},
    ]
    client.post("/_test/reset", json=fixture(users=USERS3, payments=seeded, requests=[]))
    ada = Client(client, "ada@example.com")
    assert ids(ada) == ["p_new", "p_old"]
    assert feed(ada).json()["payments"][1]["created_at"] == "2026-01-01T12:00:00+02:00"
