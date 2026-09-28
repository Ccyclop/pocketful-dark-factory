from __future__ import annotations

import copy
import json
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from conftest import JSON_UTF8, assert_error, fixture
from test_payments import Client
from test_request_actions import act, auth, pay
from test_requests import ask
from test_settlements import settle, t, user
from test_splits import split


def build_state(http):
    """A service with signups, payments, requests in every status, a split, a settlement
    and a failed attempt. Returns clients and the idempotent calls made."""
    users = [user("ada", 10000), user("bob", 2500), user("cy", 500), user("op", 0)]
    body = fixture(users=users, payments=[
        {"id": "p_seed", "from_user_id": "u_ada", "to_user_id": "u_bob", "amount": 1}],
        requests=[])
    body["settlement_operator_ids"] = ["u_op"]
    assert http.post("/_test/reset", json=body).status_code == 204
    c = {h: Client(http, f"{h}@example.com") for h in ("ada", "bob", "cy", "op")}
    zed = http.post("/auth/signup", json={"email": "zed@example.com", "password": "zed password",
                                          "display_name": "Zed"}).json()
    calls = []

    def call(client, path, body):
        k = uuid.uuid4().hex
        resp = client.http.post(path, json=body,
                                headers={**auth(client), "Idempotency-Key": k})
        calls.append((client, path, body, k, resp.status_code, resp.json()))
        return resp

    call(c["ada"], "/payments", {"to_handle": "bob", "amount": 100})
    call(c["ada"], "/payments", {"to_handle": "cy", "amount": 50, "visibility": "private"})
    paid = call(c["bob"], "/requests", {"payer_handle": "ada", "amount": 30}).json()["request_id"]
    call(c["ada"], f"/requests/{paid}/pay", {"visibility": "private"})
    declined = call(c["bob"], "/requests", {"payer_handle": "ada", "amount": 1}).json()
    act(c["ada"], declined["request_id"], "decline")
    cancelled = call(c["bob"], "/requests", {"payer_handle": "ada", "amount": 2}).json()
    act(c["bob"], cancelled["request_id"], "cancel")
    call(c["cy"], "/requests", {"payer_handle": "bob", "amount": 3})
    call(c["ada"], "/splits", {"amount": 1000, "participant_handles": ["ada", "bob", "cy"]})
    call(c["op"], "/settlements", {"transfers": [t("ada", "bob", 10), t("bob", "cy", 5)]})
    failed_key = uuid.uuid4().hex
    resp = c["cy"].http.post("/payments", json={"to_handle": "ada", "amount": 99999},
                             headers={**auth(c["cy"]), "Idempotency-Key": failed_key})
    assert resp.status_code == 409
    return c, zed, calls, failed_key


def views(http, clients):
    out = {}
    for h, c in clients.items():
        out[h] = {
            "me": http.get("/me", headers=auth(c)).json(),
            "activity": http.get("/activity", params={"limit": 200}, headers=auth(c)).json(),
            "requests": http.get("/requests", params={"limit": 200}, headers=auth(c)).json(),
        }
    return out


@pytest.fixture
def other(tmp_path):
    app = create_app(Settings(host="0.0.0.0", port=8080,
                              database_path=str(tmp_path / "other.sqlite3")))
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


def test_round_trip_to_another_service(client, other):
    clients, zed, calls, failed_key = build_state(client)
    resp = client.get("/_test/export")
    assert resp.status_code == 200 and resp.headers["content-type"] == JSON_UTF8
    doc = resp.json()
    assert (doc["track"], doc["format_version"]) == ("pocketful", 1)
    assert isinstance(doc["state"], dict)
    before = views(client, clients)

    other.post("/_test/reset", json=fixture(users=[user("old", 5)], payments=[], requests=[]))
    old = Client(other, "old@example.com")
    assert other.post("/_test/import", json=doc).status_code == 204
    assert_error(other.get("/me", headers=auth(old)), 401, "unauthenticated")

    moved = {h: Client.__new__(Client) for h in clients}
    for h, c in clients.items():
        moved[h].http, moved[h].token = other, c.token
    assert views(other, moved) == before
    assert other.get("/me", headers={"Authorization": f"Bearer {zed['token']}"}).json()[
        "user_id"] == zed["user_id"]
    for h in clients:
        assert other.post("/auth/login", json={"email": f"{h}@example.com",
                                               "password": "correct horse"}).status_code == 200
    assert other.post("/auth/login", json={"email": "zed@example.com",
                                           "password": "zed password"}).status_code == 200

    for c, path, body, k, status, original in calls:
        headers = {"Authorization": f"Bearer {c.token}", "Idempotency-Key": k}
        replay = other.post(path, json=body, headers=headers)
        assert replay.status_code == 200 and replay.json() == original, path
        changed = dict(body, extra_field_changes_body=1)
        assert_error(other.post(path, json=changed, headers=headers), 409,
                     "idempotency_key_reuse")
    assert views(other, moved) == before

    headers = {"Authorization": f"Bearer {clients['cy'].token}", "Idempotency-Key": failed_key}
    assert other.post("/payments", json={"to_handle": "ada", "amount": 1},
                      headers=headers).status_code == 201

    op = moved["op"]
    assert settle(op, transfers=[t("ada", "bob", 1)]).status_code == 201
    new = moved["ada"].pay(to_handle="bob", amount=1).json()
    assert new["payment_id"] not in {p["payment_id"] for p in before["ada"]["activity"]["payments"]}
    total = sum(v["me"]["balance"] for v in views(other, moved).values())
    assert total == sum(v["me"]["balance"] for v in before.values())


def test_import_twice_is_idempotent(client, other):
    clients, *_ = build_state(client)
    doc = client.get("/_test/export").json()
    assert other.post("/_test/import", json=doc).status_code == 204
    first = other.get("/_test/export").json()
    assert other.post("/_test/import", json=doc).status_code == 204
    assert other.get("/_test/export").json() == first
    assert first["state"] == doc["state"]


def _set(doc, table, column, value):
    data = doc["state"]["tables"][table]
    data["rows"][0][data["columns"].index(column)] = value


def _broken(doc, mutate):
    bad = copy.deepcopy(doc)
    mutate(bad)
    return bad


@pytest.mark.parametrize("mutate", [
    lambda d: d.pop("state"),
    lambda d: d.pop("track"),
    lambda d: d.pop("format_version"),
    lambda d: d.update(track="other"),
    lambda d: d.update(format_version=2),
    lambda d: d.update(format_version="1"),
    lambda d: d.update(format_version=True),
    lambda d: d.update(state={}),
    lambda d: d.update(state="garbage"),
    lambda d: d.update(state=[1, 2]),
    lambda d: d["state"]["tables"].pop("users"),
    lambda d: d["state"]["tables"].update(extra={"columns": [], "rows": []}),
    lambda d: d["state"]["tables"]["users"]["columns"].reverse(),
    lambda d: d["state"]["tables"]["users"]["rows"].append(["x"]),
    lambda d: _set(d, "users", "balance", -5),
    lambda d: _set(d, "users", "balance", "100"),
    lambda d: _set(d, "users", "balance", 1.5),
    lambda d: _set(d, "users", "is_operator", 7),
    lambda d: _set(d, "users", "password_hash", None),
    lambda d: _set(d, "payments", "to_user_id", "u_nobody"),
    lambda d: _set(d, "payments", "visibility", "friends"),
    lambda d: _set(d, "requests", "status", "open"),
    lambda d: d["state"]["tables"]["users"]["rows"].append(
        list(d["state"]["tables"]["users"]["rows"][0])),
    lambda d: d["state"]["tables"]["service"].update(rows=[]),
    lambda d: d["state"]["tables"]["tokens"]["rows"].append(["deadbeef", "u_nobody"]),
])
def test_invalid_import_changes_nothing(client, other, mutate):
    build_state(client)
    doc = client.get("/_test/export").json()
    other.post("/_test/reset", json=fixture(users=[user("old", 5)], payments=[], requests=[]))
    old = Client(other, "old@example.com")
    before = other.get("/_test/export").json()
    assert_error(other.post("/_test/import", json=_broken(doc, mutate)), 422,
                 "validation_failed")
    assert other.get("/_test/export").json() == before
    assert other.get("/me", headers=auth(old)).status_code == 200


@pytest.mark.parametrize("raw", [b"{nope", b"[]", b"\xff"])
def test_unparseable_import_is_400(other, raw):
    assert_error(other.post("/_test/import", content=raw), 400, "malformed_request")


def test_export_is_a_snapshot(client, other):
    clients, *_ = build_state(client)
    doc = client.get("/_test/export").json()
    before = views(client, clients)
    clients["ada"].pay(to_handle="bob", amount=7)
    other.post("/_test/import", json=doc)
    moved = {h: Client.__new__(Client) for h in clients}
    for h, c in clients.items():
        moved[h].http, moved[h].token = other, c.token
    assert views(other, moved) == before


def test_export_under_concurrent_writes_is_consistent(client):
    users = [user(h, 1000) for h in ("ada", "bob", "cy")]
    client.post("/_test/reset", json=fixture(users=users, payments=[], requests=[]))
    c = {h: Client(client, f"{h}@example.com") for h in ("ada", "bob", "cy")}
    names = list(c)

    def write(i):
        c[names[i % 3]].pay(to_handle=names[(i + 1) % 3], amount=1 + i % 50)

    def export(_):
        doc = client.get("/_test/export").json()
        users_table = doc["state"]["tables"]["users"]
        col = users_table["columns"].index("balance")
        return sum(row[col] for row in users_table["rows"])

    with ThreadPoolExecutor(16) as pool:
        writes = [pool.submit(write, i) for i in range(60)]
        totals = list(pool.map(export, range(20)))
        for w in writes:
            w.result()
    assert set(totals) == {3000}


def test_reset_clears_imported_state(client, other):
    clients, *_ = build_state(client)
    other.post("/_test/import", json=client.get("/_test/export").json())
    other.post("/_test/reset", json=fixture(users=[user("new", 1)], payments=[], requests=[]))
    assert_error(other.get("/me", headers=auth(clients["ada"])), 401, "unauthenticated")
    assert_error(other.post("/auth/login", json={"email": "ada@example.com",
                                                 "password": "correct horse"}),
                 401, "unauthenticated")


def test_large_state_is_fast(client, other):
    users = [user(f"u{i}", 1000) for i in range(200)]
    payments = [{"id": f"p_{i}", "from_user_id": f"u_u{i % 200}",
                 "to_user_id": f"u_u{(i + 1) % 200}", "amount": 1} for i in range(2000)]
    assert client.post("/_test/reset", json=fixture(users=users, payments=payments,
                                                    requests=[])).status_code == 204
    started = time.monotonic()
    doc = client.get("/_test/export").json()
    exported = time.monotonic()
    assert other.post("/_test/import", json=doc).status_code == 204
    imported = time.monotonic()
    assert exported - started < 10 and imported - exported < 10
    assert len(doc["state"]["tables"]["payments"]["rows"]) == 2000
    assert json.loads(json.dumps(other.get("/_test/export").json())) == doc
