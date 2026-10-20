import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)


class ErrorDetail(BaseModel):
    loc: list[str | int] = []
    msg: str
    type: str = ""
    # Extra facts, e.g. the referencing Data Set. Values are strings (ids, names; the 413's
    # counts are stringified too) so the envelope has one value type and a flat OpenAPI schema.
    ctx: dict[str, str] | None = None


class ErrorBody(BaseModel):
    code: str
    message: str
    details: list[ErrorDetail] = []


class ErrorResponse(BaseModel):
    error: ErrorBody


class AppError(Exception):
    status_code: int = 500
    code: str = "INTERNAL_ERROR"

    def __init__(self, message: str, details: list[ErrorDetail | dict] | None = None):
        super().__init__(message)
        self.message = message
        # Validate here, at the raise site: a malformed detail fails loudly in the code that built
        # it instead of turning the handler's 409/422 into a 500.
        self.details: list[ErrorDetail] = [ErrorDetail.model_validate(d) for d in details or []]


class NotFoundError(AppError):
    status_code = 404
    code = "NOT_FOUND"


class ConflictError(AppError):
    status_code = 409
    code = "CONFLICT"


class UnprocessableError(AppError):
    status_code = 422
    code = "VALIDATION_ERROR"


class PayloadTooLargeError(AppError):
    status_code = 413
    code = "PAYLOAD_TOO_LARGE"


# App-wide `responses=`: any route can fail validation or crash. /docs then shows our envelope
# instead of FastAPI's HTTPValidationError.
DEFAULT_ERROR_RESPONSES = {
    422: {"model": ErrorResponse},
    500: {"model": ErrorResponse},
}
# Per-route, so /docs advertises 404/409/413 only where they can happen.
NOT_FOUND_RESPONSE = {404: {"model": ErrorResponse}}
CONFLICT_RESPONSE = {409: {"model": ErrorResponse}}
PAYLOAD_TOO_LARGE_RESPONSE = {413: {"model": ErrorResponse}}


def _envelope(
    status_code: int,
    code: str,
    message: str,
    details: list[ErrorDetail] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    body = ErrorResponse(error=ErrorBody(code=code, message=message, details=details or []))
    # exclude_none: `ctx` appears only on the details that set it.
    return JSONResponse(
        status_code=status_code, content=body.model_dump(exclude_none=True), headers=headers
    )


async def _app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    return _envelope(exc.status_code, exc.code, exc.message, exc.details)


async def _validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    # Pydantic's ctx is not forwarded: it can hold live exception objects that are not JSON.
    details = [
        ErrorDetail(loc=list(err["loc"]), msg=err["msg"], type=err["type"]) for err in exc.errors()
    ]
    return _envelope(422, "VALIDATION_ERROR", "Request validation failed", details)


async def _http_error_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    code = "NOT_FOUND" if exc.status_code == 404 else "HTTP_ERROR"
    # headers carry e.g. the Allow header of a 405.
    return _envelope(exc.status_code, code, str(exc.detail), headers=exc.headers)


async def _unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    return _envelope(500, "INTERNAL_ERROR", "Internal server error")


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, _app_error_handler)
    app.add_exception_handler(RequestValidationError, _validation_error_handler)
    app.add_exception_handler(StarletteHTTPException, _http_error_handler)
    app.add_exception_handler(Exception, _unhandled_error_handler)
