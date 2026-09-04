"""BRW-024 Workbench Service API — typed errors + response envelope."""

from __future__ import annotations

import uuid
from enum import Enum
from typing import Any

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


class ErrorCode(str, Enum):
    VALIDATION_ERROR = "VALIDATION_ERROR"
    NOT_FOUND = "NOT_FOUND"
    CONFLICT = "CONFLICT"
    ARTIFACT_NOT_AVAILABLE = "ARTIFACT_NOT_AVAILABLE"
    SCIENTIFIC_ACTION_REQUIRED = "SCIENTIFIC_ACTION_REQUIRED"
    SCIENTIFIC_READINESS_BLOCKED = "SCIENTIFIC_READINESS_BLOCKED"
    INTEGRITY_ERROR = "INTEGRITY_ERROR"
    UNSUPPORTED_OPERATION = "UNSUPPORTED_OPERATION"
    INTERNAL_ERROR = "INTERNAL_ERROR"


HTTP_STATUS: dict[ErrorCode, int] = {
    ErrorCode.VALIDATION_ERROR: 400,
    ErrorCode.NOT_FOUND: 404,
    ErrorCode.CONFLICT: 409,
    ErrorCode.ARTIFACT_NOT_AVAILABLE: 404,
    ErrorCode.SCIENTIFIC_ACTION_REQUIRED: 409,
    ErrorCode.SCIENTIFIC_READINESS_BLOCKED: 409,
    ErrorCode.INTEGRITY_ERROR: 409,
    ErrorCode.UNSUPPORTED_OPERATION: 400,
    ErrorCode.INTERNAL_ERROR: 500,
}


class APIError(Exception):
    def __init__(
        self,
        code: ErrorCode,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.code = code
        self.message = message
        self.details = details or {}
        super().__init__(message)


def new_request_id() -> str:
    return uuid.uuid4().hex[:16]


def request_id_for(request: Request) -> str:
    return getattr(request.state, "request_id", new_request_id())


def error_response(
    code: ErrorCode,
    message: str,
    request_id: str,
    details: dict[str, Any] | list[Any] | None = None,
) -> JSONResponse:
    status = HTTP_STATUS.get(code, 500)
    return JSONResponse(
        status_code=status,
        content={
            "error": {
                "code": code.value,
                "message": message,
                "details": details or {},
                "request_id": request_id,
            }
        },
    )


async def api_error_handler(request: Request, exc: APIError) -> JSONResponse:
    return error_response(exc.code, exc.message, request_id_for(request), exc.details)


async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    safe_errors = [
        {
            "type": item.get("type", "validation_error"),
            "loc": [str(part) for part in item.get("loc", ())],
            "msg": item.get("msg", "invalid request"),
        }
        for item in exc.errors()
    ]
    return error_response(
        ErrorCode.VALIDATION_ERROR,
        "request validation failed",
        request_id_for(request),
        safe_errors,
    )


async def generic_error_handler(request: Request, exc: Exception) -> JSONResponse:
    # Never leak tracebacks or internal paths to the client.
    return error_response(
        ErrorCode.INTERNAL_ERROR,
        "internal server error",
        request_id_for(request),
    )
