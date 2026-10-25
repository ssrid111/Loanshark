"""Owner-scoped test interface. Identity is revalidated on every operation."""

import logging
import secrets
from collections.abc import Awaitable, Callable
from datetime import timedelta
from typing import TypeVar
from uuid import UUID, uuid4

from sqlalchemy.exc import DBAPIError, SQLAlchemyError

from agents.schemas import (
    AvailabilityInput,
    AvailabilityView,
    CheckIntent,
    CoordinationTicket,
    ItemInput,
    ItemView,
    ScheduleInput,
    ScheduleView,
    TimeWindow,
)
from core.clock import Clock, SystemClock
from core.errors import AppError
from core.identity import AuthenticatedStudent, StudentSessions
from core.logging import log_failure
from db.repositories.private import PrivateRepository

T = TypeVar("T")
logger = logging.getLogger(__name__)


class PersonalAgent:
    def __init__(
        self, actor: AuthenticatedStudent, sessions: StudentSessions, clock: Clock | None = None
    ) -> None:
        self._actor, self._sessions = actor, sessions
        self._clock = clock or SystemClock()

    @property
    def student_id(self) -> UUID:
        return self._actor.student_id

    async def _run(self, operation: Callable[[PrivateRepository], Awaitable[T]]) -> T:
        try:
            async with self._sessions.open(self._actor) as session:
                return await operation(PrivateRepository(session, self.student_id))
        except AppError:
            await self._sessions.record_denial(self._actor.token)
            raise
        except SQLAlchemyError as exc:
            log_failure(logger, "private_operation_failed", exc, str(uuid4()))
            await self._sessions.record_denial(self._actor.token)
            if isinstance(exc, DBAPIError) and getattr(exc.orig, "sqlstate", None) == "42501":
                raise AppError("not_authorized", 403) from None
            raise AppError("private_operation_unavailable", 503) from None

    async def items(self) -> list[ItemView]:
        return await self._run(lambda repository: repository.items())

    async def save_item(self, data: ItemInput, item_id: UUID | None = None) -> ItemView:
        return await self._run(lambda repository: repository.save_item(data, item_id))

    async def schedule(self) -> list[ScheduleView]:
        return await self._run(lambda repository: repository.schedule())

    async def save_schedule(self, data: ScheduleInput) -> ScheduleView:
        return await self._run(lambda repository: repository.save_schedule(data))

    async def remove_schedule(self, identifier: UUID) -> None:
        await self._run(lambda repository: repository.remove_schedule(identifier))

    async def availability(self) -> list[AvailabilityView]:
        return await self._run(lambda repository: repository.availability())

    async def save_availability(self, data: AvailabilityInput) -> AvailabilityView:
        return await self._run(lambda repository: repository.save_availability(data))

    async def remove_availability(self, identifier: UUID) -> None:
        await self._run(lambda repository: repository.remove_availability(identifier))

    async def pause_lending(self, paused: bool) -> None:
        await self._run(lambda repository: repository.pause(paused))

    async def confirm_schedule_coverage(self, window: TimeWindow) -> None:
        await self._run(lambda repository: repository.coverage(window, self._clock.now()))

    async def trust(self, contact_id: UUID, community_id: UUID) -> None:
        await self._run(lambda repository: repository.trust(contact_id, community_id))

    async def authorize_check(self, intent: CheckIntent) -> CoordinationTicket:
        if intent.target_owner_id == self.student_id or intent.start_at <= self._clock.now():
            raise AppError("invalid_request")
        ticket = CoordinationTicket(grant_id=uuid4(), capability=secrets.token_urlsafe(32))
        expiry = min(intent.end_at, self._clock.now() + timedelta(minutes=15))
        await self._run(lambda repository: repository.authorize_check(intent, ticket, expiry))
        return ticket

    async def approve_disclosure(self, grant_id: UUID) -> None:
        await self._run(lambda repository: repository.approve_disclosure(grant_id))

    async def revoke_disclosure(self, grant_id: UUID) -> None:
        await self._run(lambda repository: repository.revoke_disclosure(grant_id))

    async def untrust(self, contact_id: UUID, community_id: UUID) -> None:
        await self._run(lambda repository: repository.untrust(contact_id, community_id))

    async def community_opt_in(self, community_id: UUID, opted_in: bool) -> None:
        await self._run(lambda repository: repository.community_opt_in(community_id, opted_in))
