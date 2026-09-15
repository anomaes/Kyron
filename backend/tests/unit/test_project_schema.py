import pytest
from pydantic import ValidationError

from backend.schemas.project import ProjectCreate
from backend.services.project_service import _canonical_git_url


def test_project_clone_url_rejects_embedded_credentials() -> None:
    with pytest.raises(ValidationError, match="Authenticated Git URLs"):
        ProjectCreate(
            name="Widget",
            provider="github",
            provider_project="acme/widget",
            git_url="https://token@github.test/acme/widget.git",
            access_token="separate-token",
            webhook_secret="a-webhook-secret-with-enough-entropy",
        )


def test_clone_url_comparison_ignores_git_suffix_and_host_case() -> None:
    assert _canonical_git_url("https://GITHUB.test/acme/widget.git") == _canonical_git_url(
        "https://github.test/acme/widget"
    )


def test_project_accepts_pi_defaults() -> None:
    project = ProjectCreate(
        name="Widget",
        provider="github",
        provider_project="acme/widget",
        git_url="https://github.test/acme/widget.git",
        access_token="separate-token",
        webhook_secret="a-webhook-secret-with-enough-entropy",
        pi={
            "provider": "anthropic",
            "model": "anthropic/claude-sonnet-4-5",
            "skill": ".agents/skills/implementation/SKILL.md",
        },
    )
    assert project.pi.model == "anthropic/claude-sonnet-4-5"


def test_project_requires_a_nontrivial_webhook_secret() -> None:
    with pytest.raises(ValidationError, match="webhook_secret"):
        ProjectCreate(
            name="Widget",
            provider="github",
            provider_project="acme/widget",
            git_url="https://github.test/acme/widget.git",
            access_token="separate-token",
            webhook_secret="too-short",
        )


def test_github_project_rejects_gitlab_signing_secret() -> None:
    with pytest.raises(ValidationError, match="only for GitLab"):
        ProjectCreate(
            name="Widget",
            provider="github",
            provider_project="acme/widget",
            git_url="https://github.test/acme/widget.git",
            access_token="separate-token",
            webhook_secret="a-webhook-secret-with-enough-entropy",
            webhook_signing_secret="a-gitlab-only-signing-secret",
        )
