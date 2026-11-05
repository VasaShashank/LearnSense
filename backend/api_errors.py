"""One error envelope for every API error (docs/contracts/api-errors.md).

    {"error": "<CATEGORY>", "code": "<SPECIFIC_CODE>", "message": "<safe text>",
     "recoverable": false, "details": {}, "detail": <legacy>}

``detail`` is retained for backward compatibility with existing clients and is
always equal to ``message`` except for 422, where it keeps FastAPI's error list.
Messages never contain tokens, SQL, stack traces or other tenants' identifiers.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException as StarletteHTTPException

from phase3.errors import LearnSenseError

CATEGORY_BY_STATUS = {
    400: "INVALID_REQUEST",
    401: "AUTHENTICATION_ERROR",
    403: "AUTHORIZATION_ERROR",
    404: "NOT_FOUND",
    409: "CONFLICT",
    422: "VALIDATION_ERROR",
    429: "QUOTA_EXCEEDED",
    503: "SERVICE_UNAVAILABLE",
}
DEFAULT_CODE_BY_STATUS = {
    400: "INVALID_REQUEST",
    401: "AUTHENTICATION_REQUIRED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    405: "METHOD_NOT_ALLOWED",
    409: "CONFLICT",
    422: "REQUEST_VALIDATION_FAILED",
    429: "RATE_LIMITED",
    503: "SERVICE_UNAVAILABLE",
}


def category_for(status: int) -> str:
    if status in CATEGORY_BY_STATUS:
        return CATEGORY_BY_STATUS[status]
    return "SERVER_ERROR" if status >= 500 else "INVALID_REQUEST"


class ErrorEnvelope(BaseModel):
    """OpenAPI schema of every error response."""

    error: str = Field(description="Category derived from the HTTP status")
    code: str = Field(description="Specific machine-readable code")
    message: str = Field(description="Safe, human-readable message")
    recoverable: bool = False
    details: Dict[str, Any] = Field(default_factory=dict)
    detail: Any = Field(default=None, description="Deprecated alias of message (422: validation errors)")


def _responses(*statuses: int) -> Dict[int, Dict[str, Any]]:
    return {s: {"model": ErrorEnvelope, "description": category_for(s)} for s in statuses}


AUTH_ERRORS = _responses(401, 403, 503)
CONCEALED_ERRORS = _responses(401, 403, 404, 503)


class ApiError(HTTPException):
    """HTTP error with a specific code. Subclasses FastAPI's HTTPException so existing
    ``except HTTPException: raise`` blocks keep propagating it."""

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        *,
        details: Optional[Dict[str, Any]] = None,
        recoverable: bool = False,
        headers: Optional[Dict[str, str]] = None,
    ):
        super().__init__(status_code=status_code, detail=message, headers=headers)
        self.code = code
        self.message = message
        self.details = details or {}
        self.recoverable = recoverable


def envelope(
    status: int,
    *,
    code: Optional[str],
    message: str,
    recoverable: bool = False,
    details: Optional[Dict[str, Any]] = None,
    detail: Any = None,
) -> Dict[str, Any]:
    return {
        "error": category_for(status),
        "code": code or DEFAULT_CODE_BY_STATUS.get(status, "ERROR"),
        "message": message,
        "recoverable": recoverable,
        "details": details or {},
        "detail": message if detail is None else detail,
    }


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException):
        if isinstance(exc, ApiError):
            body = envelope(
                exc.status_code, code=exc.code, message=exc.message,
                recoverable=exc.recoverable, details=exc.details,
            )
        else:
            message = exc.detail if isinstance(exc.detail, str) else "Request failed."
            body = envelope(
                exc.status_code, code=None, message=message,
                recoverable=exc.status_code >= 500 or exc.status_code == 429,
                detail=exc.detail if exc.detail is not None else message,
            )
        return JSONResponse(status_code=exc.status_code, content=body, headers=getattr(exc, "headers", None))

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        errors = jsonable_encoder(exc.errors())
        return JSONResponse(
            status_code=422,
            content=envelope(
                422, code="REQUEST_VALIDATION_FAILED", message="The request was invalid.",
                details={"errors": errors}, detail=errors,
            ),
        )

    @app.exception_handler(LearnSenseError)
    async def learnsense_error_handler(request: Request, exc: LearnSenseError):
        """Typed runtime errors keep their code and retry state (recoverable → Retry-After)."""
        return JSONResponse(
            status_code=exc.http_status,
            content=envelope(
                exc.http_status, code=exc.code, message=str(exc),
                recoverable=exc.recoverable, details=exc.details,
            ),
            headers={"Retry-After": "5"} if exc.recoverable else None,
        )

    @app.exception_handler(ValueError)
    async def value_error_handler(request: Request, exc: ValueError):
        return JSONResponse(
            status_code=400,
            content=envelope(400, code="VALIDATION_ERROR", message=str(exc)),
        )
