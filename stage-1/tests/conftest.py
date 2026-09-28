from __future__ import annotations

import copy

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app

JSON_UTF8 = "application/json; charset=utf-8"

FIXTURE = {
    "currency": "EUR",
    "minor_units": 2,
    "users": [
        {"id": "u_ada", "email": "ada@example.com", "password": "correct horse",
         "display_name": "Ada", "handle": "ada", "balance": 10000},
        {"id": "u_bob", "email": "bob@example.com", "password": "correct horse",
         "display_name": "Bob", "handle": "bob", "balance": 2500},
    ],
    "payments": [
        {"id": "p_1", "from_user_id": "u_ada", "to_user_id": "u_bob",
         "amount": 500, "note": "coffee", "visibility": "public"},
    ],
    "requests": [
        {"id": "rq_1", "requester_id": "u_bob", "payer_id": "u_ada",
         "amount": 1200, "note": "taxi", "status": "pending"},
    ],
}


def fixture(**over):
    body = copy.deepcopy(FIXTURE)
    body.update(over)
    return body


@pytest.fixture
def app(tmp_path):
    return create_app(Settings(host="0.0.0.0", port=8080,
                               database_path=str(tmp_path / "db.sqlite3")))


@pytest.fixture
def client(app):
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


def assert_error(resp, status, code):
    assert resp.status_code == status, resp.text
    assert resp.headers["content-type"] == JSON_UTF8
    body = resp.json()
    assert set(body) == {"error"}
    assert body["error"]["code"] == code
    assert isinstance(body["error"]["message"], str)
