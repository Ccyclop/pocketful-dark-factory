"""Parsing request bodies and judging JSON values exactly.

Numbers are parsed as `int` or `Decimal`, never `float`, so an amount is judged by its
exact decimal value (D4): `1000`, `1000.0` and `1e3` are the same integer, `1000.5` is not.
"""
from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation
from typing import Any

from fastapi import Request

from .errors import ApiError

# Integers written with more digits than this are parsed as Decimal, which avoids
# Python's int-from-string digit limit and bounds the work done on hostile input.
_MAX_INT_DIGITS = 40
_INT_BOUND = Decimal(2) ** 64


def _parse_int(text: str) -> int | Decimal:
    return int(text) if len(text) <= _MAX_INT_DIGITS else Decimal(text)


def _reject_constant(name: str) -> Any:
    raise ValueError(f"{name} is not valid JSON")


def malformed(message: str = "request body is not valid JSON") -> ApiError:
    return ApiError(400, "malformed_request", message)


def invalid(message: str) -> ApiError:
    return ApiError(422, "validation_failed", message)


def parse_json(raw: bytes) -> Any:
    """Parse a body; any undecodable or unparseable input is 400 `malformed_request`."""
    try:
        text = raw.decode("utf-8")
        return json.loads(text, parse_float=Decimal, parse_int=_parse_int,
                          parse_constant=_reject_constant)
    except (UnicodeDecodeError, ValueError, RecursionError, InvalidOperation) as exc:
        raise malformed() from exc


async def json_object(request: Request) -> dict[str, Any]:
    """The request body as a JSON object, else 400 `malformed_request`."""
    body = parse_json(await request.body())
    if not isinstance(body, dict):
        raise malformed("request body must be a JSON object")
    return body


def integral(value: Any) -> int | None:
    """The exact integer a JSON number stands for, or None if it is not one.

    Booleans and strings are not numbers. Values beyond ±2^64 are reported as None;
    every caller's valid range is far inside that.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, Decimal):
        if not value.is_finite() or abs(value) > _INT_BOUND:
            return None
        if value != value.to_integral_value():
            return None
        return int(value)
    return None
