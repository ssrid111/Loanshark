from config import Settings
from core.errors import AppError
from main import create_app
from tests.conftest import client_for


async def test_liveness_without_database(settings: Settings) -> None:
    async with client_for(create_app(settings)) as client:
        response = await client.get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "alive"}
    assert response.headers["x-request-id"]


async def test_unreachable_database_is_not_ready(settings: Settings) -> None:
    async with client_for(create_app(settings)) as client:
        response = await client.get("/health/ready")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "not_ready"
    assert "test:test" not in response.text


async def test_no_business_or_private_endpoints(settings: Settings) -> None:
    async with client_for(create_app(settings)) as client:
        response = await client.post("/v1/requests", json={"actor_id": "someone-else"})
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "http_404"


async def test_unexpected_error_is_sanitized(settings: Settings) -> None:
    app = create_app(settings)

    @app.get("/test-error")
    async def fail() -> None:
        raise RuntimeError("sensitive-student-detail-and-password")

    async with client_for(app) as client:
        response = await client.get("/test-error")
    assert response.status_code == 500
    assert "sensitive" not in response.text
    assert response.json()["error"]["request_id"] == response.headers["x-request-id"]


async def test_known_error(settings: Settings) -> None:
    app = create_app(settings)

    @app.get("/test-domain-error")
    async def fail() -> None:
        raise AppError("not_authorized", 403)

    async with client_for(app) as client:
        response = await client.get("/test-domain-error")
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "not_authorized"


async def test_validation_does_not_echo_input(settings: Settings) -> None:
    app = create_app(settings)

    @app.get("/test-validation")
    async def validate(number: int) -> dict[str, int]:
        return {"number": number}

    async with client_for(app) as client:
        response = await client.get("/test-validation?number=private-input")
    assert response.status_code == 422
    assert "private-input" not in response.text
