from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.auth.authorization import (
    GATE_RESPOND,
    PROJECT_MANAGE,
    REPORT_VIEW,
    project_permissions,
    seed_project_roles,
)
from backend.auth.dependencies import AuthenticatedUser
from backend.db.models import (
    ApprovalPolicy,
    ApprovalPolicyRequirement,
    ApprovalRequirementRole,
    Project,
    ProjectMembership,
    ProjectMembershipRole,
    ProjectRole,
    ProviderIdentity,
    User,
)
from backend.services.approval_policy_service import (
    ApprovalPolicyService,
    approvals_satisfy,
)


def auth_user(user: User, identity: ProviderIdentity) -> AuthenticatedUser:
    return AuthenticatedUser(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        avatar_url=None,
        provider=identity.provider,
        provider_user_id=identity.provider_user_id,
        provider_username=identity.username,
    )


async def test_seeded_project_admin_has_full_project_control(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    owner = User(email="owner@example.com", display_name="Owner")
    db_session.add(owner)
    await db_session.flush()
    identity = ProviderIdentity(
        user_id=owner.id,
        provider="gitlab",
        provider_user_id="1",
        username="owner",
    )
    project = Project(
        name="Project",
        git_url="https://gitlab.example/group/repo.git",
        provider="gitlab",
        provider_project_id="1",
        provider_project_path="group/repo",
        encrypted_access_token=b"encrypted",
        local_path=str(tmp_path / "project-auth-test"),
        default_branch="main",
        added_by=owner.id,
    )
    db_session.add_all([identity, project])
    await db_session.flush()
    await seed_project_roles(db_session, project.id, owner.id)
    await db_session.commit()

    permissions = await project_permissions(db_session, auth_user(owner, identity), project.id)
    assert {PROJECT_MANAGE, GATE_RESPOND, REPORT_VIEW} <= permissions


async def test_policy_snapshot_resolves_role_members_and_excludes_initiator(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    owner = User(email="owner@example.com", display_name="Owner")
    reviewer = User(email="reviewer@example.com", display_name="Reviewer")
    db_session.add_all([owner, reviewer])
    await db_session.flush()
    owner_identity = ProviderIdentity(
        user_id=owner.id,
        provider="gitlab",
        provider_user_id="1",
        username="owner",
    )
    reviewer_identity = ProviderIdentity(
        user_id=reviewer.id,
        provider="gitlab",
        provider_user_id="2",
        username="reviewer",
    )
    project = Project(
        name="Project",
        git_url="https://gitlab.example/group/repo.git",
        provider="gitlab",
        provider_project_id="2",
        provider_project_path="group/repo",
        encrypted_access_token=b"encrypted",
        local_path=str(tmp_path / "project-policy-test"),
        default_branch="main",
        added_by=owner.id,
    )
    db_session.add_all([owner_identity, reviewer_identity, project])
    await db_session.flush()
    await seed_project_roles(db_session, project.id, owner.id)
    approver_role = await db_session.scalar(
        select(ProjectRole).where(
            ProjectRole.project_id == project.id, ProjectRole.key == "approver"
        )
    )
    assert approver_role is not None
    membership = ProjectMembership(project_id=project.id, user_id=reviewer.id)
    db_session.add(membership)
    await db_session.flush()
    db_session.add(ProjectMembershipRole(membership_id=membership.id, role_id=approver_role.id))
    policy = ApprovalPolicy(
        project_id=project.id,
        key="security-review",
        name="Security review",
        initiator_may_approve=False,
    )
    db_session.add(policy)
    await db_session.flush()
    requirement = ApprovalPolicyRequirement(
        policy_id=policy.id, key="security", name="Security", quorum=1
    )
    db_session.add(requirement)
    await db_session.flush()
    db_session.add(ApprovalRequirementRole(requirement_id=requirement.id, role_id=approver_role.id))
    await db_session.commit()

    _, eligible = await ApprovalPolicyService(db_session).snapshot(
        project, policy.key, triggering_user_id=owner.id
    )
    actors = eligible["requirements"][0]["users"]
    assert [actor["provider_user_id"] for actor in actors] == ["2"]


def test_quorum_supports_distinct_and_overlapping_requirements() -> None:
    eligible = {
        "requirements": [
            {
                "key": "security",
                "quorum": 1,
                "users": [{"provider": "gitlab", "provider_user_id": "1"}],
            },
            {
                "key": "owner",
                "quorum": 1,
                "users": [
                    {"provider": "gitlab", "provider_user_id": "1"},
                    {"provider": "gitlab", "provider_user_id": "2"},
                ],
            },
        ]
    }
    one_actor = [
        {
            "provider_identity": "gitlab:1",
            "requirement_keys": ["security", "owner"],
        }
    ]
    assert approvals_satisfy({"distinct_approvers_across_requirements": False}, eligible, one_actor)
    assert not approvals_satisfy(
        {"distinct_approvers_across_requirements": True}, eligible, one_actor
    )
    two_actors = [
        *one_actor,
        {"provider_identity": "gitlab:2", "requirement_keys": ["owner"]},
    ]
    assert approvals_satisfy({"distinct_approvers_across_requirements": True}, eligible, two_actors)
