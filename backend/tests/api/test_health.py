from collections.abc import AsyncIterator

from fastapi.testclient import TestClient

from backend.db.database import get_session
from backend.main import create_app


async def override_session() -> AsyncIterator[object]:
    class HealthySession:
        async def execute(self, _: object) -> None:
            return None

    yield HealthySession()


def test_health_reports_single_worker_mode() -> None:
    app = create_app()
    app.dependency_overrides[get_session] = override_session
    with TestClient(app) as client:
        response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "database": "ok",
        "worker_mode": "in_process_single_worker",
    }
