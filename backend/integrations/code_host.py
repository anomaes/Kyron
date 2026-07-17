from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Protocol

from backend.config import Settings

SUPPORTED_PROVIDERS = frozenset({"gitlab", "github"})


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
        self, provider: str, category: str, status_code: int | None = None
    ) -> None:
        suffix = f" (HTTP {status_code})" if status_code else ""
        super().__init__(f"{provider_display_name(provider)} {category} request failed{suffix}")
        self.provider = provider
        self.category = category
        self.status_code = status_code


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


@dataclass(frozen=True, slots=True)
class ProviderComment:
    id: str


class CodeHostClient(Protocol):
    provider: str

    async def close(self) -> None: ...

    async def get_repository(
        self, repository: str, token: str
    ) -> RepositoryMetadata: ...

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
    ) -> ChangeRequest: ...

    async def update_change_request_reviewer(
        self,
        repository: str,
        number: int,
        token: str,
        reviewer: ProviderUser,
    ) -> None: ...

    async def get_change_request(
        self, repository: str, number: int, token: str
    ) -> ChangeRequest: ...

    async def post_comment(
        self, repository: str, number: int, token: str, body: str
    ) -> ProviderComment: ...

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
