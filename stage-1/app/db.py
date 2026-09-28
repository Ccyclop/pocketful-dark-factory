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

# Tables are added by the work items that need them.
SCHEMA: list[str] = []


class Database:
    def __init__(self, path: str) -> None:
        self.path = path
        self._local = threading.local()

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
        with self._transaction(self.connection()) as conn:
            yield conn

    def ping(self) -> bool:
        return self.connection().execute("SELECT 1").fetchone()[0] == 1
