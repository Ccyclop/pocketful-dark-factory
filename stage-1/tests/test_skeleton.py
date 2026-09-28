from __future__ import annotations

import pytest

from app.config import load_settings
from conftest import JSON_UTF8, assert_error


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == JSON_UTF8
    assert resp.json() == {"status": "ok"}


@pytest.mark.parametrize("method,path", [
    ("GET", "/nope"),
    ("DELETE", "/health"),
    ("POST", "/health"),
    ("GET", "/health/"),
    ("GET", "/docs"),
    ("GET", "/openapi.json"),
    ("GET", "/redoc"),
])
def test_unrouted_is_not_found(client, method, path):
    assert_error(client.request(method, path), 404, "not_found")


def test_unhandled_exception_is_500_envelope(app, client):
    @app.get("/_boom")
    def boom():
        raise RuntimeError("boom")

    resp = client.get("/_boom")
    assert_error(resp, 500, "internal_error")
    assert "boom" not in resp.text


def test_port_env(monkeypatch):
    monkeypatch.delenv("PORT", raising=False)
    assert load_settings().port == 8080
    monkeypatch.setenv("PORT", "9123")
    s = load_settings()
    assert (s.host, s.port) == ("0.0.0.0", 9123)


def test_transaction_rolls_back(app, client):
    db = app.state.db
    with db.transaction() as conn:
        conn.execute("CREATE TABLE t (x INTEGER)")
    with pytest.raises(ValueError):
        with db.transaction() as conn:
            conn.execute("INSERT INTO t VALUES (1)")
            raise ValueError
    assert db.connection().execute("SELECT count(*) FROM t").fetchone()[0] == 0
