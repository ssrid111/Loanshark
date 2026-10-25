from datetime import timedelta
from uuid import uuid4

import pytest
from pydantic import SecretStr
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from agents.group import GroupAgent
from agents.personal import PersonalAgent
from agents.schemas import (
    AvailabilityInput,
    AvailabilityResult,
    GatewayRequest,
    ItemInput,
    ScheduleInput,
    TimeWindow,
)
from core.errors import AppError
from core.identity import AuthenticatedStudent
from db.models import InventoryItem, ScheduleBlock
from db.repositories.private import PrivateRepository
from tests.privacy_fixtures import CANARY, NOW, World

pytestmark = pytest.mark.integration


async def test_registry_and_private_management(world: World) -> None:
    owner = world.agents[0]
    item = await owner.save_item(
        ItemInput(canonical_item="charger", subtype="usb-c", max_duration_minutes=60)
    )
    assert (await owner.items())[0].id == item.id
    changed = await owner.save_item(
        ItemInput(
            canonical_item="charger", subtype="usb-c", max_duration_minutes=30, available=False
        ),
        item.id,
    )
    assert not changed.available and changed.max_duration_minutes == 30
    assert all(row.id != item.id for row in await world.agents[1].items())
    block = await owner.save_schedule(
        ScheduleInput(start_at=NOW, end_at=NOW + timedelta(minutes=5), private_location=CANARY)
    )
    assert (await owner.schedule())[0].private_location == CANARY
    await owner.remove_schedule(block.id)
    assert await owner.schedule() == []
    availability = await owner.save_availability(
        AvailabilityInput(
            location_id=world.location,
            start_at=NOW + timedelta(hours=4),
            end_at=NOW + timedelta(hours=5),
        )
    )
    assert any(row.id == availability.id for row in await owner.availability())
    await owner.remove_availability(availability.id)


async def test_registry_rejects_another_student_id(world: World) -> None:
    with pytest.raises(AppError, match="not_authorized"):
        await world.registry.resolve(world.actors[0], world.actors[1].student_id)


async def test_forged_python_identity_is_not_authority(world: World) -> None:
    forged = AuthenticatedStudent(world.actors[1].student_id, world.actors[0].token)
    with pytest.raises(AppError, match="not_authorized"):
        await world.registry.resolve(forged, forged.student_id)
    # Bypassing the registry does not bypass the session and repository checks.
    agent = PersonalAgent(forged, world.sessions, world.clock)
    with pytest.raises(AppError):
        await agent.items()


async def test_cross_owner_mutation_and_schedule_deletion_denied(world: World) -> None:
    for identifier in (world.item, uuid4()):
        with pytest.raises(AppError, match="not_found"):
            await world.agents[0].save_item(
                ItemInput(canonical_item="calculator", max_duration_minutes=60), identifier
            )
    with pytest.raises(AppError, match="not_found"):
        await world.agents[0].remove_schedule(world.block)
    assert (await world.agents[1].schedule())[0].id == world.block


async def test_repository_checks_context_even_with_valid_session(world: World) -> None:
    async with world.sessions.open(world.actors[0]) as session:
        repository = PrivateRepository(session, world.actors[1].student_id)
        with pytest.raises(AppError, match="not_authorized"):
            await repository.items()
        with pytest.raises(AppError, match="not_authorized"):
            await repository.schedule()


async def test_rls_blocks_direct_cross_owner_queries_and_forged_guc(world: World) -> None:
    async with world.sessions.open(world.actors[0]) as session:
        await session.execute(
            text("SELECT set_config('loanshark.student_id',:id,true)"),
            {"id": str(world.actors[1].student_id)},
        )
        assert list(await session.scalars(select(InventoryItem))) == []
        assert list(await session.scalars(select(ScheduleBlock))) == []
        result = await session.execute(
            text("UPDATE inventory SET active=false WHERE id=:id"), {"id": world.item}
        )
        assert result.rowcount == 0  # type: ignore[attr-defined]
    async with world.runtime.transaction() as session:
        # Connection pooling cannot retain the previous student's SET LOCAL token.
        assert await session.scalar(text("SELECT private.current_student()")) is None
        assert list(await session.scalars(select(InventoryItem))) == []


async def test_rls_rejects_cross_owner_insert(world: World) -> None:
    async with world.sessions.open(world.actors[0]) as session:
        session.add(
            InventoryItem(
                owner_id=world.actors[1].student_id,
                policy_id=world.policy,
                canonical_item="calculator",
            )
        )
        with pytest.raises(DBAPIError):
            await session.flush()


@pytest.mark.parametrize(
    "table",
    [
        "inventory",
        "schedule_blocks",
        "lending_policies",
        "api_tokens",
        "users",
        "coordination_grants",
    ],
)
async def test_gateway_role_cannot_read_private_tables(world: World, table: str) -> None:
    async with world.gateway_db.transaction() as session:
        with pytest.raises(DBAPIError):
            await session.execute(text(f"SELECT * FROM {table}"))


async def test_runtime_cannot_call_privileged_gateway_function(world: World) -> None:
    ticket = await world.ticket()
    async with world.sessions.open(world.actors[0]) as session:
        with pytest.raises(DBAPIError):
            await session.execute(
                text("SELECT * FROM private.check_availability(:token,:now,:correlation)"),
                {"token": ticket.capability.get_secret_value(), "now": NOW, "correlation": uuid4()},
            )


async def test_minimal_result_then_explicit_disclosure_and_revocation(world: World) -> None:
    ticket = await world.ticket()
    group = GroupAgent(world.gateway)
    result = await group.check(GatewayRequest(capability=ticket.capability))
    assert result.model_dump(exclude_none=True) == {"eligible": True}
    with pytest.raises(AppError):
        await world.agents[0].approve_disclosure(ticket.grant_id)
    await world.agents[1].approve_disclosure(ticket.grant_id)
    result = await group.check(GatewayRequest(capability=ticket.capability))
    assert result.location == "library-entrance"
    assert result.window and result.window.start_at == NOW + timedelta(minutes=30)
    assert set(result.model_dump(exclude_none=True)) == {"eligible", "location", "window"}
    assert CANARY not in result.model_dump_json()
    await world.agents[1].revoke_disclosure(ticket.grant_id)
    assert (await group.check(GatewayRequest(capability=ticket.capability))).location is None


@pytest.mark.parametrize(
    "case",
    [
        "paused",
        "inactive_item",
        "wrong_subtype",
        "duration",
        "same_day",
        "untrusted",
        "unknown_schedule",
        "stale_schedule",
        "busy_owner",
        "busy_borrower",
        "no_availability",
        "membership_revoked",
        "unverified_member",
        "unapproved_location",
        "expired_grant",
        "revoked_token",
        "revoked_grant",
        "invalid_timezone",
    ],
)
async def test_gateway_fails_closed_for_policy_and_schedule_cases(world: World, case: str) -> None:
    ticket = await world.ticket()
    target = world.actors[1].student_id
    if case == "paused":
        await world.agents[1].pause_lending(True)
    elif case == "inactive_item":
        await world.sql("UPDATE inventory SET active=false WHERE id=:id", id=world.item)
    elif case == "wrong_subtype":
        await world.sql("UPDATE inventory SET subtype='basic' WHERE id=:id", id=world.item)
    elif case == "duration":
        await world.sql(
            "UPDATE lending_policies SET max_duration_minutes=10 WHERE id=:id", id=world.policy
        )
    elif case == "same_day":
        await world.sql(
            "UPDATE coordination_grants SET return_at=:returns WHERE id=:id",
            returns=NOW + timedelta(days=1),
            id=ticket.grant_id,
        )
        await world.sql(
            "UPDATE lending_policies SET max_duration_minutes=3000 WHERE id=:id", id=world.policy
        )
    elif case == "untrusted":
        await world.sql("DELETE FROM trusted_contacts WHERE owner_id=:id", id=target)
    elif case == "unknown_schedule":
        await world.sql("UPDATE users SET schedule_known_until=NULL WHERE id=:id", id=target)
    elif case == "stale_schedule":
        await world.sql(
            "UPDATE users SET schedule_verified_at=:old WHERE id=:id",
            old=NOW - timedelta(days=2),
            id=target,
        )
    elif case in ("busy_owner", "busy_borrower"):
        person = world.agents[1] if case == "busy_owner" else world.agents[0]
        await person.save_schedule(
            ScheduleInput(start_at=NOW, end_at=NOW + timedelta(hours=1), private_location=CANARY)
        )
    elif case == "no_availability":
        await world.sql("DELETE FROM availability_windows WHERE owner_id=:id", id=target)
    elif case in ("membership_revoked", "unverified_member"):
        column = "opted_in" if case == "membership_revoked" else "verified"
        await world.sql(f"UPDATE memberships SET {column}=false WHERE user_id=:id", id=target)
    elif case == "unapproved_location":
        await world.sql(
            "UPDATE handoff_locations SET approved=false WHERE id=:id", id=world.location
        )
    elif case == "expired_grant":
        world.clock.current = NOW + timedelta(minutes=16)
    elif case == "revoked_token":
        await world.sql(
            "UPDATE api_tokens SET revoked_at=:now WHERE user_id=:id",
            now=NOW,
            id=world.actors[0].student_id,
        )
        # A capability may not remain valid after its authorizing identity is revoked.
    elif case == "revoked_grant":
        await world.sql(
            "UPDATE coordination_grants SET revoked_at=:now WHERE id=:id",
            now=NOW,
            id=ticket.grant_id,
        )
    elif case == "invalid_timezone":
        await world.sql("UPDATE users SET timezone='invalid-timezone' WHERE id=:id", id=target)
    result = await world.gateway.check(GatewayRequest(capability=ticket.capability))
    assert result == AvailabilityResult(eligible=False, reason="unavailable")
    assert CANARY not in result.model_dump_json()


async def test_feasible_window_respects_busy_block_and_travel_buffer(world: World) -> None:
    await world.agents[1].save_schedule(
        ScheduleInput(start_at=NOW, end_at=NOW + timedelta(minutes=35), private_location=CANARY)
    )
    ticket = await world.ticket()
    await world.agents[1].approve_disclosure(ticket.grant_id)
    result = await world.gateway.check(GatewayRequest(capability=ticket.capability))
    assert result.eligible and result.window
    assert result.window.start_at == NOW + timedelta(minutes=45)
    assert result.window.end_at == NOW + timedelta(minutes=50)


async def test_pause_can_be_resumed_and_coverage_explicitly_confirmed(world: World) -> None:
    ticket = await world.ticket()
    await world.agents[1].pause_lending(True)
    assert not (await world.gateway.check(GatewayRequest(capability=ticket.capability))).eligible
    await world.agents[1].pause_lending(False)
    await world.agents[1].confirm_schedule_coverage(
        TimeWindow(start_at=NOW, end_at=NOW + timedelta(hours=2))
    )
    assert (await world.gateway.check(GatewayRequest(capability=ticket.capability))).eligible


async def test_unknown_capability_and_probe_budget(world: World) -> None:
    assert not (await world.gateway.check(GatewayRequest(capability=SecretStr("x" * 43)))).eligible
    ticket = await world.ticket()
    for _ in range(20):
        assert (await world.gateway.check(GatewayRequest(capability=ticket.capability))).eligible
    assert not (await world.gateway.check(GatewayRequest(capability=ticket.capability))).eligible


async def test_revoked_identity_cannot_use_cached_agent(world: World) -> None:
    await world.sql(
        "UPDATE api_tokens SET revoked_at=:now WHERE user_id=:id",
        now=NOW,
        id=world.actors[0].student_id,
    )
    with pytest.raises(AppError, match="not_authorized"):
        await world.agents[0].items()
    with pytest.raises(AppError):
        await world.registry.authenticate(world.actors[0].token)


async def test_sensitive_access_decisions_are_append_only_audited(world: World) -> None:
    ticket = await world.ticket()
    await world.gateway.check(GatewayRequest(capability=ticket.capability))
    await world.agents[1].items()
    with pytest.raises(AppError):
        await world.agents[0].remove_schedule(world.block)
    async with world.admin.transaction() as session:
        events = (await session.execute(text("SELECT event_type,resource_id FROM audit_log"))).all()
        assert any(
            event == "availability_eligible" and resource == ticket.grant_id
            for event, resource in events
        )
        assert any(event == "owner_operation_denied" for event, _ in events)
        assert CANARY not in repr(events)
    async with world.gateway_db.transaction() as session:
        with pytest.raises(DBAPIError):
            await session.execute(text("DELETE FROM audit_log"))


async def test_owner_can_withdraw_trust_and_opt_in(world: World) -> None:
    ticket = await world.ticket()
    await world.agents[1].untrust(world.actors[0].student_id, world.community)
    assert not (await world.gateway.check(GatewayRequest(capability=ticket.capability))).eligible
    await world.agents[1].trust(world.actors[0].student_id, world.community)
    assert (await world.gateway.check(GatewayRequest(capability=ticket.capability))).eligible
    await world.agents[1].community_opt_in(world.community, False)
    assert not (await world.gateway.check(GatewayRequest(capability=ticket.capability))).eligible


async def test_stranger_and_unknown_credentials_are_denied(world: World) -> None:
    with pytest.raises(AppError, match="not_authorized"):
        await world.registry.authenticate(SecretStr("not-a-valid-identity-token"))
    ticket = await world.agents[3].authorize_check(world.intent())
    assert not (await world.gateway.check(GatewayRequest(capability=ticket.capability))).eligible
    with pytest.raises(AppError, match="not_authorized"):
        await world.agents[1].trust(world.actors[3].student_id, world.community)


async def test_requester_cannot_forge_owner_disclosure_or_modify_granted_terms(
    world: World,
) -> None:
    ticket = await world.ticket()
    async with world.sessions.open(world.actors[0]) as session:
        with pytest.raises(DBAPIError):
            await session.execute(
                text(
                    "INSERT INTO sharing_approvals(id,grant_id,owner_id) VALUES(:id,:grant,:owner)"
                ),
                {"id": uuid4(), "grant": ticket.grant_id, "owner": world.actors[1].student_id},
            )
    async with world.sessions.open(world.actors[0]) as session:
        with pytest.raises(DBAPIError):
            await session.execute(
                text("UPDATE coordination_grants SET target_owner_id=:owner WHERE id=:grant"),
                {"owner": world.actors[2].student_id, "grant": ticket.grant_id},
            )


async def test_same_day_policy_uses_lenders_local_day(world: World) -> None:
    await world.sql(
        "UPDATE users SET timezone='America/Phoenix' WHERE id=:id", id=world.actors[1].student_id
    )
    await world.sql(
        "UPDATE lending_policies SET max_duration_minutes=1500 WHERE id=:id", id=world.policy
    )
    # Return crosses midnight UTC but remains on the lender's local calendar day.
    ticket = await world.ticket(return_at=NOW.replace(hour=0) + timedelta(days=1, minutes=30))
    result = await world.gateway.check(GatewayRequest(capability=ticket.capability))
    assert result.eligible


async def test_accidentally_privileged_connections_are_rejected(world: World) -> None:
    from agents.guard import PrivacyGateway
    from core.identity import StudentSessions

    privileged_sessions = StudentSessions(world.admin)
    with pytest.raises(AppError, match="not_authorized"):
        await privileged_sessions.authenticate(world.actors[0].token)
    ticket = await world.ticket()
    result = await PrivacyGateway(world.admin, world.clock).check(
        GatewayRequest(capability=ticket.capability)
    )
    assert not result.eligible
