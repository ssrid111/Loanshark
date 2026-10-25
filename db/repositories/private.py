"""Owner-only data access, enforced here AND by PostgreSQL RLS. No coordination reads."""

import hashlib
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

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
from core.errors import AppError
from db.models import (
    AuditEvent,
    AvailabilityWindow,
    CoordinationGrant,
    HandoffLocation,
    InventoryItem,
    LendingPolicy,
    Membership,
    ScheduleBlock,
    SharingApproval,
    Student,
    TrustedContact,
)


class PrivateRepository:
    def __init__(self, session: AsyncSession, owner_id: UUID) -> None:
        self._session = session
        self._owner_id = owner_id

    async def authorize(self) -> None:
        actual = await self._session.scalar(text("SELECT private.current_student()"))
        if actual is None or actual != self._owner_id:
            raise AppError("not_authorized", 403)

    def audit(self, event: str, resource: UUID | None = None) -> None:
        self._session.add(
            AuditEvent(
                event_type=event,
                actor_id=self._owner_id,
                resource_kind="private_access",
                resource_id=resource or self._owner_id,
                correlation_id=uuid4(),
            )
        )

    async def items(self) -> list[ItemView]:
        await self.authorize()
        rows = (
            await self._session.execute(
                select(InventoryItem, LendingPolicy)
                .join(LendingPolicy, InventoryItem.policy_id == LendingPolicy.id)
                .where(
                    InventoryItem.owner_id == self._owner_id,
                    LendingPolicy.owner_id == self._owner_id,
                )
            )
        ).all()
        self.audit("inventory_read")
        return [self._item(item, policy) for item, policy in rows]

    @staticmethod
    def _item(item: InventoryItem, policy: LendingPolicy) -> ItemView:
        return ItemView(
            id=item.id,
            canonical_item=item.canonical_item,
            subtype=item.subtype,
            available=item.active,
            same_day_only=policy.same_day_only,
            known_contacts_only=policy.known_contacts_only,
            max_duration_minutes=policy.max_duration_minutes,
        )

    async def save_item(self, data: ItemInput, item_id: UUID | None = None) -> ItemView:
        await self.authorize()
        if item_id is None:
            policy = LendingPolicy(owner_id=self._owner_id)
            self._session.add(policy)
            # Set required fields before flush.
            policy.max_duration_minutes = data.max_duration_minutes
            policy.same_day_only = data.same_day_only
            policy.known_contacts_only = data.known_contacts_only
            await self._session.flush()
            item = InventoryItem(owner_id=self._owner_id, policy_id=policy.id)
            self._session.add(item)
        else:
            item_row = await self._session.scalar(
                select(InventoryItem)
                .where(InventoryItem.id == item_id, InventoryItem.owner_id == self._owner_id)
                .with_for_update()
            )
            if item_row is None:
                raise AppError("not_found", 404)
            item = item_row
            policy_row = await self._session.scalar(
                select(LendingPolicy).where(
                    LendingPolicy.id == item.policy_id, LendingPolicy.owner_id == self._owner_id
                )
            )
            if policy_row is None:
                raise AppError("not_authorized", 403)
            policy = policy_row
            item.version += 1
        item.canonical_item, item.subtype, item.active = (
            data.canonical_item,
            data.subtype,
            data.available,
        )
        policy.max_duration_minutes = data.max_duration_minutes
        policy.same_day_only, policy.known_contacts_only = (
            data.same_day_only,
            data.known_contacts_only,
        )
        await self._session.flush()
        self.audit("inventory_saved", item.id)
        return self._item(item, policy)

    async def schedule(self) -> list[ScheduleView]:
        await self.authorize()
        rows = await self._session.scalars(
            select(ScheduleBlock).where(ScheduleBlock.owner_id == self._owner_id)
        )
        self.audit("schedule_read")
        return [
            ScheduleView(
                id=row.id,
                start_at=row.start_at,
                end_at=row.end_at,
                private_location=row.private_location,
            )
            for row in rows
        ]

    async def save_schedule(self, data: ScheduleInput) -> ScheduleView:
        await self.authorize()
        row = ScheduleBlock(owner_id=self._owner_id, **data.model_dump())
        self._session.add(row)
        await self._session.flush()
        self.audit("schedule_saved", row.id)
        return ScheduleView(id=row.id, **data.model_dump())

    async def remove_schedule(self, identifier: UUID) -> None:
        await self.authorize()
        row = await self._session.scalar(
            select(ScheduleBlock).where(
                ScheduleBlock.id == identifier, ScheduleBlock.owner_id == self._owner_id
            )
        )
        if row is None:
            raise AppError("not_found", 404)
        await self._session.delete(row)
        self.audit("schedule_removed", identifier)

    async def availability(self) -> list[AvailabilityView]:
        await self.authorize()
        rows = await self._session.scalars(
            select(AvailabilityWindow).where(AvailabilityWindow.owner_id == self._owner_id)
        )
        self.audit("availability_read")
        return [
            AvailabilityView(
                id=row.id,
                start_at=row.start_at,
                end_at=row.end_at,
                location_id=row.location_id,
                travel_buffer_minutes=row.travel_buffer_minutes,
            )
            for row in rows
        ]

    async def save_availability(self, data: AvailabilityInput) -> AvailabilityView:
        await self.authorize()
        location = await self._session.get(HandoffLocation, data.location_id)
        if location is None or not location.approved:
            raise AppError("not_found", 404)
        membership = await self._session.scalar(
            select(Membership.id).where(
                Membership.user_id == self._owner_id,
                Membership.community_id == location.community_id,
                Membership.verified.is_(True),
                Membership.opted_in.is_(True),
            )
        )
        if membership is None:
            raise AppError("not_authorized", 403)
        row = AvailabilityWindow(owner_id=self._owner_id, **data.model_dump())
        self._session.add(row)
        await self._session.flush()
        self.audit("availability_saved", row.id)
        return AvailabilityView(id=row.id, **data.model_dump())

    async def remove_availability(self, identifier: UUID) -> None:
        await self.authorize()
        row = await self._session.scalar(
            select(AvailabilityWindow).where(
                AvailabilityWindow.id == identifier, AvailabilityWindow.owner_id == self._owner_id
            )
        )
        if row is None:
            raise AppError("not_found", 404)
        await self._session.delete(row)
        self.audit("availability_removed", identifier)

    async def profile(self) -> Student:
        await self.authorize()
        row = await self._session.get(Student, self._owner_id)
        if row is None:
            raise AppError("not_authorized", 403)
        return row

    async def pause(self, paused: bool) -> None:
        row = await self.profile()
        row.paused_lending = paused
        self.audit("lending_pause_changed")

    async def coverage(self, data: TimeWindow, verified_at: datetime) -> None:
        row = await self.profile()
        row.schedule_known_from, row.schedule_known_until = data.start_at, data.end_at
        row.schedule_verified_at = verified_at
        self.audit("schedule_coverage_confirmed")

    async def trust(self, contact_id: UUID, community_id: UUID) -> None:
        await self.authorize()
        # Membership of the other student is checked inside the protected DB function.
        await self._session.execute(
            text("SELECT private.add_trusted_contact(:contact, :community)"),
            {"contact": contact_id, "community": community_id},
        )
        self.audit("trusted_contact_added")

    async def authorize_check(
        self, intent: CheckIntent, ticket: CoordinationTicket, expires_at: datetime
    ) -> None:
        await self.authorize()
        token_id = await self._session.scalar(text("SELECT private.current_token_id()"))
        if token_id is None:
            raise AppError("not_authorized", 403)
        self._session.add(
            CoordinationGrant(
                authorizing_token_id=token_id,
                id=ticket.grant_id,
                requester_id=self._owner_id,
                capability_digest=hashlib.sha256(
                    ticket.capability.get_secret_value().encode()
                ).hexdigest(),
                target_owner_id=intent.target_owner_id,
                community_id=intent.community_id,
                location_id=intent.location_id,
                canonical_item=intent.canonical_item,
                subtype=intent.subtype,
                window_start=intent.start_at,
                window_end=intent.end_at,
                return_at=intent.return_at,
                expires_at=expires_at,
            )
        )
        await self._session.flush()
        self.audit("coordination_authorized", ticket.grant_id)

    async def approve_disclosure(self, grant_id: UUID) -> None:
        await self.authorize()
        grant = await self._session.scalar(
            select(CoordinationGrant).where(
                CoordinationGrant.id == grant_id,
                CoordinationGrant.target_owner_id == self._owner_id,
            )
        )
        if grant is None:
            raise AppError("not_found", 404)
        previous = await self._session.scalar(
            select(SharingApproval.id).where(
                SharingApproval.grant_id == grant_id, SharingApproval.owner_id == self._owner_id
            )
        )
        if previous is None:
            self._session.add(SharingApproval(grant_id=grant_id, owner_id=self._owner_id))
        self.audit("disclosure_approved", grant_id)

    async def revoke_disclosure(self, grant_id: UUID) -> None:
        await self.authorize()
        row = await self._session.scalar(
            select(SharingApproval).where(
                SharingApproval.grant_id == grant_id, SharingApproval.owner_id == self._owner_id
            )
        )
        if row is not None:
            await self._session.delete(row)
        self.audit("disclosure_revoked", grant_id)

    async def untrust(self, contact_id: UUID, community_id: UUID) -> None:
        await self.authorize()
        row = await self._session.scalar(
            select(TrustedContact).where(
                TrustedContact.owner_id == self._owner_id,
                TrustedContact.contact_id == contact_id,
                TrustedContact.community_id == community_id,
            )
        )
        if row is not None:
            await self._session.delete(row)
        self.audit("trusted_contact_removed")

    async def community_opt_in(self, community_id: UUID, opted_in: bool) -> None:
        await self.authorize()
        row = await self._session.scalar(
            select(Membership).where(
                Membership.user_id == self._owner_id,
                Membership.community_id == community_id,
                Membership.verified.is_(True),
            )
        )
        if row is None:
            raise AppError("not_authorized", 403)
        row.opted_in = opted_in
        self.audit("community_opt_in_changed")
