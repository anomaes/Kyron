from fastapi.testclient import TestClient

from backend.main import create_app


def test_authenticated_route_rejects_missing_trusted_headers() -> None:
    with TestClient(create_app()) as client:
        response = client.get("/api/auth/me")
    assert response.status_code == 401
    assert response.json()["detail"] == "Missing trusted authentication headers"
