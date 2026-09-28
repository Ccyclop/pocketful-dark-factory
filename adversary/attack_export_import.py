#!/usr/bin/env python3
"""Export/import attacks: atomicity, round trips, invalid imports."""
from __future__ import annotations

import json
import threading
import time
import uuid
from attack_common import req, record, reset_fixture, login, auth_headers


def attack_export_import():
    print("\n=== EXPORT/IMPORT ATTACKS ===")

    # Round trip
    reset_fixture()
    _, t_ada = login("ada@example.com")
    _, t_bob = login("bob@example.com")
    req("POST", "/payments", {"to_handle": "bob", "amount": 1500, "note": "test"},
        auth_headers(t_ada, uuid.uuid4().hex))
    _, export, _ = req("GET", "/_test/export")
    reset_fixture()
    s, _, _ = req("POST", "/_test/import", export)
    record("export_import", "round_trip", s == 204, f"status={s}")

    # Tokens survive import
    reset_fixture()
    _, t_ada = login("ada@example.com")
    _, export, _ = req("GET", "/_test/export")
    reset_fixture()
    req("POST", "/_test/import", export)
    s, r, _ = req("GET", "/me", headers=auth_headers(t_ada))
    record("export_import", "tokens_survive", s == 200 and r.get("handle") == "ada", f"status={s}")

    # Idempotent retries survive import
    reset_fixture()
    _, t_ada = login("ada@example.com")
    k = uuid.uuid4().hex
    s1, r1, _ = req("POST", "/payments", {"to_handle": "bob", "amount": 1500, "note": "n"},
                     auth_headers(t_ada, k))
    _, export, _ = req("GET", "/_test/export")
    reset_fixture()
    req("POST", "/_test/import", export)
    _, t_ada = login("ada@example.com")
    s2, r2, _ = req("POST", "/payments", {"to_handle": "bob", "amount": 1500, "note": "n"},
                     auth_headers(t_ada, k))
    record("export_import", "idem_survives", s1 == 201 and s2 == 200 and r1 == r2, f"{s1}->{s2}")

    # Invalid import leaves state unchanged
    reset_fixture()
    _, t_ada = login("ada@example.com")
    req("POST", "/payments", {"to_handle": "bob", "amount": 1500, "note": "test"},
        auth_headers(t_ada, uuid.uuid4().hex))
    _, export, _ = req("GET", "/_test/export")
    bad = json.loads(json.dumps(export))
    bad["track"] = "wrong"
    s, _, _ = req("POST", "/_test/import", bad)
    _, r, _ = req("GET", "/me", headers=auth_headers(t_ada))
    record("export_import", "invalid_no_change", s == 422 and r.get("balance") == 8500, f"status={s}")

    # Reset after import
    reset_fixture()
    _, t_ada = login("ada@example.com")
    _, export, _ = req("GET", "/_test/export")
    req("POST", "/_test/import", export)
    reset_fixture()
    s, _, _ = req("GET", "/me", headers=auth_headers(t_ada))
    record("export_import", "reset_after_import", s == 401, f"status={s}")

    # Export atomicity under concurrent writes
    reset_fixture()
    _, t_ada = login("ada@example.com")
    _, t_bob = login("bob@example.com")
    stop = threading.Event()
    def writer():
        while not stop.is_set():
            req("POST", "/payments", {"to_handle": "bob", "amount": 1},
                auth_headers(t_ada, uuid.uuid4().hex))
    threads = [threading.Thread(target=writer) for _ in range(5)]
    for t in threads:
        t.start()
    time.sleep(0.5)
    _, export, _ = req("GET", "/_test/export")
    stop.set()
    for t in threads:
        t.join()
    has_tables = isinstance(export, dict) and "state" in export and "tables" in export.get("state", {})
    record("export_import", "atomic_under_writes", has_tables, f"has_tables={has_tables}")

    # Import with missing fields
    reset_fixture()
    _, export, _ = req("GET", "/_test/export")
    for field in ["track", "format_version", "state"]:
        bad = json.loads(json.dumps(export))
        del bad[field]
        s, _, _ = req("POST", "/_test/import", bad)
        record("export_import", f"missing_{field}", s == 422, f"status={s}")

    # Import with wrong version
    reset_fixture()
    _, export, _ = req("GET", "/_test/export")
    bad = json.loads(json.dumps(export))
    bad["format_version"] = 2
    s, _, _ = req("POST", "/_test/import", bad)
    record("export_import", "wrong_version", s == 422, f"status={s}")

    # Import with extra tables
    reset_fixture()
    _, export, _ = req("GET", "/_test/export")
    bad = json.loads(json.dumps(export))
    bad["state"]["tables"]["extra"] = {"columns": ["id"], "rows": [["x"]]}
    s, _, _ = req("POST", "/_test/import", bad)
    record("export_import", "extra_table", s == 422, f"status={s}")


if __name__ == "__main__":
    attack_export_import()
    from attack_common import summary
    ok = summary()
    exit(0 if ok else 1)
