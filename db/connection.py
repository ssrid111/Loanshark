from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from config import Settings


class Database:
    def __init__(self, settings: Settings) -> None:
        self.engine: AsyncEngine = create_async_engine(
            settings.database_url.get_secret_value(),
            pool_pre_ping=True,
            hide_parameters=True,
            connect_args={
                "timeout": settings.database_timeout_seconds,
                "command_timeout": settings.database_timeout_seconds,
                "server_settings": {"timezone": "UTC"},
            },
        )
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[AsyncSession]:
        # Exceptions propagate; SQLAlchemy rolls back on exit. Never share across tasks.
        async with self.sessions.begin() as session:
            yield session

    async def close(self) -> None:
        await self.engine.dispose()
