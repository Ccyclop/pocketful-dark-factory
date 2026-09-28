"""SQLite data store: connections, schema and the transaction helper.

Every write goes through `Database.transaction()`, which opens a `BEGIN IMMEDIATE`
transaction. SQLite then allows one writer at a time, so a check and the write that
depends on it, done inside one transaction, are a single atomic step.
"""
from __future__ import annotations

import contextlib
import os
import sqlite3
import threading
from collections.abc import Iterator

BUSY_TIMEOUT_MS = 5000

# The largest balance any wallet may hold (§4: no balance outside ±2^53).
MAX_BALANCE = 2 ** 53

SCHEMA: list[str] = [
    # One row: the service's currency, declared by the last reset.
    """CREATE TABLE service (
        id          INTEGER PRIMARY KEY CHECK (id = 1),
        currency    TEXT    NOT NULL,
        minor_units INTEGER NOT NULL
    )""",
    f"""CREATE TABLE users (
        seq           INTEGER PRIMARY KEY AUTOINCREMENT,
        id            TEXT    NOT NULL UNIQUE,
        email         TEXT    NOT NULL,
        email_key     TEXT    NOT NULL UNIQUE,
        password_hash TEXT    NOT NULL,
        display_name  TEXT    NOT NULL,
        handle        TEXT    NOT NULL UNIQUE,
        balance       INTEGER NOT NULL CHECK (balance >= 0 AND balance <= {MAX_BALANCE}),
        is_operator   INTEGER NOT NULL DEFAULT 0
    )""",
    # Only a digest of each bearer token is stored.
    """CREATE TABLE tokens (
        token_hash TEXT PRIMARY KEY,
        user_id    TEXT NOT NULL REFERENCES users (id)
    )""",
    """CREATE INDEX tokens_user ON tokens (user_id)""",
    # created_ts orders rows by time whatever offset created_at was written with.
    """CREATE TABLE payments (
        seq           INTEGER PRIMARY KEY AUTOINCREMENT,
        id            TEXT    NOT NULL UNIQUE,
        from_user_id  TEXT    NOT NULL REFERENCES users (id),
        to_user_id    TEXT    NOT NULL REFERENCES users (id),
        amount        INTEGER NOT NULL,
        note          TEXT    NOT NULL,
        visibility    TEXT    NOT NULL CHECK (visibility IN ('public', 'private')),
        request_id    TEXT,
        settlement_id TEXT,
        created_at    TEXT    NOT NULL,
        created_ts    REAL    NOT NULL
    )""",
    """CREATE INDEX payments_from ON payments (from_user_id)""",
    """CREATE INDEX payments_to ON payments (to_user_id)""",
    """CREATE TABLE requests (
        seq          INTEGER PRIMARY KEY AUTOINCREMENT,
        id           TEXT    NOT NULL UNIQUE,
        requester_id TEXT    NOT NULL REFERENCES users (id),
        payer_id     TEXT    NOT NULL REFERENCES users (id),
        amount       INTEGER NOT NULL,
        note         TEXT    NOT NULL,
        status       TEXT    NOT NULL
                     CHECK (status IN ('pending', 'paid', 'declined', 'cancelled')),
        payment_id   TEXT,
        created_at   TEXT    NOT NULL,
        created_ts   REAL    NOT NULL
    )""",
    """CREATE INDEX requests_requester ON requests (requester_id)""",
    """CREATE INDEX requests_payer ON requests (payer_id)""",
    # A split's own record; its requests are ordinary rows in `requests`.
    """CREATE TABLE splits (
        seq          INTEGER PRIMARY KEY AUTOINCREMENT,
        id           TEXT    NOT NULL UNIQUE,
        requester_id TEXT    NOT NULL REFERENCES users (id),
        amount       INTEGER NOT NULL,
        note         TEXT    NOT NULL,
        created_at   TEXT    NOT NULL,
        created_ts   REAL    NOT NULL
    )""",
    # One row per claimed idempotency key (D2): only a 2xx outcome is stored.
    """CREATE TABLE idempotency (
        user_id     TEXT    NOT NULL REFERENCES users (id),
        method      TEXT    NOT NULL,
        path        TEXT    NOT NULL,
        key         TEXT    NOT NULL,
        fingerprint TEXT    NOT NULL,
        status      INTEGER NOT NULL,
        response    TEXT    NOT NULL,
        PRIMARY KEY (user_id, method, path, key)
    )""",
]

# Every table holding service state, children first, so clearing respects foreign keys.
STATE_TABLES = ("idempotency", "tokens", "payments", "requests", "splits", "users",
                "service")


class Database:
    def __init__(self, path: str) -> None:
        self.path = path
        self._local = threading.local()
        # One writer at a time, queued here rather than in SQLite's busy-retry loop.
        self._write_lock = threading.Lock()

    def initialize(self, fresh: bool = True) -> None:
        """Create the database file and schema. State need not survive a restart."""
        directory = os.path.dirname(self.path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        if fresh:
            for suffix in ("", "-wal", "-shm"):
                with contextlib.suppress(FileNotFoundError):
                    os.remove(self.path + suffix)
        conn = self._connect()
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            with self._transaction(conn):
                for statement in SCHEMA:
                    conn.execute(statement)
        finally:
            conn.close()

    def _connect(self) -> sqlite3.Connection:
        # isolation_level=None: transactions are opened explicitly by transaction().
        conn = sqlite3.connect(self.path, isolation_level=None, check_same_thread=False,
                               timeout=BUSY_TIMEOUT_MS / 1000)
        conn.row_factory = sqlite3.Row
        conn.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def connection(self) -> sqlite3.Connection:
        """This thread's connection, opened on first use."""
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = self._connect()
            self._local.conn = conn
        return conn

    @staticmethod
    @contextlib.contextmanager
    def _transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
        conn.execute("BEGIN IMMEDIATE")
        try:
            yield conn
        except BaseException:
            conn.execute("ROLLBACK")
            raise
        conn.execute("COMMIT")

    @contextlib.contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """A write transaction: commits on success, rolls back on any exception."""
        with self._write_lock, self._transaction(self.connection()) as conn:
            yield conn

    @contextlib.contextmanager
    def snapshot(self) -> Iterator[sqlite3.Connection]:
        """A read transaction: every query inside sees one consistent state."""
        conn = self.connection()
        conn.execute("BEGIN")
        try:
            yield conn
        finally:
            conn.execute("ROLLBACK")

    def ping(self) -> bool:
        return self.connection().execute("SELECT 1").fetchone()[0] == 1


def clear_state(conn: sqlite3.Connection) -> None:
    """Delete all service state. Call inside a transaction."""
    for table in STATE_TABLES:
        conn.execute(f"DELETE FROM {table}")
