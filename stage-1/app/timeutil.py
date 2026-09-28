"""Timestamps: RFC 3339, UTC, second precision (D10)."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def now() -> tuple[str, float]:
    """The current time as (RFC 3339 string, epoch seconds for ordering)."""
    moment = datetime.now(timezone.utc).replace(microsecond=0)
    return moment.isoformat(), moment.timestamp()


def parse_rfc3339(value: Any) -> tuple[str, float] | None:
    """(the string as given, epoch seconds) for a valid RFC 3339 timestamp with an
    explicit offset, else None."""
    if not isinstance(value, str) or len(value) < 20 or value[10] not in "Tt":
        return None
    try:
        moment = datetime.fromisoformat(value.replace("z", "Z"))
    except ValueError:
        return None
    if moment.tzinfo is None:
        return None
    return value, moment.timestamp()
