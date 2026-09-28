"""`limit` and `offset` query parameters, shared by the list endpoints (§5, §8).

An integer query parameter is plain decimal digits (S1-ERR-11): `1e9`, `4.0`, `+4` and
the empty string are 422 `validation_failed`, like any value outside the range.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from fastapi import Request

from .jsonbody import invalid

_DIGITS = re.compile(r"[0-9]+")
LIMIT_DEFAULT = 50
LIMIT_MAX = 200


@dataclass(frozen=True)
class Page:
    limit: int
    offset: int


def _integer(request: Request, name: str, default: int) -> int:
    raw = request.query_params.get(name)
    if raw is None:
        return default
    if not _DIGITS.fullmatch(raw):
        raise invalid(f"`{name}` must be written as plain decimal digits")
    # Strip leading zeros so an absurdly long value cannot hit the int digit limit.
    digits = raw.lstrip("0") or "0"
    return int(digits) if len(digits) <= 18 else 10 ** 18


def page(request: Request) -> Page:
    """Use as `Depends(page)`, after `Depends(current_user)`."""
    limit = _integer(request, "limit", LIMIT_DEFAULT)
    if not 1 <= limit <= LIMIT_MAX:
        raise invalid(f"`limit` must be from 1 to {LIMIT_MAX}")
    offset = _integer(request, "offset", 0)
    return Page(limit=limit, offset=offset)
