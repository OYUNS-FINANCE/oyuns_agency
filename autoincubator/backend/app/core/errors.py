"""One error shape for every API failure: {"error": {"code", "message", "details"}}."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.logging import get_logger

log = get_logger(__name__)


class ErrorBody(BaseModel):
    code: str
    message: str
    details: Any | None = None


class ErrorResponse(BaseModel):
    error: ErrorBody


class AppError(Exception):
    status_code = status.HTTP_400_BAD_REQUEST
    code = "bad_request"

    def __init__(self, message: str, *, details: Any | None = None, code: str | None = None):
        super().__init__(message)
        self.message = message
        self.details = details
        if code is not None:
            self.code = code


class NotFoundError(AppError):
    status_code = status.HTTP_404_NOT_FOUND
    code = "not_found"


class ConflictError(AppError):
    """The request is valid but the current state forbids it, e.g. `run_not_paused`."""

    status_code = status.HTTP_409_CONFLICT
    code = "conflict"


class ServiceUnavailableError(AppError):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    code = "service_unavailable"


ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    404: {"model": ErrorResponse, "description": "Not found"},
    422: {"model": ErrorResponse, "description": "Validation error"},
}
CONFLICT_RESPONSES: dict[int | str, dict[str, Any]] = {
    **ERROR_RESPONSES,
    409: {"model": ErrorResponse, "description": "Conflicts with the run's current state"},
}


def _response(status_code: int, code: str, message: str, details: Any = None) -> JSONResponse:
    body = ErrorResponse(error=ErrorBody(code=code, message=message, details=details))
    return JSONResponse(status_code=status_code, content=jsonable_encoder(body))


async def _app_error(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, AppError)
    return _response(exc.status_code, exc.code, exc.message, exc.details)


async def _http_error(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, StarletteHTTPException)
    code = {404: "not_found", 405: "method_not_allowed"}.get(exc.status_code, "http_error")
    return _response(exc.status_code, code, str(exc.detail))


async def _validation_error(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    # ctx may hold the raw exception from a model validator; send its message.
    errors = jsonable_encoder(
        [{k: v for k, v in e.items() if k != "url"} for e in exc.errors()],
        custom_encoder={BaseException: str},
    )
    return _response(
        status.HTTP_422_UNPROCESSABLE_CONTENT, "validation_error", "Invalid request", errors
    )


async def _unhandled_error(request: Request, exc: Exception) -> JSONResponse:
    log.error("api.unhandled_error", path=request.url.path, exc_info=exc)
    return _response(
        status.HTTP_500_INTERNAL_SERVER_ERROR, "internal_error", "Internal server error"
    )


def install_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, _app_error)
    app.add_exception_handler(StarletteHTTPException, _http_error)
    app.add_exception_handler(RequestValidationError, _validation_error)
    app.add_exception_handler(Exception, _unhandled_error)
