"""Map domain errors to HTTP status codes."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from memory_workbench.domain.errors import (
    InvalidTransition,
    MemoryError,
    MemoryNotFound,
    ScopeViolation,
    SecretContent,
    ValidationError,
)


def to_http(exc: Exception) -> HTTPException:
    if isinstance(exc, MemoryNotFound):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, ScopeViolation):
        return HTTPException(status_code=403, detail=str(exc))
    if isinstance(exc, SecretContent):
        return HTTPException(status_code=422, detail=str(exc))
    if isinstance(exc, InvalidTransition):
        return HTTPException(status_code=409, detail=str(exc))
    if isinstance(exc, ValidationError):
        return HTTPException(status_code=400, detail=str(exc))
    if isinstance(exc, MemoryError):
        return HTTPException(status_code=400, detail=str(exc))
    return HTTPException(status_code=500, detail=str(exc))


def to_mcp(exc: Exception) -> dict[str, Any]:
    """Return structured MCP error body."""
    code = "INTERNAL"
    if isinstance(exc, MemoryNotFound):
        code = "NOT_FOUND"
    elif isinstance(exc, ScopeViolation):
        code = "SCOPE_VIOLATION"
    elif isinstance(exc, SecretContent):
        code = "SECRET_REFUSED"
    elif isinstance(exc, InvalidTransition):
        code = "INVALID_TRANSITION"
    elif isinstance(exc, ValidationError):
        code = "VALIDATION"
    elif isinstance(exc, MemoryError):
        code = "DOMAIN_ERROR"
    return {"error": {"code": code, "message": str(exc)}}
