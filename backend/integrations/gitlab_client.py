from __future__ import annotations

import asyncio
from typing import Any

import httpx

from backend.services.crypto import SecretRedactor


class GitLabError(RuntimeError):
    def __init__(self, category: str, status_code: int | None = None) -> None:
        suffix = f" (HTTP {status_code})" if status_code else ""
        super().__init__(f"GitLab {category} request failed{suffix}")
        self.category = category
        self.status_code = status_code


class GitLabClient:
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
    ) -> dict[str, Any]:
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
                if not isinstance(data, dict):
                    raise GitLabError(category, response.status_code)
                return data
        finally:
            redactor.clear()
        raise GitLabError(category)

    async def get_project(self, project_id: int, token: str) -> dict[str, Any]:
        return await self.request(
            "GET", f"/projects/{project_id}", token, category="project metadata"
        )

    async def create_merge_request(
        self,
        project_id: int,
        token: str,
        *,
        source_branch: str,
        target_branch: str,
        title: str,
        description: str,
        reviewer_id: int,
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
                "reviewer_ids": [reviewer_id],
                "remove_source_branch": True,
            },
            retry_get=False,
        )

    async def update_merge_request_reviewers(
        self,
        project_id: int,
        mr_iid: int,
        token: str,
        reviewer_id: int,
    ) -> dict[str, Any]:
        return await self.request(
            "PUT",
            f"/projects/{project_id}/merge_requests/{mr_iid}",
            token,
            category="merge request reviewer update",
            json={"reviewer_ids": [reviewer_id]},
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
