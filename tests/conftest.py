import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest
from dotenv import load_dotenv
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession

from config import Settings
from db.connection import Database

pytest_plugins = ["tests.privacy_fixtures"]

load_dotenv(override=False)


@pytest.fixture
def settings() -> Settings:
    return Settings(
        _env_file=None,
        database_url=SecretStr("postgresql+asyncpg://test:test@127.0.0.1:1/loanshark_test"),
        database_timeout_seconds=0.2,
    )


def test_url(variable: str = "TEST_DATABASE_URL") -> str:
    value = os.environ.get(variable)
    if not value:
        pytest.skip(f"{variable} not set; PostgreSQL integration test not run")
    parsed = make_url(value)
    if parsed.drivername != "postgresql+asyncpg" or not (parsed.database or "").endswith("_test"):
        pytest.fail("Refusing integration tests on a database not explicitly named *_test")
    return value


test_url.__test__ = False  # type: ignore[attr-defined]


@pytest.fixture
async def database() -> AsyncIterator[Database]:
    database = Database(Settings(_env_file=None, database_url=SecretStr(test_url())))
    try:
        async with database.engine.connect() as connection:
            revision = await connection.scalar(text("SELECT version_num FROM alembic_version"))
            assert revision == "0002_privacy", "Migrate the test database first"
        yield database
    finally:
        await database.close()


@pytest.fixture
async def session(database: Database) -> AsyncIterator[AsyncSession]:
    async with database.engine.connect() as connection:
        transaction = await connection.begin()
        async with AsyncSession(bind=connection, expire_on_commit=False) as session:
            try:
                yield session
            finally:
                await session.close()
                if transaction.is_active:
                    await transaction.rollback()


@asynccontextmanager
async def client_for(app: FastAPI) -> AsyncIterator[AsyncClient]:
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            yield client
