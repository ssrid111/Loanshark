from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from pydantic import SecretStr
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError, IntegrityError, StatementError
from sqlalchemy.ext.asyncio import AsyncSession

from config import Settings
from db.connection import Database
from db.models import (
    AuditEvent,
    BorrowRequest,
    Community,
    Confirmation,
    FoundReport,
    InventoryItem,
    LendingPolicy,
    Loan,
    LostFoundReport,
    LostReport,
    Offer,
    Reservation,
    Student,
)
from main import create_app
from tests.conftest import client_for, test_url

pytestmark = pytest.mark.integration
NOW = datetime(2026, 10, 24, 16, tzinfo=UTC)


async def student(session: AsyncSession) -> Student:
    person = Student(platform="discord", platform_user_id=str(uuid4()))
    session.add(person)
    await session.flush()
    return person


async def community(session: AsyncSession) -> Community:
    group = Community(platform="discord", guild_id=str(uuid4()), channel_id=str(uuid4()))
    session.add(group)
    await session.flush()
    return group


async def test_database_connectivity(database: Database) -> None:
    async with database.engine.connect() as connection:
        assert await connection.scalar(text("SELECT 1")) == 1
        assert await connection.scalar(text("SHOW timezone")) == "UTC"
        assert str(await connection.scalar(text("SHOW server_version"))).startswith("17.")


async def test_student_platform_id_is_string_and_unique(session: AsyncSession) -> None:
    person = await student(session)
    assert isinstance(person.platform_user_id, str)
    assert person.joined_at.utcoffset() == timedelta(0)
    session.add(Student(platform=person.platform, platform_user_id=person.platform_user_id))
    with pytest.raises(IntegrityError):
        await session.flush()


async def test_inventory_requires_real_owner(session: AsyncSession) -> None:
    session.add(LendingPolicy(owner_id=uuid4(), max_duration_minutes=60))
    with pytest.raises(IntegrityError):
        await session.flush()


async def test_item_policy_must_belong_to_same_owner(session: AsyncSession) -> None:
    first, second = await student(session), await student(session)
    policy = LendingPolicy(owner_id=first.id, max_duration_minutes=60)
    session.add(policy)
    await session.flush()
    session.add(InventoryItem(owner_id=second.id, policy_id=policy.id, canonical_item="calculator"))
    with pytest.raises(IntegrityError):
        await session.flush()


async def test_policy_duration_positive(session: AsyncSession) -> None:
    person = await student(session)
    session.add(LendingPolicy(owner_id=person.id, max_duration_minutes=0))
    with pytest.raises(IntegrityError):
        await session.flush()


@pytest.mark.parametrize("invalid_state", [True, False])
async def test_request_constraints(session: AsyncSession, invalid_state: bool) -> None:
    person = await student(session)
    group = await community(session)
    session.add(
        BorrowRequest(
            borrower_id=person.id,
            community_id=group.id,
            canonical_item="calculator",
            need_by=NOW,
            proposed_return_at=NOW + timedelta(hours=1) if invalid_state else NOW,
            status="FAKE_SUCCESS" if invalid_state else "DRAFT",
        )
    )
    with pytest.raises(IntegrityError):
        await session.flush()


async def test_naive_timestamps_rejected_in_real_database(session: AsyncSession) -> None:
    person = await student(session)
    group = await community(session)
    session.add(
        BorrowRequest(
            borrower_id=person.id,
            community_id=group.id,
            canonical_item="calculator",
            need_by=NOW.replace(tzinfo=None),
            proposed_return_at=NOW + timedelta(hours=1),
        )
    )
    with pytest.raises(StatementError, match="Naive"):
        await session.flush()


async def test_confirmation_cannot_be_marked_decided_without_consumption(
    session: AsyncSession,
) -> None:
    person = await student(session)
    session.add(
        Confirmation(
            subject_id=person.id,
            action_kind="share_request",
            resource_kind="request",
            resource_id=uuid4(),
            resource_version=1,
            payload_digest="a" * 64,
            token_digest="b" * 64,
            created_at=NOW,
            expires_at=NOW + timedelta(minutes=10),
            decision="APPROVED",
        )
    )
    with pytest.raises(IntegrityError):
        await session.flush()


async def test_lost_and_found_use_separate_tables(session: AsyncSession) -> None:
    assert not hasattr(LostFoundReport, "__table__")
    person = await student(session)
    group = await community(session)
    lost = LostReport(
        reporter_id=person.id,
        community_id=group.id,
        canonical_item="calculator",
        zone="library",
        seen_from=NOW,
        seen_until=NOW,
    )
    found = FoundReport(
        reporter_id=person.id,
        community_id=group.id,
        canonical_item="calculator",
        zone="library",
        seen_from=NOW,
        seen_until=NOW,
        public_description="A calculator",
        encrypted_hidden_details=b"opaque-ciphertext",
        verification_prompt="Describe a distinctive marking.",
    )
    session.add_all([lost, found])
    await session.flush()
    assert await session.scalar(select(LostReport.id).where(LostReport.id == lost.id)) == lost.id
    assert (
        await session.scalar(select(FoundReport.id).where(FoundReport.id == found.id)) == found.id
    )


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE audit_log SET event_type='modified'",
        "DELETE FROM audit_log",
        "TRUNCATE audit_log",
    ],
)
async def test_audit_mutations_rejected(session: AsyncSession, statement: str) -> None:
    session.add(
        AuditEvent(
            event_type="foundation_test",
            resource_kind="test",
            resource_id=uuid4(),
            correlation_id=uuid4(),
        )
    )
    await session.flush()
    with pytest.raises(DBAPIError):
        await session.execute(text(statement))


async def test_transaction_rolls_back_on_exception(database: Database) -> None:
    identifier = str(uuid4())
    with pytest.raises(RuntimeError, match="intentional"):
        async with database.transaction() as session:
            session.add(Student(platform="discord", platform_user_id=identifier))
            await session.flush()
            raise RuntimeError("intentional rollback")
    async with database.transaction() as session:
        assert (
            await session.scalar(select(Student.id).where(Student.platform_user_id == identifier))
            is None
        )


async def test_real_readiness_after_migration() -> None:
    settings = Settings(
        _env_file=None, database_url=SecretStr(test_url("TEST_RUNTIME_DATABASE_URL"))
    )
    async with client_for(create_app(settings)) as client:
        response = await client.get("/health/ready")
    assert response.status_code == 200
    assert response.json()["database"] is True
    assert response.json()["migrations"] is True


async def test_runtime_role_has_no_ddl_or_audit_mutation_privileges() -> None:
    database = Database(
        Settings(_env_file=None, database_url=SecretStr(test_url("TEST_RUNTIME_DATABASE_URL")))
    )
    try:
        async with database.engine.connect() as conn:
            assert await conn.scalar(text("SELECT current_user")) == "loanshark_runtime"
            for privilege in ("UPDATE", "DELETE", "TRUNCATE"):
                assert not await conn.scalar(
                    text("SELECT has_table_privilege(current_user, 'audit_log', :privilege)"),
                    {"privilege": privilege},
                )
            assert await conn.scalar(
                text("SELECT has_table_privilege(current_user, 'audit_log', 'INSERT')")
            )
            assert not await conn.scalar(
                text("SELECT has_schema_privilege(current_user, 'public', 'CREATE')")
            )
    finally:
        await database.close()


async def reserved_item(
    session: AsyncSession,
) -> tuple[Student, Student, InventoryItem, Reservation]:
    lender, borrower = await student(session), await student(session)
    group = await community(session)
    policy = LendingPolicy(owner_id=lender.id, max_duration_minutes=60)
    session.add(policy)
    await session.flush()
    item = InventoryItem(owner_id=lender.id, policy_id=policy.id, canonical_item="calculator")
    request = BorrowRequest(
        borrower_id=borrower.id,
        community_id=group.id,
        canonical_item="calculator",
        need_by=NOW,
        proposed_return_at=NOW + timedelta(hours=1),
    )
    session.add_all([item, request])
    await session.flush()
    offer = Offer(
        item_id=item.id,
        lender_id=lender.id,
        request_id=request.id,
        expires_at=NOW + timedelta(minutes=10),
    )
    session.add(offer)
    await session.flush()
    reservation = Reservation(
        item_id=item.id,
        request_id=request.id,
        offer_id=offer.id,
        held_at=NOW,
        hold_expires_at=NOW + timedelta(minutes=10),
    )
    session.add(reservation)
    await session.flush()
    return lender, borrower, item, reservation


async def test_only_one_unreleased_reservation_per_item(session: AsyncSession) -> None:
    lender, borrower, item, reservation = await reserved_item(session)
    group = await community(session)
    other_request = BorrowRequest(
        borrower_id=borrower.id,
        community_id=group.id,
        canonical_item="calculator",
        need_by=NOW,
        proposed_return_at=NOW + timedelta(hours=1),
    )
    session.add(other_request)
    await session.flush()
    other_offer = Offer(
        item_id=item.id,
        lender_id=lender.id,
        request_id=other_request.id,
        expires_at=NOW + timedelta(minutes=10),
    )
    session.add(other_offer)
    await session.flush()
    session.add(
        Reservation(
            item_id=item.id,
            request_id=other_request.id,
            offer_id=other_offer.id,
            held_at=NOW,
            hold_expires_at=NOW + timedelta(minutes=10),
        )
    )
    with pytest.raises(IntegrityError):
        await session.flush()


@pytest.mark.parametrize("invalid_case", ["same_person", "duration", "missing_close_receipt"])
async def test_loan_constraints(session: AsyncSession, invalid_case: str) -> None:
    lender, borrower, item, reservation = await reserved_item(session)
    session.add(
        Loan(
            reservation_id=reservation.id,
            borrower_id=(lender.id if invalid_case == "same_person" else borrower.id),
            lender_id=lender.id,
            item_id=item.id,
            start_at=NOW,
            due_at=NOW if invalid_case == "duration" else NOW + timedelta(hours=1),
            status="CLOSED" if invalid_case == "missing_close_receipt" else "ACTIVE",
            closed_at=NOW + timedelta(minutes=30)
            if invalid_case == "missing_close_receipt"
            else None,
        )
    )
    with pytest.raises(IntegrityError):
        await session.flush()


async def test_loan_round_trip_persists_aware_timestamps(session: AsyncSession) -> None:
    lender, borrower, item, reservation = await reserved_item(session)
    loan = Loan(
        reservation_id=reservation.id,
        borrower_id=borrower.id,
        lender_id=lender.id,
        item_id=item.id,
        start_at=NOW,
        due_at=NOW + timedelta(hours=1),
    )
    session.add(loan)
    await session.flush()
    await session.refresh(loan)
    assert loan.status == "ACTIVE"
    assert loan.start_at.tzinfo is UTC
    assert loan.reservation_id == reservation.id
