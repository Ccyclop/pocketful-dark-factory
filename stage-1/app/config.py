"""Runtime settings, read from the environment."""
from __future__ import annotations

import os
from dataclasses import dataclass

DEFAULT_PORT = 8080
DEFAULT_DATABASE_PATH = "/tmp/pocketful/pocketful.sqlite3"


@dataclass(frozen=True)
class Settings:
    host: str
    port: int
    database_path: str


def load_settings() -> Settings:
    port = os.environ.get("PORT", "").strip()
    return Settings(
        host="0.0.0.0",
        port=int(port) if port else DEFAULT_PORT,
        database_path=os.environ.get("DATABASE_PATH", DEFAULT_DATABASE_PATH),
    )
