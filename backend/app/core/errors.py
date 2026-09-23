import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from backend.app.schemas.common import ErrorDetail, ErrorResponse

logger = logging.getLogger(__name__)


class AppError(Exception):
    def __init__(self, status_code: int, code: str, message: str, *, retryable: bool = False):
        self.status_code = status_code
        self.error = ErrorDetail(code=code, message=message, retryable=retryable)
        super().__init__(message)


def error_response(status: int, error: ErrorDetail) -> JSONResponse:
    return JSONResponse(status_code=status, content=ErrorResponse(error=error).model_dump())


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def application_error_handler(request: Request, exc: AppError) -> JSONResponse:
        return error_response(exc.status_code, exc.error)

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(request: Request, exc: RequestValidationError):
        fields = sorted({".".join(str(p) for p in error["loc"]) for error in exc.errors()})
        return error_response(
            422,
            ErrorDetail(code="VALIDATION_ERROR", message="Проверьте поля: " + ", ".join(fields)),
        )

    @app.exception_handler(HTTPException)
    async def http_error_handler(request: Request, exc: HTTPException):
        response = error_response(
            exc.status_code,
            ErrorDetail(code=f"HTTP_{exc.status_code}", message=str(exc.detail)),
        )
        if exc.headers:
            response.headers.update(exc.headers)
        return response

    @app.exception_handler(Exception)
    async def unexpected_error_handler(request: Request, exc: Exception):
        logger.error("Unhandled API error", exc_info=exc)
        return error_response(
            500, ErrorDetail(code="INTERNAL_ERROR", message="Внутренняя ошибка сервера.")
        )
