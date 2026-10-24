import asyncio
import logging

from fastapi import APIRouter, Request
from sqlalchemy import text
from starlette.responses import JSONResponse

from core.errors import error_response
from core.logging import log_failure
from db.connection import Database

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/health/live")
async def live() -> dict[str, str]:
    return {"status": "alive"}


@router.get("/health/ready", response_model=None)
async def ready(request: Request) -> dict[str, str | bool] | JSONResponse:
    database: Database = request.app.state.database
    try:
        async with asyncio.timeout(request.app.state.settings.database_timeout_seconds):
            async with database.engine.connect() as connection:
                await connection.execute(text("SELECT 1"))
                revision = await connection.scalar(text("SELECT version_num FROM alembic_version"))
        if not revision or revision != request.app.state.expected_revision:
            logger.warning("schema_not_ready", extra={"event": "schema_not_ready"})
            return error_response("not_ready", 503, request.state.request_id)
    except Exception as exc:
        log_failure(logger, "database_not_ready", exc, request.state.request_id)
        return error_response("not_ready", 503, request.state.request_id)
    return {"status": "ready", "database": True, "migrations": True, "adapters_enabled": False}
