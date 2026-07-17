from __future__ import annotations

import asyncio
from typing import Any
from urllib.parse import quote

import httpx

from backend.integrations.code_host import (
    ChangeRequest,
    CodeHostError,
    ProviderComment,
    ProviderUser,
    RepositoryMetadata,
)
from backend.services.crypto import SecretRedactor


class GitHubError(CodeHostError):
    def __init__(self, category: str, status_code: int | None = None) -> None:
        super().__init__("github", category, status_code)


class GitHubClient:
    provider = "github"

    def __init__(self, base_url: str, client: httpx.AsyncClient | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self._owned_client = client is None
        self.client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(connect=10, read=30, write=30, pool=10)
        )

    async def close(self) -> None:
        if self._owned_client:
            await self.client.aclose()

    async def request(
        self,
        method: str,
        path: str,
        token: str,
        *,
        category: str,
        json: dict[str, Any] | None = None,
        retry_get: bool = True,
    ) -> dict[str, Any] | list[dict[str, Any]]:
        redactor = SecretRedactor([token])
        attempts = 3 if method == "GET" and retry_get else 1
        try:
            for attempt in range(attempts):
                try:
                    response = await self.client.request(
                        method,
                        f"{self.base_url}{path}",
                        headers={
                            "Authorization": f"Bearer {token}",
                            "Accept": "application/vnd.github+json",
                            "X-GitHub-Api-Version": "2022-11-28",
                        },
                        json=json,
                    )
                except httpx.RequestError as exc:
                    if attempt + 1 == attempts:
                        raise GitHubError(category) from exc
                    await asyncio.sleep(0.25 * 2**attempt)
                    continue
                if response.status_code in {502, 503, 504} and attempt + 1 < attempts:
                    await asyncio.sleep(0.25 * 2**attempt)
                    continue
                if response.is_error:
                    raise GitHubError(category, response.status_code)
                if response.status_code == 204 or not response.content:
                    return {}
                data = response.json()
                if not isinstance(data, (dict, list)):
                    raise GitHubError(category, response.status_code)
                return data
        finally:
            redactor.clear()
        raise GitHubError(category)

    @staticmethod
    def _repository_path(repository: str) -> str:
        parts = repository.split("/")
        if len(parts) != 2 or not all(parts):
            raise ValueError("GitHub repository must use owner/repository format")
        return "/".join(quote(part, safe="") for part in parts)

    async def get_repository(self, repository: str, token: str) -> RepositoryMetadata:
        data = await self.request(
            "GET",
            f"/repos/{self._repository_path(repository)}",
            token,
            category="repository metadata",
        )
        assert isinstance(data, dict)
        return RepositoryMetadata(
            id=str(data["id"]),
            path=str(data["full_name"]),
            default_branch=str(data.get("default_branch") or "main"),
            clone_url=str(data.get("clone_url") or ""),
        )

    async def create_change_request(
        self,
        repository: str,
        token: str,
        *,
        source_branch: str,
        target_branch: str,
        title: str,
        description: str,
        reviewer: ProviderUser,
    ) -> ChangeRequest:
        path = self._repository_path(repository)
        data = await self.request(
            "POST",
            f"/repos/{path}/pulls",
            token,
            category="pull request creation",
            json={
                "head": source_branch,
                "base": target_branch,
                "title": title,
                "body": description,
                "maintainer_can_modify": True,
            },
            retry_get=False,
        )
        assert isinstance(data, dict)
        number = int(data["number"])
        await self.update_change_request_reviewer(repository, number, token, reviewer)
        return ChangeRequest(number=number, url=str(data["html_url"]), state=str(data["state"]))

    async def update_change_request_reviewer(
        self,
        repository: str,
        number: int,
        token: str,
        reviewer: ProviderUser,
    ) -> None:
        await self.request(
            "POST",
            f"/repos/{self._repository_path(repository)}/pulls/{number}/requested_reviewers",
            token,
            category="pull request reviewer update",
            json={"reviewers": [reviewer.username]},
            retry_get=False,
        )

    async def get_change_request(
        self, repository: str, number: int, token: str
    ) -> ChangeRequest:
        data = await self.request(
            "GET",
            f"/repos/{self._repository_path(repository)}/pulls/{number}",
            token,
            category="pull request status",
        )
        assert isinstance(data, dict)
        state = "merged" if data.get("merged") is True else str(data["state"])
        return ChangeRequest(number=number, url=str(data["html_url"]), state=state)

    async def post_comment(
        self, repository: str, number: int, token: str, body: str
    ) -> ProviderComment:
        data = await self.request(
            "POST",
            f"/repos/{self._repository_path(repository)}/issues/{number}/comments",
            token,
            category="pull request comment",
            json={"body": body},
            retry_get=False,
        )
        assert isinstance(data, dict)
        return ProviderComment(id=str(data["id"]))

    async def consume_approval(
        self,
        repository: str,
        number: int,
        token: str,
        reviewer: ProviderUser,
        review_id: str | None = None,
    ) -> None:
        review_ids = [review_id] if review_id else await self._active_review_ids(
            repository, number, token, reviewer
        )
        for active_review_id in review_ids:
            if active_review_id is None:
                continue
            await self.request(
                "PUT",
                (
                    f"/repos/{self._repository_path(repository)}/pulls/{number}/reviews/"
                    f"{quote(active_review_id, safe='')}/dismissals"
                ),
                token,
                category="approval dismissal",
                json={"message": "Intermediate Kyron approval consumed; fresh approval required."},
                retry_get=False,
            )

    async def _active_review_ids(
        self,
        repository: str,
        number: int,
        token: str,
        reviewer: ProviderUser,
    ) -> list[str]:
        data = await self.request(
            "GET",
            f"/repos/{self._repository_path(repository)}/pulls/{number}/reviews",
            token,
            category="pull request reviews",
        )
        assert isinstance(data, list)
        latest_by_user: dict[str, dict[str, Any]] = {}
        for review in data:
            user = review.get("user") or {}
            user_id = str(user.get("id") or "")
            login = str(user.get("login") or "")
            if user_id == reviewer.id or login.casefold() == reviewer.username.casefold():
                latest_by_user[user_id or login.casefold()] = review
        return [
            str(review["id"])
            for review in latest_by_user.values()
            if str(review.get("state") or "").upper() == "APPROVED"
        ]
