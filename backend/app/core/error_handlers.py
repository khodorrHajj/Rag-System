import logging

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.core.exceptions import AppError

logger = logging.getLogger(__name__)

def register_exception_handlers(application: FastAPI) -> None:
    @application.exception_handler(AppError)
    async def handle_app_error(_: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail},
            headers=exc.headers,
        )

    @application.exception_handler(HTTPException)
    async def handle_http_exception(_: Request, exc: HTTPException) -> JSONResponse:
        detail = exc.detail if isinstance(exc.detail, str) else "Request failed."

        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": detail},
            headers=exc.headers or {},
        )

    @application.exception_handler(RequestValidationError)
    async def handle_validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        logger.info("Request validation failed: %s", exc.errors())

        return JSONResponse(
            status_code=422,
            content={"detail": "Request validation failed."},
        )

    @application.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        logger.exception(
            "Unhandled server error during %s %s",
            request.method,
            request.url.path,
        )

        settings = get_settings()
        detail = "Internal server error."
        if not settings.is_production:
            detail = "Internal server error. Check server logs for details."

        return JSONResponse(
            status_code=500,
            content={"detail": detail},
        )

