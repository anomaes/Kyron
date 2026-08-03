from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Protocol

from backend.config import Settings

SUPPORTED_PROVIDERS = frozenset({"gitlab", "github"})
CODE_HOST_ERROR_DETAIL_LIMIT = 2000


def provider_display_name(provider: str) -> str:
    if provider == "gitlab":
        return "GitLab"
    if provider == "github":
        return "GitHub"
    raise ValueError(f"Unsupported code-host provider: {provider}")


def git_username(provider: str) -> str:
    if provider == "github":
        return "x-access-token"
    if provider == "gitlab":
        return "oauth2"
    raise ValueError(f"Unsupported code-host provider: {provider}")


def repository_locator(provider: str, project_id: str, project_path: str) -> str:
    if provider == "gitlab":
        return project_id
    if provider == "github":
        return project_path
    raise ValueError(f"Unsupported code-host provider: {provider}")


class CodeHostError(RuntimeError):
    def __init__(
        self,
        provider: str,
        category: str,
        status_code: int | None = None,
        *,
        detail: str | None = None,
    ) -> None:
        suffix = f" (HTTP {status_code})" if status_code else ""
        bounded_detail = detail.strip() if detail else None
        if bounded_detail and len(bounded_detail) > CODE_HOST_ERROR_DETAIL_LIMIT:
            bounded_detail = (
                f"{bounded_detail[:CODE_HOST_ERROR_DETAIL_LIMIT]}… [response truncated]"
            )
        detail_suffix = f": {bounded_detail}" if bounded_detail else ""
        super().__init__(
            f"{provider_display_name(provider)} {category} request failed"
            f"{suffix}{detail_suffix}"
        )
        self.provider = provider
        self.category = category
        self.status_code = status_code
        self.detail = bounded_detail


@dataclass(frozen=True, slots=True)
class ProviderUser:
    id: str
    username: str


@dataclass(frozen=True, slots=True)
class RepositoryMetadata:
    id: str
    path: str
    default_branch: str
    clone_url: str


@dataclass(frozen=True, slots=True)
class ChangeRequest:
    number: int
    url: str
    state: str
    source_branch: str | None = None
    target_branch: str | None = None
    head_sha: str | None = None
    target_sha: str | None = None


@dataclass(frozen=True, slots=True)
class ProviderComment:
    id: str


class CodeHostClient(Protocol):
    provider: str

    async def close(self) -> None: ...

    async def get_repository(self, repository: str, token: str) -> RepositoryMetadata: ...

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
    ) -> ChangeRequest: ...

    async def find_change_request(
        self,
        repository: str,
        token: str,
        *,
        source_branch: str,
        target_branch: str,
    ) -> ChangeRequest | None: ...

    async def update_change_request_reviewers(
        self,
        repository: str,
        number: int,
        token: str,
        reviewers: list[ProviderUser],
    ) -> None: ...

    async def get_change_request(
        self, repository: str, number: int, token: str
    ) -> ChangeRequest: ...

    async def post_comment(
        self, repository: str, number: int, token: str, body: str
    ) -> ProviderComment: ...

    async def publish_commit_status(
        self,
        repository: str,
        commit_sha: str,
        token: str,
        *,
        state: str,
        description: str,
        target_url: str,
    ) -> None: ...

    async def consume_approval(
        self,
        repository: str,
        number: int,
        token: str,
        reviewer: ProviderUser,
        review_id: str | None = None,
    ) -> None: ...


def create_code_host_client(provider: str, settings: Settings) -> CodeHostClient:
    if provider == "gitlab":
        from backend.integrations.gitlab_client import GitLabClient

        return GitLabClient(str(settings.GITLAB_URL))
    if provider == "github":
        from backend.integrations.github_client import GitHubClient

        return GitHubClient(str(settings.GITHUB_API_URL))
    raise ValueError(f"Unsupported code-host provider: {provider}")


@asynccontextmanager
async def code_host_client(provider: str, settings: Settings) -> AsyncIterator[CodeHostClient]:
    client = create_code_host_client(provider, settings)
    try:
        yield client
    finally:
        await client.close()
