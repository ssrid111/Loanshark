import logging
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from core.logging import log_failure

logger = logging.getLogger(__name__)


class AppError(Exception):
    def __init__(self, code: str, status_code: int = 400) -> None:
        super().__init__(code)
        self.code = code
        self.status_code = status_code


def error_response(code: str, status_code: int, request_id: str) -> JSONResponse:
    return JSONResponse({"error": {"code": code, "request_id": request_id}}, status_code)


class RequestSafetyMiddleware:
    """Single error boundary and server-generated correlation IDs; no request-body logging."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request_id = str(uuid4())
        scope.setdefault("state", {})["request_id"] = request_id
        started = False
        status_code = 500

        async def safe_send(message: Message) -> None:
            nonlocal started, status_code
            if message["type"] == "http.response.start":
                started = True
                status_code = message["status"]
                message.setdefault("headers", []).append((b"x-request-id", request_id.encode()))
            await send(message)

        try:
            await self.app(scope, receive, safe_send)
        except Exception as exc:
            log_failure(logger, "request_failed", exc, request_id)
            if started:
                raise RuntimeError("Response delivery failed; see sanitized error log") from None
            await error_response("internal_error", 500, request_id)(scope, receive, safe_send)
        finally:
            logger.info(
                "request_finished",
                extra={
                    "event": "request_finished",
                    "request_id": request_id,
                    "method": scope["method"],
                    "status_code": status_code,
                },
            )


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def application_error(request: Request, exc: AppError) -> JSONResponse:
        logger.warning("application_error", extra={"event": "application_error"})
        return error_response(exc.code, exc.status_code, request.state.request_id)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        # Pydantic's input and context may contain student data, so return no raw errors.
        logger.warning("validation_failed", extra={"event": "validation_failed"})
        return error_response("invalid_request", 422, request.state.request_id)

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException) -> JSONResponse:
        return error_response(f"http_{exc.status_code}", exc.status_code, request.state.request_id)
