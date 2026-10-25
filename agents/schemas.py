"""Explicit private-input and safe-output contracts; no ORM serialization to the group."""

from datetime import UTC, datetime
from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)


class TimeWindow(StrictModel):
    start_at: datetime
    end_at: datetime

    @field_validator("start_at", "end_at")
    @classmethod
    def utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("A timezone-aware time is required")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def ordered(self) -> Self:
        if self.end_at <= self.start_at:
            raise ValueError("A positive time window is required")
        return self


class ItemInput(StrictModel):
    canonical_item: str = Field(min_length=1, max_length=80, pattern=r"^[a-z0-9][a-z0-9 -]*$")
    subtype: str | None = Field(default=None, max_length=80)
    available: bool = True
    same_day_only: bool = True
    known_contacts_only: bool = True
    max_duration_minutes: int = Field(gt=0, le=20160)


class ItemView(ItemInput):
    id: UUID


class ScheduleInput(TimeWindow):
    private_location: str = Field(min_length=1, max_length=200, repr=False)


class ScheduleView(ScheduleInput):
    id: UUID


class AvailabilityInput(TimeWindow):
    location_id: UUID
    travel_buffer_minutes: int = Field(default=15, ge=0, le=120)


class AvailabilityView(AvailabilityInput):
    id: UUID


class CheckIntent(TimeWindow):
    community_id: UUID
    target_owner_id: UUID
    location_id: UUID
    canonical_item: str = Field(min_length=1, max_length=80, pattern=r"^[a-z0-9][a-z0-9 -]*$")
    subtype: str | None = Field(default=None, max_length=80)
    return_at: datetime
    confirmed: Literal[True]

    @field_validator("return_at")
    @classmethod
    def return_utc(cls, value: datetime) -> datetime:
        return cls.utc(value)

    @model_validator(mode="after")
    def valid_return(self) -> Self:
        if self.return_at <= self.end_at:
            raise ValueError("Return must follow the proposed handoff window")
        return self


class CoordinationTicket(StrictModel):
    grant_id: UUID
    capability: SecretStr = Field(repr=False)


class GatewayRequest(StrictModel):
    # No student ID, SQL, free-form location, raw policy or schedule fields accepted.
    capability: SecretStr = Field(min_length=32, max_length=128, repr=False)


class AvailabilityResult(StrictModel):
    eligible: bool
    location: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9-]{0,63}$")
    window: TimeWindow | None = None
    reason: Literal["unavailable"] | None = None

    @model_validator(mode="after")
    def consistent(self) -> Self:
        if (self.location is None) != (self.window is None):
            raise ValueError("Location and window must be disclosed together")
        if not self.eligible and (self.location is not None or self.window is not None):
            raise ValueError("An ineligible result cannot disclose meeting details")
        if self.eligible and self.reason is not None:
            raise ValueError("Eligible results do not reveal policy reasons")
        return self
