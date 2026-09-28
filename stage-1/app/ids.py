"""Server-generated ids: a type prefix and a random suffix (S1-RT-8, D11).

The random suffix keeps generated ids from colliding with seeded or imported ids,
whatever format those use.
"""
from __future__ import annotations

import secrets


def new_id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(8)}"
