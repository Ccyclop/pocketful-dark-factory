"""The error envelope (§5) and the handlers that put it on every 4xx and 5xx.

Body: {"error": {"code": "<code>", "message": "<human readable>"}}
"""
from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from .responses import JsonResponse

logger = logging.getLogger("pocketful")

# Codes for statuses raised by the framework rather than by our own ApiError.
_FRAMEWORK_CODES = {
    400: "malformed_request",
    401: "unauthenticated",
    403: "forbidden",
    404: "not_found",
    409: "conflict",
    422: "validation_failed",
}


class ApiError(Exception):
    """Raise from any handler to return `status` with the error envelope."""

    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


def error_response(status: int, code: str, message: str) -> JsonResponse:
    return JsonResponse({"error": {"code": code, "message": message}}, status_code=status)


def not_found(message: str = "not found") -> ApiError:
    return ApiError(404, "not_found", message)


async def _api_error(_: Request, exc: ApiError) -> JsonResponse:
    return error_response(exc.status, exc.code, exc.message)


async def _http_error(_: Request, exc: StarletteHTTPException) -> JsonResponse:
    # An unrouted method on a known path is 404, like an unrouted path (D13).
    if exc.status_code in (404, 405):
        return error_response(404, "not_found", "no such resource")
    status = exc.status_code if 400 <= exc.status_code <= 599 else 500
    code = _FRAMEWORK_CODES.get(status, "internal_error" if status >= 500 else "bad_request")
    return error_response(status, code, str(exc.detail))


async def _validation_error(_: Request, exc: RequestValidationError) -> JsonResponse:
    if any(err.get("type") == "json_invalid" for err in exc.errors()):
        return error_response(400, "malformed_request", "request body is not valid JSON")
    return error_response(422, "validation_failed", "request failed validation")


async def _unhandled(_: Request, exc: Exception) -> JsonResponse:
    logger.exception("unhandled error", exc_info=exc)
    return error_response(500, "internal_error", "internal server error")


def install(app: FastAPI) -> None:
    app.add_exception_handler(ApiError, _api_error)
    app.add_exception_handler(StarletteHTTPException, _http_error)
    app.add_exception_handler(RequestValidationError, _validation_error)
    app.add_exception_handler(Exception, _unhandled)
