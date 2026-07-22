import httpx
import pytest

from backend.integrations.gitlab_client import GitLabClient, GitLabError


async def test_project_request_uses_private_token_without_exposing_it() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["PRIVATE-TOKEN"] == "secret-token"
        return httpx.Response(
            200,
            json={"id": 123, "default_branch": "main", "path_with_namespace": "g/r"},
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        gitlab = GitLabClient("https://gitlab.example", client)
        project = await gitlab.get_project(123, "secret-token")
    assert project["default_branch"] == "main"


async def test_gitlab_error_is_sanitized() -> None:
    transport = httpx.MockTransport(lambda _: httpx.Response(401, text="secret-token"))
    async with httpx.AsyncClient(transport=transport) as client:
        gitlab = GitLabClient("https://gitlab.example", client)
        with pytest.raises(GitLabError) as captured:
            await gitlab.get_project(123, "secret-token")
    assert "secret-token" not in str(captured.value)


async def test_find_merge_request_uses_run_branch_and_target() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["state"] == "opened"
        assert request.url.params["source_branch"] == "workflow/run"
        assert request.url.params["target_branch"] == "main"
        return httpx.Response(
            200,
            json=[
                {
                    "iid": 19,
                    "web_url": "https://gitlab.example/group/repo/-/merge_requests/19",
                    "state": "opened",
                }
            ],
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        change_request = await GitLabClient("https://gitlab.example", client).find_change_request(
            "123",
            "token",
            source_branch="workflow/run",
            target_branch="main",
        )
    assert change_request is not None
    assert change_request.number == 19
