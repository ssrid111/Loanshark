"""Opaque bearer identities for the private test interface; no caller-selected actor IDs."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from uuid import UUID, uuid4

from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import AppError
from core.logging import log_failure
from db.connection import Database

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AuthenticatedStudent:
    student_id: UUID
    token: SecretStr = field(repr=False)


async def require_runtime_role(session: AsyncSession) -> None:
    if await session.scalar(text("SELECT current_user")) != "loanshark_runtime":
        raise AppError("not_authorized", 403)


class StudentSessions:
    def __init__(self, database: Database) -> None:
        self._database = database

    @asynccontextmanager
    async def open(self, actor: AuthenticatedStudent) -> AsyncIterator[AsyncSession]:
        async with self._database.transaction() as session:
            await require_runtime_role(session)
            await session.execute(
                text("SELECT set_config('loanshark.token', :token, true)"),
                {"token": actor.token.get_secret_value()},
            )
            actual = await session.scalar(text("SELECT private.current_student()"))
            if actual is None or actual != actor.student_id:
                raise AppError("not_authorized", 403)
            yield session

    async def authenticate(self, token: SecretStr) -> AuthenticatedStudent:
        try:
            async with self._database.transaction() as session:
                await require_runtime_role(session)
                await session.execute(
                    text("SELECT set_config('loanshark.token', :token, true)"),
                    {"token": token.get_secret_value()},
                )
                identifier = await session.scalar(
                    text("SELECT private.authenticate(:correlation)"), {"correlation": uuid4()}
                )
            if not isinstance(identifier, UUID):
                raise AppError("not_authorized", 403)
            return AuthenticatedStudent(identifier, token)
        except SQLAlchemyError as exc:
            log_failure(logger, "identity_store_unavailable", exc, str(uuid4()))
            raise AppError("private_operation_unavailable", 503) from None

    async def record_denial(self, token: SecretStr) -> None:
        try:
            async with self._database.transaction() as session:
                await require_runtime_role(session)
                await session.execute(
                    text("SELECT set_config('loanshark.token', :token, true)"),
                    {"token": token.get_secret_value()},
                )
                await session.execute(
                    text("SELECT private.record_owner_denial(:correlation)"),
                    {"correlation": uuid4()},
                )
        except SQLAlchemyError as exc:
            log_failure(logger, "identity_store_unavailable", exc, str(uuid4()))
            raise AppError("private_operation_unavailable", 503) from None
