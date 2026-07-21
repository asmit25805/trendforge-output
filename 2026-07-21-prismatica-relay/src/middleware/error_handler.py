import logging
from typing import Any, Dict, List, Mapping, Optional, Sequence, Union

import httpx
from pydantic import BaseModel, ValidationError, validator
from sanic import Sanic, response
from sanic.exceptions import InvalidUsage, SanicException, ServerError

logger = logging.getLogger(__name__)


class ErrorDetailModel(BaseModel):
    """Structure for individual error details returned to the client."""

    code: str
    message: str
    retryable: bool = False


class ValidationIssueModel(BaseModel):
    """Structure for a single validation issue."""

    loc: str
    msg: str
    type: str


class ErrorResponseModel(BaseModel):
    """Top‑level error response payload."""

    code: str
    message: Optional[str] = None
    issues: Optional[List[ValidationIssueModel]] = None
    error: Optional[ErrorDetailModel] = None


def _format_validation_issues(err: ValidationError) -> List[ValidationIssueModel]:
    """
    Convert a pydantic ``ValidationError`` into a list of ``ValidationIssueModel``.
    """
    issues: List[ValidationIssueModel] = []
    for e in err.errors():
        loc = ".".join(map(str, e.get("loc", [])))
        issues.append(
            ValidationIssueModel(
                loc=loc,
                msg=e.get("msg", ""),
                type=e.get("type", ""),
            )
        )
    return issues


def _build_error_response(
    *,
    code: str,
    message: Optional[str] = None,
    issues: Optional[Sequence[ValidationIssueModel]] = None,
    error_detail: Optional[ErrorDetailModel] = None,
    status: int,
) -> response.HTTPResponse:
    """
    Assemble a JSON error response using ``ErrorResponseModel`` and return a
    Sanic ``HTTPResponse`` with the appropriate status code.
    """
    payload = ErrorResponseModel(
        code=code,
        message=message,
        issues=list(issues) if issues is not None else None,
        error=error_detail,
    )
    return response.json(payload.dict(exclude_none=True), status=status)


async def error_middleware(request: Any, exc: Exception) -> response.HTTPResponse:
    """
    Global error handler for the Sanic application.

    It maps known exception types to a structured JSON payload while ensuring
    that unexpected errors are logged and reported as internal server errors.
    """
    # ----------------------------------------------------------------------
    # 1️⃣ Validation errors – client supplied payload does not conform to schema
    # ----------------------------------------------------------------------
    if isinstance(exc, ValidationError):
        logger.warning("Validation error: %s", exc)
        issues = _format_validation_issues(exc)
        return _build_error_response(
            code="invalid_payload",
            message="Request payload validation failed",
            issues=issues,
            status=400,
        )

    # ----------------------------------------------------------------------
    # 2️⃣ Sanic client‑side exceptions (e.g. InvalidUsage, BadRequest, etc.)
    # ----------------------------------------------------------------------
    if isinstance(exc, InvalidUsage):
        logger.info("Invalid usage: %s", exc)
        return _build_error_response(
            code="invalid_request",
            message=str(exc),
            status=exc.status_code if hasattr(exc, "status_code") else 400,
        )

    if isinstance(exc, SanicException) and getattr(exc, "status_code", 0) < 500:
        logger.info("Sanic client error %s: %s", getattr(exc, "status_code", 0), exc)
        return _build_error_response(
            code="client_error",
            message=str(exc),
            status=exc.status_code,
        )

    # ----------------------------------------------------------------------
    # 3️⃣ Upstream server errors – we surface a generic internal error
    # ----------------------------------------------------------------------
    if isinstance(exc, ServerError):
        logger.error("Server error encountered: %s", exc, exc_info=True)
        return _build_error_response(
            code="internal_error",
            message="An unexpected server error occurred",
            status=500,
        )

    # ----------------------------------------------------------------------
    # 4️⃣ HTTPX transport‑level errors – treat as upstream failures
    # ----------------------------------------------------------------------
    if isinstance(exc, httpx.HTTPError):
        logger.warning("HTTP transport error: %s", exc)
        detail = ErrorDetailModel(
            code="upstream_unavailable",
            message=str(exc),
            retryable=True,
        )
        return _build_error_response(
            code="upstream_error",
            error_detail=detail,
            status=502,
        )

    # ----------------------------------------------------------------------
    # 5️⃣ Fallback – any other unexpected exception
    # ----------------------------------------------------------------------
    logger.exception("Unhandled exception in request processing")
    return _build_error_response(
        code="internal_error",
        message="An unexpected error occurred while processing the request",
        status=500,
    )


def register_error_handler(app: Sanic) -> None:
    """
    Register the global error middleware with a Sanic application instance.

    The function attaches ``error_middleware`` as the handler for the base
    ``Exception`` class, ensuring that all uncaught exceptions flow through the
    standardized error handling pipeline.
    """
    if not isinstance(app, Sanic):
        raise TypeError("app must be an instance of sanic.Sanic")

    # Sanic registers exception handlers via the ``exception`` decorator.
    # By binding ``Exception`` we guarantee coverage for any subclass not
    # explicitly handled elsewhere.
    app.exception(Exception)(error_middleware)

    logger.debug("Global error handler registered for %s", app.name)


__all__: List[str] = [
    "ErrorDetailModel",
    "ValidationIssueModel",
    "ErrorResponseModel",
    "error_middleware",
    "register_error_handler",
]