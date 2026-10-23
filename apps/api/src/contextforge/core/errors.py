"""Typed application errors and the single place they become HTTP responses.

The body shape is compatible with OpenAI SDK error parsing (``error.message``,
``error.type``, ``error.code``) and adds ``details`` for structured context, so gateway
clients and the dashboard read the same envelope.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger("contextforge.errors")


class AppError(Exception):
    status_code = 400
    code = "bad_request"
    type = "invalid_request_error"

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        details: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        if code:
            self.code = code
        self.details = details or {}
        self.headers = headers or {}

    def body(self) -> dict[str, Any]:
        return {
            "error": {
                "code": self.code,
                "type": self.type,
                "message": self.message,
                "details": self.details,
            }
        }


class NotFoundError(AppError):
    status_code = 404
    code = "not_found"


class ConflictError(AppError):
    status_code = 409
    code = "conflict"


class AuthenticationError(AppError):
    status_code = 401
    code = "unauthenticated"
    type = "authentication_error"


class PermissionDeniedError(AppError):
    status_code = 403
    code = "forbidden"
    type = "permission_error"


class UnsupportedTokenizerError(AppError):
    status_code = 422
    code = "unsupported_tokenizer"


class BudgetUnsatisfiableError(AppError):
    """Strict mode: the budget cannot be met without dropping protected or required content."""

    status_code = 422
    code = "budget_unsatisfiable"
    type = "budget_error"


class PayloadTooLargeError(AppError):
    status_code = 413
    code = "payload_too_large"


class RateLimitedError(AppError):
    status_code = 429
    code = "rate_limited"
    type = "rate_limit_error"


class UpstreamError(AppError):
    status_code = 502
    code = "upstream_error"
    type = "api_error"


class UpstreamTimeoutError(AppError):
    status_code = 504
    code = "upstream_timeout"
    type = "api_error"


class DependencyUnavailableError(AppError):
    status_code = 503
    code = "dependency_unavailable"
    type = "api_error"


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(exc.body(), status_code=exc.status_code, headers=exc.headers)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        errors = [
            {"loc": list(e.get("loc", [])), "msg": e.get("msg", ""), "type": e.get("type", "")}
            for e in exc.errors()
        ]
        err = AppError("Request validation failed", code="validation_error")
        err.details = {"errors": errors}
        return JSONResponse(err.body(), status_code=422)

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        err = AppError(str(exc.detail), code="http_error")
        return JSONResponse(err.body(), status_code=exc.status_code)

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        log.exception("unhandled error", extra={"path": request.url.path})
        err = AppError("Internal server error", code="internal_error")
        err.type = "api_error"
        return JSONResponse(err.body(), status_code=500)
