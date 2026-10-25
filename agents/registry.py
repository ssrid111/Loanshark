import logging
from uuid import UUID, uuid4

from pydantic import SecretStr
from sqlalchemy.exc import SQLAlchemyError

from agents.personal import PersonalAgent
from core.clock import Clock, SystemClock
from core.errors import AppError
from core.identity import AuthenticatedStudent, StudentSessions
from core.logging import log_failure


class PersonalAgentRegistry:
    """Stateless logical agents keyed by owner ID, never shared conversation/state objects."""

    def __init__(self, sessions: StudentSessions, clock: Clock | None = None) -> None:
        self._sessions = sessions
        self._clock = clock or SystemClock()

    async def authenticate(self, token: SecretStr) -> AuthenticatedStudent:
        return await self._sessions.authenticate(token)

    async def resolve(self, actor: AuthenticatedStudent, student_id: UUID) -> PersonalAgent:
        # Reject a forged Python context as well as a valid actor naming another student.
        try:
            async with self._sessions.open(actor):
                pass
        except AppError:
            await self._sessions.record_denial(actor.token)
            raise
        except SQLAlchemyError as exc:
            log_failure(
                logging.getLogger(__name__), "identity_store_unavailable", exc, str(uuid4())
            )
            raise AppError("private_operation_unavailable", 503) from None
        if actor.student_id != student_id:
            await self._sessions.record_denial(actor.token)
            raise AppError("not_authorized", 403)
        return PersonalAgent(actor, self._sessions, self._clock)
