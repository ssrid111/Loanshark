"""Committed synthetic fixtures for real separate-role connections; disposable *_test DB only."""

import secrets
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from pydantic import SecretStr
from sqlalchemy import text

from agents.guard import PrivacyGateway
from agents.personal import PersonalAgent
from agents.registry import PersonalAgentRegistry
from agents.schemas import CheckIntent, CoordinationTicket, GatewayRequest
from config import Settings
from core.identity import AuthenticatedStudent, StudentSessions
from db.connection import Database
from db.models import (
    ApiToken,
    AvailabilityWindow,
    Community,
    HandoffLocation,
    InventoryItem,
    LendingPolicy,
    Membership,
    ScheduleBlock,
    Student,
    TrustedContact,
)
from tests.conftest import test_url

NOW = datetime(2030, 1, 15, 12, tzinfo=UTC)
CANARY = "private-address-and-hidden-inventory-DO-NOT-EXPOSE"


@dataclass
class FakeClock:
    current: datetime = NOW

    def now(self) -> datetime:
        return self.current


@dataclass
class World:
    admin: Database
    runtime: Database
    gateway_db: Database
    sessions: StudentSessions
    registry: PersonalAgentRegistry
    gateway: PrivacyGateway
    clock: FakeClock
    actors: list[AuthenticatedStudent]
    agents: list[PersonalAgent]
    community: UUID
    location: UUID
    item: UUID
    policy: UUID
    block: UUID

    def intent(self, **changes: object) -> CheckIntent:
        data: dict[str, object] = dict(
            community_id=self.community,
            target_owner_id=self.actors[1].student_id,
            location_id=self.location,
            canonical_item="calculator",
            subtype="graphing",
            start_at=NOW + timedelta(minutes=30),
            end_at=NOW + timedelta(minutes=60),
            return_at=NOW + timedelta(minutes=90),
            confirmed=True,
        )
        data.update(changes)
        return CheckIntent.model_validate(data)

    async def ticket(self, **changes: object) -> CoordinationTicket:
        return await self.agents[0].authorize_check(self.intent(**changes))

    async def check(self, ticket: CoordinationTicket) -> object:
        return await self.gateway.check(GatewayRequest(capability=ticket.capability))

    async def sql(self, statement: str, **parameters: object) -> None:
        async with self.admin.transaction() as session:
            await session.execute(text(statement), parameters)


@pytest.fixture
async def world() -> AsyncIterator[World]:
    admin = Database(Settings(_env_file=None, database_url=SecretStr(test_url())))
    runtime = Database(
        Settings(_env_file=None, database_url=SecretStr(test_url("TEST_RUNTIME_DATABASE_URL")))
    )
    gateway_db = Database(
        Settings(_env_file=None, database_url=SecretStr(test_url("TEST_GATEWAY_DATABASE_URL")))
    )
    tokens = [SecretStr(secrets.token_urlsafe(32)) for _ in range(4)]
    import hashlib

    try:
        async with admin.transaction() as session:
            people = [
                Student(
                    platform="demo",
                    platform_user_id=str(uuid4()),
                    timezone="UTC",
                    schedule_known_from=NOW - timedelta(hours=1),
                    schedule_known_until=NOW + timedelta(days=3),
                    schedule_verified_at=NOW,
                )
                for _ in range(4)
            ]
            group = Community(platform="demo", guild_id=str(uuid4()), channel_id=str(uuid4()))
            session.add_all([*people, group])
            await session.flush()
            location = HandoffLocation(
                community_id=group.id, code="library-entrance", approved=True
            )
            policy = LendingPolicy(
                owner_id=people[1].id,
                same_day_only=True,
                known_contacts_only=True,
                max_duration_minutes=120,
            )
            session.add_all([location, policy])
            await session.flush()
            item = InventoryItem(
                owner_id=people[1].id,
                policy_id=policy.id,
                canonical_item="calculator",
                subtype="graphing",
            )
            private_item = InventoryItem(
                owner_id=people[1].id,
                policy_id=policy.id,
                canonical_item="secret-device",
                subtype=CANARY,
            )
            block = ScheduleBlock(
                owner_id=people[1].id,
                start_at=NOW + timedelta(hours=2),
                end_at=NOW + timedelta(hours=3),
                private_location=CANARY,
            )
            session.add_all([item, private_item, block])
            for index, person in enumerate(people):
                session.add(
                    ApiToken(
                        user_id=person.id,
                        token_digest=hashlib.sha256(
                            tokens[index].get_secret_value().encode()
                        ).hexdigest(),
                        expires_at=datetime(2099, 1, 1, tzinfo=UTC),
                    )
                )
                if index < 3:
                    session.add(
                        Membership(
                            user_id=person.id, community_id=group.id, verified=True, opted_in=True
                        )
                    )
                    session.add(
                        AvailabilityWindow(
                            owner_id=person.id,
                            location_id=location.id,
                            start_at=NOW + timedelta(minutes=15),
                            end_at=NOW + timedelta(minutes=75),
                            travel_buffer_minutes=10,
                        )
                    )
            session.add(
                TrustedContact(
                    owner_id=people[1].id, contact_id=people[0].id, community_id=group.id
                )
            )
            await session.flush()
            ids = [person.id for person in people]
        clock = FakeClock()
        sessions = StudentSessions(runtime)
        registry = PersonalAgentRegistry(sessions, clock)
        actors = [await registry.authenticate(token) for token in tokens]
        agents = [
            await registry.resolve(actor, identifier)
            for actor, identifier in zip(actors, ids, strict=True)
        ]
        yield World(
            admin,
            runtime,
            gateway_db,
            sessions,
            registry,
            PrivacyGateway(gateway_db, clock),
            clock,
            actors,
            agents,
            group.id,
            location.id,
            item.id,
            policy.id,
            block.id,
        )
    finally:
        await gateway_db.close()
        await runtime.close()
        await admin.close()
