"""Shared helpers and fixtures for stage-1 acceptance tests."""

import json
import os
import socket
import subprocess
import time
from contextlib import contextmanager

import pytest
import requests

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STAGE_DIR = os.path.join(REPO_ROOT, "stage-1")
IMAGE_NAME = "pocketful-stage-1-acceptance"
STARTUP_TIMEOUT = 60
REQUEST_TIMEOUT = 5
RESET_TIMEOUT = 10


def free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def docker(args, **kwargs):
    cmd = ["docker"] + list(args)
    return subprocess.run(cmd, capture_output=True, text=True, **kwargs)


def build_image():
    result = docker(["build", "-t", IMAGE_NAME, STAGE_DIR], timeout=120)
    if result.returncode != 0:
        raise RuntimeError(f"docker build failed:\n{result.stdout}\n{result.stderr}")
    return IMAGE_NAME


@contextmanager
def running_container(port: int | None = 8123, network: str | None = None):
    """Yield a context dict with url/container_id/internal_port.

    With network="none" the host port is not published; tests must probe via
    docker exec (the helper does this during startup).
    """
    image = build_image()
    env = []
    if port is not None:
        env.extend(["-e", f"PORT={port}"])
    internal_port = port if port is not None else 8080
    host_port = free_port()
    cmd = ["run", "--rm", "-d", *env]
    if network != "none":
        cmd.extend(["-p", f"{host_port}:{internal_port}"])
    if network:
        cmd.extend(["--network", network])
    cmd.append(image)

    start = docker(cmd)
    if start.returncode != 0:
        raise RuntimeError(f"docker run failed: {start.stderr}")
    container_id = start.stdout.strip()
    url = f"http://127.0.0.1:{host_port}"

    try:
        deadline = time.monotonic() + STARTUP_TIMEOUT
        while time.monotonic() < deadline:
            ps = docker(["ps", "-q", "-f", f"id={container_id}"])
            if ps.returncode != 0 or not ps.stdout.strip():
                raise RuntimeError("container exited before becoming healthy")
            if _is_healthy(container_id, host_port, internal_port, network):
                break
            time.sleep(0.2)
        else:
            raise TimeoutError(f"service did not become healthy within {STARTUP_TIMEOUT}s")
        yield {"url": url, "container_id": container_id, "internal_port": internal_port}
    finally:
        docker(["stop", "-t", "5", container_id], timeout=30)
        docker(["rm", "-f", container_id], timeout=30)


def _is_healthy(container_id: str, host_port: int, internal_port: int, network: str | None) -> bool:
    if network == "none":
        probe = docker(
            [
                "exec",
                container_id,
                "python",
                "-c",
                (
                    "import urllib.request; "
                    f"print(urllib.request.urlopen('http://127.0.0.1:{internal_port}/health', timeout=1).read().decode())"
                ),
            ],
            timeout=2,
        )
        return probe.returncode == 0 and '"status":"ok"' in probe.stdout
    try:
        r = requests.get(f"http://127.0.0.1:{host_port}/health", timeout=1)
        return r.status_code == 200
    except Exception:
        return False


def assert_json_content_type(response: requests.Response):
    ct = response.headers.get("Content-Type", "")
    assert ct == "application/json; charset=utf-8", f"Content-Type was {ct!r}"


def assert_error_envelope(body: dict, code: str):
    assert "error" in body, f"missing error envelope: {body}"
    err = body["error"]
    assert set(err.keys()) == {"code", "message"}, f"error shape wrong: {err}"
    assert err.get("code") == code, f"expected code {code!r}, got {err.get('code')!r}"
    assert isinstance(err.get("message"), str), "error.message must be a string"


def api_post(ctx: dict, path: str, *, json_body=None, token: str | None = None, timeout=REQUEST_TIMEOUT):
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return requests.post(f"{ctx['url']}{path}", json=json_body, headers=headers, timeout=timeout)


def api_get(ctx: dict, path: str, *, token: str | None = None, params: dict | None = None, timeout=REQUEST_TIMEOUT):
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return requests.get(f"{ctx['url']}{path}", params=params, headers=headers, timeout=timeout)


def eur_fixture():
    return {
        "currency": "EUR",
        "minor_units": 2,
        "users": [
            {
                "id": "u_ada",
                "email": "ada@example.com",
                "password": "correct horse",
                "display_name": "Ada",
                "handle": "ada",
                "balance": 10000,
            },
            {
                "id": "u_bob",
                "email": "bob@example.com",
                "password": "battery stapler",
                "display_name": "Bob",
                "handle": "bob",
                "balance": 2500,
            },
        ],
        "payments": [],
        "requests": [],
    }


def reset(ctx: dict, fixture: dict):
    r = api_post(ctx, "/_test/reset", json_body=fixture, timeout=RESET_TIMEOUT)
    assert r.status_code == 204, f"reset failed: {r.status_code} {r.text}"
    assert r.text == "", "reset body must be empty"


def login(ctx: dict, email: str, password: str) -> dict:
    r = api_post(ctx, "/auth/login", json_body={"email": email, "password": password})
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
    assert_json_content_type(r)
    body = r.json()
    assert "token" in body and body["token"]
    return body


def signup(ctx: dict, email: str, password: str, display_name: str) -> requests.Response:
    return api_post(
        ctx,
        "/auth/signup",
        json_body={"email": email, "password": password, "display_name": display_name},
    )


def me(ctx: dict, token: str) -> requests.Response:
    return api_get(ctx, "/me", token=token)


def pay(ctx: dict, token: str, key: str | None, body: dict) -> requests.Response:
    headers = {"Authorization": f"Bearer {token}"}
    if key is not None:
        headers["Idempotency-Key"] = key
    return requests.post(
        f"{ctx['url']}/payments",
        json=body,
        headers=headers,
        timeout=REQUEST_TIMEOUT,
    )


def activity(ctx: dict, token: str, params: dict | None = None) -> requests.Response:
    return api_get(ctx, "/activity", token=token, params=params)
