"""Persistence only. No public serialization, authorization or lending decisions here."""

from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    LargeBinary,
    MetaData,
    String,
    UniqueConstraint,
    false,
    func,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import TypeDecorator


class UTCDateTime(TypeDecorator[datetime]):
    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: object) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Naive timestamps are not allowed")
        return value.astimezone(UTC)

    def process_result_value(self, value: datetime | None, dialect: object) -> datetime | None:
        return value.astimezone(UTC) if value is not None else None


class Base(DeclarativeBase):
    metadata = MetaData(
        naming_convention={
            "ix": "ix_%(table_name)s_%(column_0_name)s",
            "uq": "uq_%(table_name)s_%(column_0_name)s",
            "ck": "ck_%(table_name)s_%(constraint_name)s",
            "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
            "pk": "pk_%(table_name)s",
        }
    )


class Identity:
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)


class CreatedAt:
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), server_default=func.now())


class Student(Identity, Base):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("platform", "platform_user_id"),
        CheckConstraint("length(platform_user_id) > 0", name="nonempty_platform_id"),
        CheckConstraint("consent_version >= 0", name="valid_consent_version"),
    )
    platform: Mapped[str] = mapped_column(String(32), default="discord")
    platform_user_id: Mapped[str] = mapped_column(String(128))
    timezone: Mapped[str] = mapped_column(String(64), default="UTC")
    paused_lending: Mapped[bool] = mapped_column(Boolean, server_default=false())
    consent_version: Mapped[int] = mapped_column(Integer, server_default="0")
    joined_at: Mapped[datetime] = mapped_column(UTCDateTime(), server_default=func.now())
    inactive_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    schedule_known_from: Mapped[datetime | None] = mapped_column(UTCDateTime())
    schedule_known_until: Mapped[datetime | None] = mapped_column(UTCDateTime())
    schedule_verified_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class Community(Identity, Base):
    __tablename__ = "communities"
    __table_args__ = (UniqueConstraint("platform", "guild_id", "channel_id"),)
    platform: Mapped[str] = mapped_column(String(32), default="discord")
    guild_id: Mapped[str] = mapped_column(String(128))
    channel_id: Mapped[str] = mapped_column(String(128))


class LendingPolicy(Identity, Base):
    __tablename__ = "lending_policies"
    __table_args__ = (
        UniqueConstraint("id", "owner_id"),
        CheckConstraint("max_duration_minutes > 0", name="positive_duration"),
    )
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    same_day_only: Mapped[bool] = mapped_column(Boolean, server_default=false())
    known_contacts_only: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    max_duration_minutes: Mapped[int] = mapped_column(Integer)


class InventoryItem(Identity, CreatedAt, Base):
    __tablename__ = "inventory"
    __table_args__ = (
        UniqueConstraint("id", "owner_id"),
        ForeignKeyConstraint(
            ["policy_id", "owner_id"], ["lending_policies.id", "lending_policies.owner_id"]
        ),
        CheckConstraint("version > 0", name="positive_version"),
        CheckConstraint("length(canonical_item) > 0", name="nonempty_item"),
    )
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    canonical_item: Mapped[str] = mapped_column(String(100))
    subtype: Mapped[str | None] = mapped_column(String(100))
    active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    policy_id: Mapped[UUID] = mapped_column(index=True)
    version: Mapped[int] = mapped_column(Integer, server_default="1")


class BorrowRequest(Identity, CreatedAt, Base):
    __tablename__ = "requests"
    __table_args__ = (
        CheckConstraint("proposed_return_at > need_by", name="return_after_need"),
        CheckConstraint("scope_version > 0", name="positive_scope_version"),
        CheckConstraint(
            "status IN ('DRAFT','AWAITING_SCOPE_CONFIRMATION','OPEN','RESERVED',"
            "'FULFILLED','CANCELLED','EXPIRED','UNMATCHED')",
            name="valid_status",
        ),
        Index("ix_requests_status_need_by", "status", "need_by"),
    )
    borrower_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    community_id: Mapped[UUID] = mapped_column(ForeignKey("communities.id"), index=True)
    canonical_item: Mapped[str] = mapped_column(String(100))
    subtype: Mapped[str | None] = mapped_column(String(100))
    need_by: Mapped[datetime] = mapped_column(UTCDateTime())
    proposed_return_at: Mapped[datetime] = mapped_column(UTCDateTime())
    # A draft may omit a place; it cannot be opened until a later service validates it.
    pickup_zone: Mapped[str | None] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(32), server_default="DRAFT")
    scope_version: Mapped[int] = mapped_column(Integer, server_default="1")
    scope_confirmation_id: Mapped[UUID | None] = mapped_column(ForeignKey("confirmations.id"))


class Confirmation(Identity, CreatedAt, Base):
    __tablename__ = "confirmations"
    __table_args__ = (
        CheckConstraint("resource_version > 0", name="positive_resource_version"),
        CheckConstraint("expires_at > created_at", name="valid_expiry"),
        CheckConstraint("decision IN ('APPROVED','DECLINED')", name="valid_decision"),
        CheckConstraint(
            "(consumed_at IS NULL AND decision IS NULL) OR "
            "(consumed_at IS NOT NULL AND decision IS NOT NULL)",
            name="decision_consumption",
        ),
        CheckConstraint(
            "consumed_at IS NULL OR (consumed_at >= created_at AND consumed_at <= expires_at)",
            name="consumed_within_window",
        ),
        Index("ix_confirmations_resource", "resource_kind", "resource_id"),
    )
    subject_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    action_kind: Mapped[str] = mapped_column(String(64))
    resource_kind: Mapped[str] = mapped_column(String(64))
    # Polymorphic reference: the future service validates type, existence and ownership.
    resource_id: Mapped[UUID]
    resource_version: Mapped[int] = mapped_column(Integer)
    payload_digest: Mapped[str] = mapped_column(String(64))
    token_digest: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime(), index=True)
    consumed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    decision: Mapped[str | None] = mapped_column(String(16))


class Offer(Identity, Base):
    """Referential foundation only; no offer service or state transitions yet."""

    __tablename__ = "offers"
    __table_args__ = (
        UniqueConstraint("id", "request_id", "item_id"),
        ForeignKeyConstraint(["item_id", "lender_id"], ["inventory.id", "inventory.owner_id"]),
        CheckConstraint("version > 0", name="positive_version"),
        CheckConstraint(
            "status IN ('PENDING_OWNER','OWNER_ACCEPTED','AWAITING_BORROWER','RESERVED',"
            "'DECLINED','EXPIRED','WITHDRAWN','RELEASED')",
            name="valid_status",
        ),
    )
    request_id: Mapped[UUID] = mapped_column(ForeignKey("requests.id"), index=True)
    lender_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    item_id: Mapped[UUID] = mapped_column(index=True)
    status: Mapped[str] = mapped_column(String(32), server_default="PENDING_OWNER")
    version: Mapped[int] = mapped_column(Integer, server_default="1")
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime())


class Reservation(Identity, Base):
    """Keeps Loan's required reservation foreign key real; business behavior is deferred."""

    __tablename__ = "reservations"
    __table_args__ = (
        UniqueConstraint("id", "item_id"),
        ForeignKeyConstraint(
            ["offer_id", "request_id", "item_id"],
            ["offers.id", "offers.request_id", "offers.item_id"],
        ),
        CheckConstraint("hold_expires_at > held_at", name="positive_hold"),
        CheckConstraint("released_at IS NULL OR released_at >= held_at", name="valid_release"),
        Index(
            "uq_active_reservation_item",
            "item_id",
            unique=True,
            postgresql_where=text("released_at IS NULL"),
        ),
        Index(
            "uq_active_reservation_request",
            "request_id",
            unique=True,
            postgresql_where=text("released_at IS NULL"),
        ),
    )
    item_id: Mapped[UUID] = mapped_column(ForeignKey("inventory.id"), index=True)
    request_id: Mapped[UUID] = mapped_column(ForeignKey("requests.id"), index=True)
    offer_id: Mapped[UUID] = mapped_column(unique=True)
    held_at: Mapped[datetime] = mapped_column(UTCDateTime(), server_default=func.now())
    hold_expires_at: Mapped[datetime] = mapped_column(UTCDateTime())
    released_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class Loan(Identity, Base):
    __tablename__ = "loans"
    __table_args__ = (
        ForeignKeyConstraint(
            ["reservation_id", "item_id"], ["reservations.id", "reservations.item_id"]
        ),
        ForeignKeyConstraint(["item_id", "lender_id"], ["inventory.id", "inventory.owner_id"]),
        CheckConstraint("borrower_id <> lender_id", name="distinct_participants"),
        CheckConstraint("due_at > start_at", name="positive_duration"),
        CheckConstraint("status IN ('ACTIVE','RETURN_REPORTED','CLOSED')", name="valid_status"),
        CheckConstraint(
            "(status = 'CLOSED' AND closed_at IS NOT NULL AND "
            "lender_return_confirmation_id IS NOT NULL) OR "
            "(status <> 'CLOSED' AND closed_at IS NULL)",
            name="closed_requires_receipt",
        ),
        CheckConstraint("closed_at IS NULL OR closed_at >= start_at", name="valid_close_time"),
        Index("ix_loans_status_due_at", "status", "due_at"),
    )
    reservation_id: Mapped[UUID] = mapped_column(unique=True)
    borrower_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    lender_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    item_id: Mapped[UUID] = mapped_column(index=True)
    start_at: Mapped[datetime] = mapped_column(UTCDateTime())
    due_at: Mapped[datetime] = mapped_column(UTCDateTime())
    closed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    status: Mapped[str] = mapped_column(String(32), server_default="ACTIVE")
    lender_return_confirmation_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("confirmations.id")
    )


class LostFoundReport(Identity, CreatedAt):
    """Unmapped shared fields; lost/found remain separate protected tables as approved."""

    reporter_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    community_id: Mapped[UUID] = mapped_column(ForeignKey("communities.id"), index=True)
    canonical_item: Mapped[str] = mapped_column(String(100))
    zone: Mapped[str] = mapped_column(String(100))
    seen_from: Mapped[datetime] = mapped_column(UTCDateTime())
    seen_until: Mapped[datetime] = mapped_column(UTCDateTime())
    status: Mapped[str] = mapped_column(String(16), server_default="OPEN")


class LostReport(LostFoundReport, Base):
    __tablename__ = "lost_reports"
    __table_args__ = (
        CheckConstraint("seen_until >= seen_from", name="valid_time_window"),
        CheckConstraint("status IN ('OPEN','RESOLVED','CANCELLED')", name="valid_status"),
        Index("ix_lost_reports_match", "canonical_item", "zone", "seen_from"),
    )
    encrypted_identifying_details: Mapped[bytes | None] = mapped_column(LargeBinary)


class FoundReport(LostFoundReport, Base):
    __tablename__ = "found_reports"
    __table_args__ = (
        CheckConstraint("seen_until >= seen_from", name="valid_time_window"),
        CheckConstraint("status IN ('OPEN','RESOLVED','CANCELLED')", name="valid_status"),
        Index("ix_found_reports_match", "canonical_item", "zone", "seen_from"),
    )
    public_description: Mapped[str] = mapped_column(String(500))
    encrypted_hidden_details: Mapped[bytes] = mapped_column(LargeBinary)
    verification_prompt: Mapped[str] = mapped_column(String(200))


class AuditEvent(Identity, CreatedAt, Base):
    __tablename__ = "audit_log"
    __table_args__ = (Index("ix_audit_log_resource", "resource_kind", "resource_id"),)
    event_type: Mapped[str] = mapped_column(String(64))
    actor_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"), index=True)
    resource_kind: Mapped[str] = mapped_column(String(64))
    resource_id: Mapped[UUID]
    confirmation_id: Mapped[UUID | None] = mapped_column(ForeignKey("confirmations.id"))
    correlation_id: Mapped[UUID] = mapped_column(index=True)
    before_state: Mapped[str | None] = mapped_column(String(32))
    after_state: Mapped[str | None] = mapped_column(String(32))


class ApiToken(Identity, CreatedAt, Base):
    __tablename__ = "api_tokens"
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    token_digest: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime())
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class Membership(Identity, Base):
    __tablename__ = "memberships"
    __table_args__ = (UniqueConstraint("community_id", "user_id"),)
    community_id: Mapped[UUID] = mapped_column(ForeignKey("communities.id"), index=True)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    verified: Mapped[bool] = mapped_column(Boolean, server_default=false())
    opted_in: Mapped[bool] = mapped_column(Boolean, server_default=false())


class TrustedContact(Identity, Base):
    __tablename__ = "trusted_contacts"
    __table_args__ = (
        UniqueConstraint("owner_id", "contact_id", "community_id"),
        CheckConstraint("owner_id <> contact_id", name="different_people"),
    )
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    contact_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    community_id: Mapped[UUID] = mapped_column(ForeignKey("communities.id"), index=True)


class HandoffLocation(Identity, Base):
    """Admin-curated public meeting zones, never a student's private address."""

    __tablename__ = "handoff_locations"
    __table_args__ = (
        UniqueConstraint("community_id", "code"),
        UniqueConstraint("id", "community_id"),
        CheckConstraint("code ~ '^[a-z][a-z0-9-]{0,63}$'", name="safe_location_code"),
    )
    community_id: Mapped[UUID] = mapped_column(ForeignKey("communities.id"), index=True)
    code: Mapped[str] = mapped_column(String(64))
    approved: Mapped[bool] = mapped_column(Boolean, server_default=false())


class AvailabilityWindow(Identity, Base):
    __tablename__ = "availability_windows"
    __table_args__ = (
        CheckConstraint("end_at > start_at", name="positive_window"),
        CheckConstraint("travel_buffer_minutes BETWEEN 0 AND 120", name="valid_buffer"),
        Index("ix_availability_owner_window", "owner_id", "start_at", "end_at"),
    )
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    location_id: Mapped[UUID] = mapped_column(ForeignKey("handoff_locations.id"), index=True)
    start_at: Mapped[datetime] = mapped_column(UTCDateTime())
    end_at: Mapped[datetime] = mapped_column(UTCDateTime())
    travel_buffer_minutes: Mapped[int] = mapped_column(Integer, server_default="15")


class ScheduleBlock(Identity, Base):
    __tablename__ = "schedule_blocks"
    __table_args__ = (
        CheckConstraint("end_at > start_at", name="positive_window"),
        Index("ix_schedule_owner_window", "owner_id", "start_at", "end_at"),
    )
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    start_at: Mapped[datetime] = mapped_column(UTCDateTime())
    end_at: Mapped[datetime] = mapped_column(UTCDateTime())
    private_location: Mapped[str] = mapped_column(String(200))


class CoordinationGrant(Identity, CreatedAt, Base):
    """Immutable, requester-approved query; digest is an opaque coordination capability."""

    __tablename__ = "coordination_grants"
    __table_args__ = (
        CheckConstraint("requester_id <> target_owner_id", name="different_people"),
        CheckConstraint("window_end > window_start", name="positive_window"),
        CheckConstraint("return_at > window_end", name="valid_return"),
        ForeignKeyConstraint(
            ["location_id", "community_id"],
            ["handoff_locations.id", "handoff_locations.community_id"],
        ),
    )
    authorizing_token_id: Mapped[UUID] = mapped_column(ForeignKey("api_tokens.id"), index=True)
    requester_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    target_owner_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    community_id: Mapped[UUID] = mapped_column(ForeignKey("communities.id"), index=True)
    location_id: Mapped[UUID] = mapped_column(index=True)
    canonical_item: Mapped[str] = mapped_column(String(100))
    subtype: Mapped[str | None] = mapped_column(String(100))
    window_start: Mapped[datetime] = mapped_column(UTCDateTime())
    window_end: Mapped[datetime] = mapped_column(UTCDateTime())
    return_at: Mapped[datetime] = mapped_column(UTCDateTime())
    check_count: Mapped[int] = mapped_column(Integer, server_default="0")
    capability_digest: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime())
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class SharingApproval(Identity, CreatedAt, Base):
    __tablename__ = "sharing_approvals"
    grant_id: Mapped[UUID] = mapped_column(ForeignKey("coordination_grants.id"), unique=True)
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
