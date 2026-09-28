"""Black-box acceptance tests for WI-1.1 — stage 1 skeleton / health endpoint."""

import json
import re
import threading
import time

import pytest
import requests

from conftest import (
    IMAGE_NAME,
    REQUEST_TIMEOUT,
    assert_error_envelope,
    assert_json_content_type,
    build_image,
    docker,
    running_container,
)


class TestDeliveryAndRuntime:
    """S1-DEL-1, S1-DEL-2, S1-DEL-3 (startup part), S1-RT-1, S1-RT-2, S1-RT-4."""

    def test_02_health_custom_port(self):
        with running_container(port=9123) as ctx:
            r = requests.get(f"{ctx['url']}/health", timeout=REQUEST_TIMEOUT)
            assert r.status_code == 200
            assert r.json() == {"status": "ok"}
            assert_json_content_type(r)

    def test_02_health_default_port(self):
        with running_container(port=None) as ctx:
            r = requests.get(f"{ctx['url']}/health", timeout=REQUEST_TIMEOUT)
            assert r.status_code == 200
            assert r.json() == {"status": "ok"}
            assert_json_content_type(r)

    def test_03_unknown_path_and_method(self):
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
        with running_container(port=9123) as ctx:
            results, errors = [], []

            def fetch():
                try:
                    results.append(requests.get(f"{ctx['url']}/health", timeout=REQUEST_TIMEOUT))
                except Exception as exc:
                    errors.append(exc)

            start = time.monotonic()
            threads = [threading.Thread(target=fetch) for _ in range(50)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
            assert time.monotonic() - start <= REQUEST_TIMEOUT
            assert not errors
            assert len(results) == 50
            for r in results:
                assert r.status_code == 200
                assert r.json() == {"status": "ok"}
                assert_json_content_type(r)

    def test_repeated_health_is_stable(self):
        with running_container(port=9123) as ctx:
            for _ in range(20):
                r = requests.get(f"{ctx['url']}/health", timeout=REQUEST_TIMEOUT)
                assert r.status_code == 200
                assert r.json() == {"status": "ok"}


class TestNetworkNone:
    """Criterion 6: the image starts and serves /health with --network none."""

    def test_network_none_starts_and_serves_health(self):
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
            assert probe.returncode == 0, probe.stderr
            lines = probe.stdout.strip().splitlines()
            assert lines[0] == "200"
            assert json.loads(lines[-1]) == {"status": "ok"}

    def test_network_none_has_no_external_connectivity(self):
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
            assert probe.stdout.strip() == "blocked"


class TestErrorEnvelope:
    """S1-ERR-1 and criterion 4: every 4xx/5xx carries the error envelope."""

    def test_404_envelope_shape(self):
        with running_container(port=9123) as ctx:
            r = requests.get(f"{ctx['url']}/nope", timeout=REQUEST_TIMEOUT)
            body = r.json()
            assert set(body.keys()) == {"error"}
            assert set(body["error"].keys()) == {"code", "message"}
            assert body["error"]["code"] == "not_found"


class TestNoStageTwoBehavior:
    """Criterion 7: no stage-2 HTML pages are present in the stage-1 image."""

    def test_no_html_at_root(self):
        with running_container(port=9123) as ctx:
            r = requests.get(ctx["url"], timeout=REQUEST_TIMEOUT)
            assert r.status_code == 404
            assert_json_content_type(r)
            assert_error_envelope(r.json(), "not_found")

    def test_image_contains_no_html_templates(self):
        image = build_image()
        result = docker(["run", "--rm", image, "find", "/srv", "-type", "f"])
        assert result.returncode == 0
        files = result.stdout.strip().splitlines()
        htmlish = [f for f in files if re.search(r"\.(html?|jinja2?|j2|htm)$", f, re.IGNORECASE)]
        assert not htmlish, f"stage-1 image contains HTML/template files: {htmlish}"
