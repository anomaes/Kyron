import json

import httpx
import pytest

from backend.integrations.code_host import ProviderUser
from backend.integrations.github_client import GitHubClient, GitHubError


async def test_repository_request_uses_bearer_token_and_normalizes_metadata() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer secret-token"
        assert request.url.path == "/repos/acme/widget"
        return httpx.Response(
            200,
            json={
                "id": 123,
                "full_name": "acme/widget",
                "default_branch": "main",
                "clone_url": "https://github.test/acme/widget.git",
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        metadata = await GitHubClient("https://api.github.test", client).get_repository(
            "acme/widget", "secret-token"
        )
    assert metadata.id == "123"
    assert metadata.path == "acme/widget"
    assert metadata.clone_url == "https://github.test/acme/widget.git"


async def test_pull_request_creation_requests_triggering_user_as_reviewer() -> None:
    requests: list[tuple[str, str, dict[str, object]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content or b"{}")
        requests.append((request.method, request.url.path, body))
        if request.url.path.endswith("/pulls"):
            return httpx.Response(
                201,
                json={
                    "number": 17,
                    "html_url": "https://github.test/acme/widget/pull/17",
                    "state": "open",
                },
            )
        return httpx.Response(201, json={"requested_reviewers": [{"login": "alice"}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        change_request = await GitHubClient(
            "https://api.github.test", client
        ).create_change_request(
            "acme/widget",
            "token",
            source_branch="workflow/run",
            target_branch="main",
            title="Run",
            description="Review",
            reviewers=[ProviderUser(id="7", username="alice")],
        )
    assert change_request.number == 17
    assert requests[1] == (
        "POST",
        "/repos/acme/widget/pulls/17/requested_reviewers",
        {"reviewers": ["alice"]},
    )


async def test_submitted_approval_is_dismissed_by_review_id() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "PUT"
        assert request.url.path.endswith("/pulls/17/reviews/99/dismissals")
        return httpx.Response(200, json={"id": 99, "state": "DISMISSED"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await GitHubClient("https://api.github.test", client).consume_approval(
            "acme/widget",
            17,
            "token",
            ProviderUser(id="7", username="alice"),
            "99",
        )


async def test_frontend_approval_dismisses_active_review_from_triggering_user() -> None:
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        if request.method == "GET":
            return httpx.Response(
                200,
                json=[
                    {"id": 70, "state": "APPROVED", "user": {"id": 7, "login": "alice"}},
                    {"id": 71, "state": "APPROVED", "user": {"id": 8, "login": "bob"}},
                ],
            )
        return httpx.Response(200, json={"id": 70, "state": "DISMISSED"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await GitHubClient("https://api.github.test", client).consume_approval(
            "acme/widget", 17, "token", ProviderUser(id="7", username="alice")
        )
    assert paths[-1].endswith("/reviews/70/dismissals")
    assert not any(path.endswith("/reviews/71/dismissals") for path in paths)


async def test_github_error_does_not_expose_token_or_response() -> None:
    transport = httpx.MockTransport(lambda _: httpx.Response(401, text="secret-token"))
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(GitHubError) as captured:
            await GitHubClient("https://api.github.test", client).get_repository(
                "acme/widget", "secret-token"
            )
    assert "secret-token" not in str(captured.value)
