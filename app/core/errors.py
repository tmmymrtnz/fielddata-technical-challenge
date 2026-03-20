from __future__ import annotations

import logging
from http import HTTPStatus
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from starlette.exceptions import HTTPException as StarletteHTTPException


logger = logging.getLogger("api.errors")


def _request_id(request: Request) -> str:
    request_id = getattr(request.state, "request_id", None)
    if request_id is None:
        request_id = str(uuid4())
        request.state.request_id = request_id
    return request_id


def _http_error_code(status_code: int) -> str:
    try:
        return HTTPStatus(status_code).name.lower()
    except ValueError:
        return "http_error"


def _error_response(
    request: Request,
    status_code: int,
    code: str,
    message: str,
    *,
    details=None,
) -> JSONResponse:
    request_id = _request_id(request)
    payload: dict[str, object] = {
        "error": {
            "code": code,
            "message": message,
        },
        "request_id": request_id,
    }
    if details is not None:
        payload["error"]["details"] = details

    return JSONResponse(status_code=status_code, content=payload, headers={"X-Request-ID": request_id})


async def request_context_middleware(request: Request, call_next):
    request.state.request_id = request.headers.get("X-Request-ID") or str(uuid4())
    response = await call_next(request)
    response.headers["X-Request-ID"] = request.state.request_id
    return response


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        return _error_response(
            request,
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "validation_error",
            "La request no pasó la validación",
            details=[
                {
                    "loc": list(error["loc"]),
                    "message": error["msg"],
                    "type": error["type"],
                }
                for error in exc.errors()
            ],
        )

    async def _http_exception_handler(request: Request, exc: HTTPException | StarletteHTTPException) -> JSONResponse:
        detail = exc.detail
        if isinstance(detail, str):
            message = detail
            details = None
        else:
            message = HTTPStatus(exc.status_code).phrase
            details = detail

        return _error_response(
            request,
            exc.status_code,
            _http_error_code(exc.status_code),
            message,
            details=details,
        )

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
        return await _http_exception_handler(request, exc)

    @app.exception_handler(StarletteHTTPException)
    async def starlette_http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        return await _http_exception_handler(request, exc)

    @app.exception_handler(IntegrityError)
    async def integrity_error_handler(request: Request, exc: IntegrityError) -> JSONResponse:
        logger.exception("Database integrity error request_id=%s path=%s", _request_id(request), request.url.path, exc_info=exc)
        return _error_response(
            request,
            status.HTTP_409_CONFLICT,
            "integrity_error",
            "La operación viola una restricción de integridad de datos",
        )

    @app.exception_handler(SQLAlchemyError)
    async def sqlalchemy_error_handler(request: Request, exc: SQLAlchemyError) -> JSONResponse:
        logger.exception("Database error request_id=%s path=%s", _request_id(request), request.url.path, exc_info=exc)
        return _error_response(
            request,
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "database_error",
            "Ocurrió un error al acceder a la base de datos",
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled error request_id=%s path=%s", _request_id(request), request.url.path, exc_info=exc)
        return _error_response(
            request,
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "internal_error",
            "Ocurrió un error interno",
        )
