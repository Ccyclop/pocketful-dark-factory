"""Field rules shared by the write endpoints (§5, §8).

`amount`, `note` and `visibility` are always 422 when invalid, whatever the JSON type
(S1-ERR-10). Other fields of the wrong JSON type are 400 (D5).
"""
from __future__ import annotations

from typing import Any

from .jsonbody import integral, invalid, malformed

MAX_AMOUNT = 1_000_000_000
NOTE_MAX = 200
VISIBILITIES = ("public", "private")


def check_string_types(body: dict[str, Any], names: tuple[str, ...]) -> None:
    """A present field that is not a string (incl. null) is 400 `malformed_request`."""
    for name in names:
        if name in body and not isinstance(body[name], str):
            raise malformed(f"`{name}` must be a string")


def required(body: dict[str, Any], name: str) -> Any:
    if name not in body:
        raise invalid(f"`{name}` is required")
    return body[name]


def amount(body: dict[str, Any], minimum: int = 1) -> int:
    """A required amount: an integral JSON number in minimum..1000000000 (D4)."""
    value = integral(required(body, "amount"))
    if value is None or not minimum <= value <= MAX_AMOUNT:
        raise invalid(f"`amount` must be an integer from {minimum} to {MAX_AMOUNT}")
    return value


def note(body: dict[str, Any]) -> str:
    """Optional, default "". Stored verbatim; at most 200 code points (D7)."""
    if "note" not in body:
        return ""
    value = body["note"]
    if not isinstance(value, str) or len(value) > NOTE_MAX:
        raise invalid(f"`note` must be a string of at most {NOTE_MAX} characters")
    return value


def visibility(body: dict[str, Any]) -> str:
    """Optional, default "public"."""
    if "visibility" not in body:
        return "public"
    value = body["visibility"]
    if value not in VISIBILITIES or not isinstance(value, str):
        raise invalid("`visibility` must be \"public\" or \"private\"")
    return value
