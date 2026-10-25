from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from fastapi import FastAPI

from api.routes import router
from config import Settings
from core.errors import RequestSafetyMiddleware, register_error_handlers
from core.logging import configure_logging
from db.connection import Database


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved = settings if settings is not None else Settings()
    configure_logging(resolved.log_level)
    migration_config = Config()
    migration_config.set_main_option(
        "script_location", str(Path(__file__).parent / "db/migrations")
    )
    expected_revision = ScriptDirectory.from_config(migration_config).get_current_head()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.database = Database(resolved)
        try:
            yield
        finally:
            await app.state.database.close()

    app = FastAPI(title="LoanShark", version="0.2.0", lifespan=lifespan)
    app.state.settings = resolved
    app.state.expected_revision = expected_revision
    app.add_middleware(RequestSafetyMiddleware)
    register_error_handlers(app)
    app.include_router(router)
    return app
