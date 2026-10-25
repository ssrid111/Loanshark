"""Coordination boundary: separate DB role, safe projection, no private table reads."""

import logging
from uuid import uuid4

from sqlalchemy import text

from agents.schemas import AvailabilityResult, GatewayRequest, TimeWindow
from core.clock import Clock, SystemClock
from core.errors import AppError
from core.logging import log_failure
from db.connection import Database

logger = logging.getLogger(__name__)


class PrivacyGateway:
    def __init__(self, gateway_database: Database, clock: Clock | None = None) -> None:
        self._database = gateway_database
        self._clock = clock or SystemClock()

    async def check(self, request: GatewayRequest) -> AvailabilityResult:
        correlation = uuid4()
        try:
            async with self._database.transaction() as session:
                if await session.scalar(text("SELECT current_user")) != "loanshark_gateway":
                    raise AppError("not_authorized", 403)
                # Typed projection only. This role has no private table SELECT privileges.
                row = (
                    (
                        await session.execute(
                            text(
                                "SELECT * FROM private.check_availability("
                                ":capability, :evaluated_at, :correlation)"
                            ),
                            {
                                "capability": request.capability.get_secret_value(),
                                "evaluated_at": self._clock.now(),
                                "correlation": correlation,
                            },
                        )
                    )
                    .mappings()
                    .one()
                )
                result = AvailabilityResult(
                    eligible=row["eligible"],
                    location=row["location"],
                    window=(
                        TimeWindow(start_at=row["window_start"], end_at=row["window_end"])
                        if row["window_start"] is not None
                        else None
                    ),
                    reason=None if row["eligible"] else "unavailable",
                )
            return result
        except Exception as exc:
            # DB, schema and clock failures deny coordination without exposing exception text.
            log_failure(logger, "gateway_failed_closed", exc, str(correlation))
            # Do not return eligibility if the audit transaction could not commit.
            return AvailabilityResult(eligible=False, reason="unavailable")
