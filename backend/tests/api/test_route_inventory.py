from backend.api.run_routes import websocket_router
from backend.main import create_app


def test_required_http_and_websocket_routes_are_registered() -> None:
    paths = set(create_app().openapi()["paths"])
    paths.update(f"/api{getattr(route, 'path', '')}" for route in websocket_router.routes)

    required = {
        "/api/health",
        "/api/metrics",
        "/api/auth/me",
        "/api/admin/users",
        "/api/projects/{project_id}/access",
        "/api/projects/{project_id}/roles",
        "/api/projects/{project_id}/memberships",
        "/api/projects/{project_id}/approval-policies",
        "/api/projects/{project_id}/approval-policies/{policy_key}",
        "/api/projects/{project_id}/governance-profiles",
        "/api/projects",
        "/api/projects/{project_id}/pi",
        "/api/projects/{project_id}/workflows",
        "/api/projects/{project_id}/workflows/validate",
        "/api/projects/{project_id}/workflows/templates",
        "/api/projects/{project_id}/workflows/templates/{template_id}",
        "/api/projects/{project_id}/workflows/changes",
        "/api/projects/{project_id}/workflows/changes/review",
        "/api/projects/{project_id}/workflows/{workflow_id}/runs",
        "/api/credentials",
        "/api/runs",
        "/api/runs/{run_id}",
        "/api/runs/{run_id}/graph",
        "/api/runs/{run_id}/report",
        "/api/runs/{run_id}/logs",
        "/api/runs/{run_id}/cancel",
        "/api/runs/{run_id}/resume",
        "/api/runs/{run_id}/approve",
        "/api/runs/{run_id}/feedback",
        "/api/runs/{run_id}/override-gate",
        "/api/webhook/gitlab",
        "/api/webhook/github",
        "/api/ws/runs/{run_id}/logs",
    }

    assert required <= paths
