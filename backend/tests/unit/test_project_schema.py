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
        )


def test_clone_url_comparison_ignores_git_suffix_and_host_case() -> None:
    assert _canonical_git_url("https://GITHUB.test/acme/widget.git") == _canonical_git_url(
        "https://github.test/acme/widget"
    )
