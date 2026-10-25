"""Contract and dependency-boundary checks complement, not replace, database authorization."""

import ast
import io
import logging
from pathlib import Path
from typing import Any
from unittest.mock import Mock

import pytest
from pydantic import SecretStr, ValidationError

from agents.guard import PrivacyGateway
from agents.schemas import AvailabilityResult, GatewayRequest, ItemInput, ScheduleInput
from core.logging import JsonFormatter
from db.connection import Database
from tests.privacy_fixtures import CANARY, NOW


@pytest.mark.parametrize(
    "field",
    [
        "inventory",
        "items",
        "schedule",
        "private_address",
        "owner_id",
        "student_id",
        "hidden_identifier",
        "lending_policy",
        "max_duration_minutes",
        "token",
    ],
)
def test_gateway_response_rejects_prohibited_fields(field: str) -> None:
    with pytest.raises(ValidationError) as failure:
        AvailabilityResult.model_validate({"eligible": True, field: CANARY})
    assert CANARY not in str(failure.value)


@pytest.mark.parametrize("field", ["student_id", "owner_id", "sql", "schedule", "location"])
def test_gateway_request_rejects_unsanctioned_fields(field: str) -> None:
    with pytest.raises(ValidationError):
        GatewayRequest.model_validate({"capability": "x" * 43, field: CANARY})


@pytest.mark.parametrize(
    "payload",
    [
        {"eligible": False, "location": "library", "window": {"start_at": NOW, "end_at": NOW}},
        {"eligible": True, "location": "private-address"},
        {"eligible": True, "location": "123 Secret Street", "window": {}},
        {"eligible": True, "reason": "unavailable"},
    ],
)
def test_gateway_response_rejects_inconsistent_shapes(payload: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        AvailabilityResult.model_validate(payload)


def test_private_input_cannot_select_another_owner_or_naive_time() -> None:
    with pytest.raises(ValidationError):
        ItemInput.model_validate(
            dict(canonical_item="calculator", max_duration_minutes=60, owner_id="another-student")
        )
    with pytest.raises(ValidationError):
        ScheduleInput(start_at=NOW.replace(tzinfo=None), end_at=NOW, private_location=CANARY)


async def test_gateway_errors_and_logs_exclude_sensitive_values() -> None:
    database = Mock(spec=Database)
    database.transaction.side_effect = RuntimeError(CANARY)
    buffer = io.StringIO()
    handler = logging.StreamHandler(buffer)
    handler.setFormatter(JsonFormatter())
    logger = logging.getLogger("agents.guard")
    logger.addHandler(handler)
    try:
        result = await PrivacyGateway(database).check(
            GatewayRequest(capability=SecretStr("x" * 43))
        )
    finally:
        logger.removeHandler(handler)
    assert result.eligible is False
    assert CANARY not in result.model_dump_json() + buffer.getvalue()
    assert "gateway_failed_closed" in buffer.getvalue()
    assert "RuntimeError" in buffer.getvalue()


def violations(source: str, path: str) -> list[str]:
    found = []
    for node in ast.walk(ast.parse(source)):
        modules = []
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            modules = [module, *[module + "." + alias.name for alias in node.names]]
            if node.level:
                found.append("relative imports are disallowed at this service boundary")
        elif isinstance(node, ast.Import):
            modules = [alias.name for alias in node.names]
        for module in modules:
            if module.startswith("db.repositories") and path != "agents/personal.py":
                found.append(module)
            if module.startswith("db.models"):
                found.append(module)
            if path == "agents/group.py" and module.startswith(
                (
                    "db",
                    "core.identity",
                    "agents.personal",
                    "agents.registry",
                    "agents.guard",
                    "config",
                )
            ):
                found.append(module)
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id in ("__import__", "eval", "exec"):
                found.append("dynamic code/import")
            if isinstance(node.func, ast.Attribute) and node.func.attr == "import_module":
                found.append("dynamic import")
    return found


def test_unrelated_application_modules_do_not_import_private_repositories_or_models() -> None:
    root = Path(__file__).parents[1]
    for package in ("agents", "api", "core", "borrowing", "lostfound", "llm", "adapters"):
        for path in (root / package).rglob("*.py"):
            relative = path.relative_to(root).as_posix()
            assert violations(path.read_text(), relative) == [], relative


@pytest.mark.parametrize(
    "source",
    [
        "from db.repositories.private import PrivateRepository",
        "from db.repositories import private",
        "import db.models",
        "from db.connection import Database",
        "from core.identity import StudentSessions",
        "__import__('db.repositories.private')",
    ],
)
def test_boundary_checker_detects_unapproved_dependency(source: str) -> None:
    assert violations(source, "agents/group.py")


async def test_private_service_errors_and_logs_exclude_sensitive_values() -> None:
    from collections.abc import AsyncIterator
    from contextlib import asynccontextmanager
    from uuid import uuid4

    from sqlalchemy.exc import SQLAlchemyError
    from sqlalchemy.ext.asyncio import AsyncSession

    from agents.personal import PersonalAgent
    from core.errors import AppError
    from core.identity import AuthenticatedStudent, StudentSessions

    sessions = Mock(spec=StudentSessions)

    @asynccontextmanager
    async def failing_session(actor: AuthenticatedStudent) -> AsyncIterator[AsyncSession]:
        raise SQLAlchemyError(CANARY)
        yield  # pragma: no cover

    sessions.open.side_effect = failing_session
    buffer = io.StringIO()
    handler = logging.StreamHandler(buffer)
    handler.setFormatter(JsonFormatter())
    logger = logging.getLogger("agents.personal")
    logger.addHandler(handler)
    try:
        agent = PersonalAgent(AuthenticatedStudent(uuid4(), SecretStr("x" * 43)), sessions)
        with pytest.raises(AppError) as error:
            await agent.items()
    finally:
        logger.removeHandler(handler)
    assert CANARY not in str(error.value) + buffer.getvalue()
    assert "SQLAlchemyError" in buffer.getvalue()
