import asyncio
import os
import sys

import pytest
from pydantic import SecretStr
from sqlalchemy import text

from config import Settings
from db.connection import Database
from main import create_app
from tests.conftest import client_for, test_url

pytestmark = pytest.mark.integration


async def migrate(*arguments: str) -> None:
    environment = {**os.environ, "MIGRATION_DATABASE_URL": test_url()}
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "alembic",
        *arguments,
        env=environment,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    output, errors = await process.communicate()
    assert process.returncode == 0, (output + errors).decode()


async def test_real_migration_roundtrip_and_readiness() -> None:
    settings = Settings(
        _env_file=None, database_url=SecretStr(test_url("TEST_RUNTIME_DATABASE_URL"))
    )
    # This explicit *_test database contains only synthetic, transactional fixtures.
    await migrate("downgrade", "base")
    try:
        async with client_for(create_app(settings)) as client:
            response = await client.get("/health/ready")
            assert response.status_code == 503
    finally:
        await migrate("upgrade", "head")
    await migrate("check")
    async with client_for(create_app(settings)) as client:
        response = await client.get("/health/ready")
        assert response.status_code == 200


async def test_stale_revision_is_not_ready() -> None:
    database = Database(Settings(_env_file=None, database_url=SecretStr(test_url())))
    try:
        async with database.transaction() as session:
            await session.execute(text("UPDATE alembic_version SET version_num='stale_revision'"))
        try:
            settings = Settings(
                _env_file=None, database_url=SecretStr(test_url("TEST_RUNTIME_DATABASE_URL"))
            )
            async with client_for(create_app(settings)) as client:
                response = await client.get("/health/ready")
                assert response.status_code == 503
        finally:
            async with database.transaction() as session:
                await session.execute(
                    text("UPDATE alembic_version SET version_num='0001_foundation'")
                )
    finally:
        await database.close()
