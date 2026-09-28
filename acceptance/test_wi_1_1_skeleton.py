"""
Black-box acceptance tests for WI-1.1 — stage 1 skeleton / health endpoint.

These tests treat the service only through its public HTTP interface and Docker
container contract.  They correspond to the acceptance criteria in the work item.
"""

import json
import os
import re
import socket
import subprocess
import threading
import time
from contextlib import contextmanager

import pytest
import requests

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STAGE_DIR = os.path.join(REPO_ROOT, "stage-1")
IMAGE_NAME = "pocketful-stage-1-acceptance"
STARTUP_TIMEOUT = 60  # seconds; S1-RT-2
REQUEST_TIMEOUT = 5  # seconds; S1-DEL-3


def free_port():
    """Return a free TCP port on localhost."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def docker(args, **kwargs):
    """Run a docker CLI command and return its CompletedProcess."""
    cmd = ["docker"] + list(args)
    return subprocess.run(cmd, capture_output=True, text=True, **kwargs)


def build_image():
    result = docker(["build", "-t", IMAGE_NAME, STAGE_DIR], timeout=120)
    assert result.returncode == 0, (
        f"docker build failed:\nstdout={result.stdout}\nstderr={result.stderr}"
    )
    return IMAGE_NAME


@contextmanager
def running_container(
    *,
    port: int | None = None,
    network: str | None = None,
    publish_host: bool = True,
):
    """
    Yield the base URL of a running container (or the container id if the URL is
    not reachable from the host).

    *port* is the internal port; if None the image default 8080 is used.
    *network* is passed as ``--network``; with ``"none"`` host port publishing is
    not available on Docker Desktop, so callers must probe via ``docker exec``.
    """
    image = build_image()
    env = []
    if port is not None:
        env.extend(["-e", f"PORT={port}"])
    internal_port = port if port is not None else 8080
    host_port = free_port()

    cmd = ["run", "--rm", "-d", *env]
    if publish_host and network != "none":
        cmd.extend(["-p", f"{host_port}:{internal_port}"])
    if network:
        cmd.extend(["--network", network])
    cmd.append(image)

    start = docker(cmd)
    assert start.returncode == 0, f"docker run failed: {start.stderr}"
    container_id = start.stdout.strip()
    url = f"http://127.0.0.1:{host_port}"

    try:
        if network == "none":
            # With --network none we cannot reach the host-mapped port on Docker
            # Desktop, so verify readiness by exec'ing into the container.
            deadline = time.monotonic() + STARTUP_TIMEOUT
            healthy = False
            while time.monotonic() < deadline:
                ps = docker(["ps", "-q", "-f", f"id={container_id}"])
                if ps.returncode != 0 or not ps.stdout.strip():
                    raise RuntimeError("container exited before becoming healthy")
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
                if probe.returncode == 0 and '"status":"ok"' in probe.stdout:
                    healthy = True
                    break
                time.sleep(0.2)
            if not healthy:
                raise TimeoutError(
                    f"service did not become healthy within {STARTUP_TIMEOUT}s"
                )
            yield {"url": url, "container_id": container_id, "internal_port": internal_port}
        else:
            deadline = time.monotonic() + STARTUP_TIMEOUT
            while time.monotonic() < deadline:
                ps = docker(["ps", "-q", "-f", f"id={container_id}"])
                if ps.returncode != 0 or not ps.stdout.strip():
                    raise RuntimeError("container exited before becoming healthy")
                try:
                    r = requests.get(f"{url}/health", timeout=1)
                    if r.status_code == 200:
                        break
                except Exception:
                    pass
                time.sleep(0.2)
            else:
                raise TimeoutError(
                    f"service did not become healthy within {STARTUP_TIMEOUT}s"
                )
            yield {"url": url, "container_id": container_id, "internal_port": internal_port}
    finally:
        docker(["stop", "-t", "5", container_id], timeout=30)
        docker(["rm", "-f", container_id], timeout=30)


def assert_json_content_type(response: requests.Response):
    ct = response.headers.get("Content-Type", "")
    assert ct == "application/json; charset=utf-8", f"Content-Type was {ct!r}"


def assert_error_envelope(body: dict, code: str):
    assert "error" in body, f"missing error envelope: {body}"
    err = body["error"]
    assert set(err.keys()) == {"code", "message"}, f"error shape wrong: {err}"
    assert err.get("code") == code, f"expected code {code!r}, got {err.get('code')!r}"
    assert isinstance(err.get("message"), str), "error.message must be a string"


class TestDeliveryAndRuntime:
    """S1-DEL-1, S1-DEL-2, S1-DEL-3 (startup part), S1-RT-1, S1-RT-2, S1-RT-4."""

    def test_02_health_custom_port(self):
        """Criterion 2: custom PORT -> /health 200 ok, JSON content type, within 60s."""
        with running_container(port=9123) as ctx:
            r = requests.get(f"{ctx['url']}/health", timeout=REQUEST_TIMEOUT)
            assert r.status_code == 200
            assert r.json() == {"status": "ok"}
            assert_json_content_type(r)

    def test_02_health_default_port(self):
        """Criterion 2: without -e PORT the service listens on 8080."""
        with running_container(port=None) as ctx:
            r = requests.get(f"{ctx['url']}/health", timeout=REQUEST_TIMEOUT)
            assert r.status_code == 200
            assert r.json() == {"status": "ok"}
            assert_json_content_type(r)

    def test_03_unknown_path_and_method(self):
        """Criterion 3: GET /nope and DELETE /health are 404 not_found with envelope."""
        with running_container(port=9123) as ctx:
            r_get = requests.get(f"{ctx['url']}/nope", timeout=REQUEST_TIMEOUT)
            assert r_get.status_code == 404
            assert_json_content_type(r_get)
            assert_error_envelope(r_get.json(), "not_found")

            r_del = requests.delete(f"{ctx['url']}/health", timeout=REQUEST_TIMEOUT)
            assert r_del.status_code == 404
            assert_json_content_type(r_del)
            assert_error_envelope(r_del.json(), "not_found")

    def test_05_concurrent_health(self):
        """Criterion 5: 50 concurrent GET /health all return 200 within 5s."""
        with running_container(port=9123) as ctx:
            results = []
            errors = []

            def fetch():
                try:
                    r = requests.get(f"{ctx['url']}/health", timeout=REQUEST_TIMEOUT)
                    results.append(r)
                except Exception as exc:
                    errors.append(exc)

            start = time.monotonic()
            threads = [threading.Thread(target=fetch) for _ in range(50)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
            elapsed = time.monotonic() - start
            assert elapsed <= REQUEST_TIMEOUT, f"concurrent fetch took {elapsed:.2f}s"

            assert not errors, f"concurrent requests raised exceptions: {errors[:3]}"
            assert len(results) == 50
            for r in results:
                assert r.status_code == 200, f"unexpected status {r.status_code}: {r.text}"
                assert r.json() == {"status": "ok"}
                assert_json_content_type(r)

    def test_repeated_health_is_stable(self):
        """Repeated identical requests are stable (part of S1-INV-7 for this endpoint)."""
        with running_container(port=9123) as ctx:
            for _ in range(20):
                r = requests.get(f"{ctx['url']}/health", timeout=REQUEST_TIMEOUT)
                assert r.status_code == 200
                assert r.json() == {"status": "ok"}


class TestNetworkNone:
    """Criterion 6: the image starts and serves /health with ``--network none``."""

    def test_network_none_starts_and_serves_health(self):
        """
        The delivered command includes ``--network none``.  On Docker Desktop the
        host port is not published for network=none, so we verify the service by
        executing a Python HTTP client inside the container's loopback namespace.
        """
        with running_container(port=9123, network="none") as ctx:
            probe = docker(
                [
                    "exec",
                    ctx["container_id"],
                    "python",
                    "-c",
                    (
                        "import json, urllib.request; "
                        f"r = urllib.request.urlopen('http://127.0.0.1:{ctx['internal_port']}/health', timeout=5); "
                        "print(r.status); print(dict(r.headers)); print(r.read().decode())"
                    ),
                ],
                timeout=10,
            )
            assert probe.returncode == 0, f"exec probe failed: {probe.stderr}"
            lines = probe.stdout.strip().splitlines()
            assert lines[0] == "200"
            body = json.loads(lines[-1])
            assert body == {"status": "ok"}

    def test_network_none_has_no_external_connectivity(self):
        """A network=none container cannot reach the public internet."""
        with running_container(port=9123, network="none") as ctx:
            probe = docker(
                [
                    "exec",
                    ctx["container_id"],
                    "python",
                    "-c",
                    (
                        "import socket; s = socket.socket(socket.AF_INET, socket.SOCK_STREAM); "
                        "s.settimeout(3); "
                        "rc = s.connect_ex(('1.1.1.1', 53)); "
                        "print('connected' if rc == 0 else 'blocked')"
                    ),
                ],
                timeout=10,
            )
            assert probe.returncode == 0
            assert probe.stdout.strip() == "blocked", "container had outbound network access"


class TestErrorEnvelope:
    """S1-ERR-1 and criterion 4: every 4xx/5xx carries the error envelope."""

    def test_404_envelope_shape(self):
        """404 body is exactly the required shape with code not_found."""
        with running_container(port=9123) as ctx:
            r = requests.get(f"{ctx['url']}/nope", timeout=REQUEST_TIMEOUT)
            body = r.json()
            assert set(body.keys()) == {"error"}
            assert set(body["error"].keys()) == {"code", "message"}
            assert body["error"]["code"] == "not_found"


class TestNoStageTwoBehavior:
    """Criterion 7: no stage-2 HTML pages are present in the stage-1 image."""

    def test_no_html_at_root(self):
        """Root path should not serve an HTML page."""
        with running_container(port=9123) as ctx:
            r = requests.get(ctx["url"], timeout=REQUEST_TIMEOUT)
            assert r.status_code == 404
            assert_json_content_type(r)
            assert_error_envelope(r.json(), "not_found")

    def test_image_contains_no_html_templates(self):
        """The container image has no HTML/Jinja templates that would imply screens."""
        image = build_image()
        result = docker(["run", "--rm", image, "find", "/srv", "-type", "f"])
        assert result.returncode == 0
        files = result.stdout.strip().splitlines()
        htmlish = [
            f
            for f in files
            if re.search(r"\.(html?|jinja2?|j2|htm)$", f, re.IGNORECASE)
        ]
        assert not htmlish, f"stage-1 image contains HTML/template files: {htmlish}"
