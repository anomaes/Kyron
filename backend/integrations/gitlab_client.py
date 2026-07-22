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


class GitLabError(CodeHostError):
    def __init__(self, category: str, status_code: int | None = None) -> None:
        super().__init__("gitlab", category, status_code)


class GitLabClient:
    provider = "gitlab"

    def __init__(self, base_url: str, client: httpx.AsyncClient | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self._owned_client = client is None
        self.client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(connect=10, read=30, write=30, pool=10)
        )

    async def close(self) -> None:
        if self._owned_client:
            await self.client.aclose()

    async def _request_data(
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
                        f"{self.base_url}/api/v4{path}",
                        headers={"PRIVATE-TOKEN": token},
                        json=json,
                    )
                except httpx.RequestError as exc:
                    if attempt + 1 == attempts:
                        raise GitLabError(category) from exc
                    await asyncio.sleep(0.25 * 2**attempt)
                    continue
                if response.status_code in {502, 503, 504} and attempt + 1 < attempts:
                    await asyncio.sleep(0.25 * 2**attempt)
                    continue
                if response.is_error:
                    raise GitLabError(category, response.status_code)
                if response.status_code == 204 or not response.content:
                    return {}
                data = response.json()
                if not isinstance(data, (dict, list)):
                    raise GitLabError(category, response.status_code)
                return data
        finally:
            redactor.clear()
        raise GitLabError(category)

    async def request(
        self,
        method: str,
        path: str,
        token: str,
        *,
        category: str,
        json: dict[str, Any] | None = None,
        retry_get: bool = True,
    ) -> dict[str, Any]:
        data = await self._request_data(
            method, path, token, category=category, json=json, retry_get=retry_get
        )
        if not isinstance(data, dict):
            raise GitLabError(category)
        return data

    async def request_list(
        self,
        method: str,
        path: str,
        token: str,
        *,
        category: str,
    ) -> list[dict[str, Any]]:
        data = await self._request_data(method, path, token, category=category)
        if not isinstance(data, list):
            raise GitLabError(category)
        return data

    async def get_repository(self, repository: str, token: str) -> RepositoryMetadata:
        data = await self.request(
            "GET", f"/projects/{quote(repository, safe='')}", token, category="project metadata"
        )
        return RepositoryMetadata(
            id=str(data["id"]),
            path=str(data["path_with_namespace"]),
            default_branch=str(data.get("default_branch") or "main"),
            clone_url=str(data.get("http_url_to_repo") or ""),
        )

    async def get_project(self, project_id: int, token: str) -> dict[str, Any]:
        metadata = await self.get_repository(str(project_id), token)
        return {
            "id": int(metadata.id),
            "path_with_namespace": metadata.path,
            "default_branch": metadata.default_branch,
            "http_url_to_repo": metadata.clone_url,
        }

    async def create_merge_request(
        self,
        project_id: int,
        token: str,
        *,
        source_branch: str,
        target_branch: str,
        title: str,
        description: str,
        reviewer_ids: list[int],
    ) -> dict[str, Any]:
        return await self.request(
            "POST",
            f"/projects/{project_id}/merge_requests",
            token,
            category="merge request creation",
            json={
                "source_branch": source_branch,
                "target_branch": target_branch,
                "title": title,
                "description": description,
                "reviewer_ids": reviewer_ids,
                "remove_source_branch": True,
            },
            retry_get=False,
        )

    async def update_merge_request_reviewers(
        self,
        project_id: int,
        mr_iid: int,
        token: str,
        reviewer_ids: list[int],
    ) -> dict[str, Any]:
        return await self.request(
            "PUT",
            f"/projects/{project_id}/merge_requests/{mr_iid}",
            token,
            category="merge request reviewer update",
            json={"reviewer_ids": reviewer_ids},
            retry_get=False,
        )

    async def get_merge_request(self, project_id: int, mr_iid: int, token: str) -> dict[str, Any]:
        return await self.request(
            "GET",
            f"/projects/{project_id}/merge_requests/{mr_iid}",
            token,
            category="merge request status",
        )

    async def post_note(
        self, project_id: int, mr_iid: int, token: str, body: str
    ) -> dict[str, Any]:
        return await self.request(
            "POST",
            f"/projects/{project_id}/merge_requests/{mr_iid}/notes",
            token,
            category="merge request note",
            json={"body": body},
            retry_get=False,
        )

    async def reset_approvals(self, project_id: int, mr_iid: int, token: str) -> None:
        await self.request(
            "PUT",
            f"/projects/{project_id}/merge_requests/{mr_iid}/reset_approvals",
            token,
            category="approval reset",
            retry_get=False,
        )

    async def wait_for_approval_sync(
        self,
        project_id: int,
        mr_iid: int,
        token: str,
        *,
        timeout_seconds: float = 20,
    ) -> None:
        deadline = asyncio.get_running_loop().time() + timeout_seconds
        while True:
            merge_request = await self.get_merge_request(project_id, mr_iid, token)
            if merge_request.get("detailed_merge_status") not in {
                "checking",
                "approvals_syncing",
            }:
                return
            if asyncio.get_running_loop().time() >= deadline:
                raise GitLabError("approval synchronization")
            await asyncio.sleep(0.5)

    async def create_change_request(
        self,
        repository: str,
        token: str,
        *,
        source_branch: str,
        target_branch: str,
        title: str,
        description: str,
        reviewers: list[ProviderUser],
    ) -> ChangeRequest:
        data = await self.create_merge_request(
            int(repository),
            token,
            source_branch=source_branch,
            target_branch=target_branch,
            title=title,
            description=description,
            reviewer_ids=sorted({int(reviewer.id) for reviewer in reviewers}),
        )
        return ChangeRequest(
            number=int(data["iid"]), url=str(data["web_url"]), state=str(data["state"])
        )

    async def find_change_request(
        self,
        repository: str,
        token: str,
        *,
        source_branch: str,
        target_branch: str,
    ) -> ChangeRequest | None:
        query = (
            f"state=opened&source_branch={quote(source_branch, safe='')}"
            f"&target_branch={quote(target_branch, safe='')}"
        )
        rows = await self.request_list(
            "GET",
            f"/projects/{quote(repository, safe='')}/merge_requests?{query}",
            token,
            category="merge request lookup",
        )
        if not rows:
            return None
        row = rows[0]
        return ChangeRequest(
            number=int(row["iid"]), url=str(row.get("web_url") or ""), state=str(row["state"])
        )

    async def update_change_request_reviewers(
        self,
        repository: str,
        number: int,
        token: str,
        reviewers: list[ProviderUser],
    ) -> None:
        await self.update_merge_request_reviewers(
            int(repository), number, token, sorted({int(reviewer.id) for reviewer in reviewers})
        )

    async def get_change_request(self, repository: str, number: int, token: str) -> ChangeRequest:
        data = await self.get_merge_request(int(repository), number, token)
        return ChangeRequest(
            number=int(data["iid"]),
            url=str(data.get("web_url") or ""),
            state=str(data["state"]),
        )

    async def post_comment(
        self, repository: str, number: int, token: str, body: str
    ) -> ProviderComment:
        data = await self.post_note(int(repository), number, token, body)
        return ProviderComment(id=str(data["id"]))

    async def consume_approval(
        self,
        repository: str,
        number: int,
        token: str,
        reviewer: ProviderUser,
        review_id: str | None = None,
    ) -> None:
        del reviewer, review_id
        await self.wait_for_approval_sync(int(repository), number, token)
        await self.reset_approvals(int(repository), number, token)
