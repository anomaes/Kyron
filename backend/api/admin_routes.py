from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import delete, select

from backend.auth.authorization import (
    AUDIT_VIEW,
    MEMBERSHIP_MANAGE,
    PERMISSIONS,
    POLICY_MANAGE,
    POLICY_VIEW,
    ROLE_MANAGE,
    audit_event,
    authorize_project,
    project_permissions,
    replace_role_permissions,
)
from backend.auth.dependencies import CurrentUser, DbSession
from backend.db.models import (
    ApprovalPolicy,
    ApprovalPolicyRequirement,
    ApprovalRequirementRole,
    ApprovalRequirementUser,
    AuthorizationAuditEvent,
    GovernanceProfile,
    Project,
    ProjectMembership,
    ProjectMembershipRole,
    ProjectRole,
    ProjectRolePermission,
    ProviderIdentity,
    User,
)
from backend.schemas.admin import (
    ApprovalPolicyRequest,
    GovernanceProfileRequest,
    MembershipRequest,
    RoleRequest,
    UserAdminUpdate,
)
from backend.services.approval_policy_service import ApprovalPolicyError, ApprovalPolicyService

router = APIRouter(tags=["administration"])


def require_system_admin(user: CurrentUser) -> None:
    if not user.is_system_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "System administrator access is required")


@router.get("/admin/permissions")
async def list_permissions(user: CurrentUser) -> list[str]:
    require_system_admin(user)
    return sorted(PERMISSIONS)


@router.get("/admin/users")
async def list_users(user: CurrentUser, db: DbSession) -> list[dict[str, Any]]:
    require_system_admin(user)
    users = list(await db.scalars(select(User).order_by(User.display_name, User.email)))
    identities = {
        identity.user_id: identity for identity in await db.scalars(select(ProviderIdentity))
    }
    return [
        {
            "id": item.id,
            "email": item.email,
            "display_name": item.display_name,
            "avatar_url": item.avatar_url,
            "is_active": item.is_active,
            "is_system_admin": item.is_system_admin,
            "last_login_at": item.last_login_at,
            "provider": identities[item.id].provider if item.id in identities else None,
            "provider_user_id": identities[item.id].provider_user_id
            if item.id in identities
            else None,
            "provider_username": identities[item.id].username if item.id in identities else None,
        }
        for item in users
    ]


@router.patch("/admin/users/{user_id}")
async def update_user(
    user_id: uuid.UUID, request: UserAdminUpdate, actor: CurrentUser, db: DbSession
) -> dict[str, Any]:
    require_system_admin(actor)
    target = await db.get(User, user_id)
    if target is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User does not exist")
    if target.id == actor.id and (request.is_active is False or request.is_system_admin is False):
        raise HTTPException(
            status.HTTP_409_CONFLICT, "You cannot disable or demote your own account"
        )
    before = {"is_active": target.is_active, "is_system_admin": target.is_system_admin}
    if request.is_active is not None:
        target.is_active = request.is_active
    if request.is_system_admin is not None:
        target.is_system_admin = request.is_system_admin
    db.add(
        audit_event(
            actor,
            "USER_ACCESS_CHANGED",
            "user",
            target_id=str(target.id),
            details={
                "before": before,
                "after": {"is_active": target.is_active, "is_system_admin": target.is_system_admin},
            },
        )
    )
    await db.commit()
    return {
        "id": target.id,
        "is_active": target.is_active,
        "is_system_admin": target.is_system_admin,
    }


@router.get("/projects/{project_id}/access")
async def current_project_access(
    project_id: uuid.UUID, user: CurrentUser, db: DbSession
) -> dict[str, Any]:
    permissions = await project_permissions(db, user, project_id)
    if not permissions:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You are not a member of this project")
    return {"permissions": sorted(permissions), "is_system_admin": user.is_system_admin}


@router.get("/projects/{project_id}/roles")
async def list_roles(
    project_id: uuid.UUID, user: CurrentUser, db: DbSession
) -> list[dict[str, Any]]:
    await authorize_project(db, user, project_id, ROLE_MANAGE)
    roles = list(
        await db.scalars(
            select(ProjectRole)
            .where(ProjectRole.project_id == project_id)
            .order_by(ProjectRole.name)
        )
    )
    result = []
    for role in roles:
        permissions = list(
            await db.scalars(
                select(ProjectRolePermission.permission).where(
                    ProjectRolePermission.role_id == role.id
                )
            )
        )
        result.append({**_model(role), "permissions": sorted(permissions)})
    return result


@router.post("/projects/{project_id}/roles", status_code=status.HTTP_201_CREATED)
async def create_role(
    project_id: uuid.UUID, request: RoleRequest, user: CurrentUser, db: DbSession
) -> dict[str, Any]:
    await authorize_project(db, user, project_id, ROLE_MANAGE)
    if await db.scalar(
        select(ProjectRole.id).where(
            ProjectRole.project_id == project_id, ProjectRole.key == request.key
        )
    ):
        raise HTTPException(status.HTTP_409_CONFLICT, "Role key already exists")
    role = ProjectRole(
        project_id=project_id, key=request.key, name=request.name, description=request.description
    )
    db.add(role)
    await db.flush()
    try:
        await replace_role_permissions(db, role, set(request.permissions))
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    db.add(
        audit_event(
            user,
            "ROLE_CREATED",
            "project_role",
            project_id=project_id,
            target_id=str(role.id),
            details={"key": role.key},
        )
    )
    await db.commit()
    return {**_model(role), "permissions": sorted(set(request.permissions))}


@router.put("/projects/{project_id}/roles/{role_id}")
async def update_role(
    project_id: uuid.UUID,
    role_id: uuid.UUID,
    request: RoleRequest,
    user: CurrentUser,
    db: DbSession,
) -> dict[str, Any]:
    await authorize_project(db, user, project_id, ROLE_MANAGE)
    role = await db.scalar(
        select(ProjectRole).where(ProjectRole.id == role_id, ProjectRole.project_id == project_id)
    )
    if role is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Role does not exist")
    if role.is_builtin:
        raise HTTPException(status.HTTP_409_CONFLICT, "Built-in roles are immutable")
    role.key, role.name, role.description = request.key, request.name, request.description
    try:
        await replace_role_permissions(db, role, set(request.permissions))
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    db.add(
        audit_event(
            user, "ROLE_UPDATED", "project_role", project_id=project_id, target_id=str(role.id)
        )
    )
    await db.commit()
    return {**_model(role), "permissions": sorted(set(request.permissions))}


@router.get("/projects/{project_id}/memberships")
async def list_memberships(
    project_id: uuid.UUID, user: CurrentUser, db: DbSession
) -> list[dict[str, Any]]:
    await authorize_project(db, user, project_id, MEMBERSHIP_MANAGE)
    memberships = list(
        await db.scalars(
            select(ProjectMembership).where(ProjectMembership.project_id == project_id)
        )
    )
    result = []
    for membership in memberships:
        member = await db.get(User, membership.user_id)
        keys = list(
            await db.scalars(
                select(ProjectRole.key)
                .join(ProjectMembershipRole, ProjectMembershipRole.role_id == ProjectRole.id)
                .where(ProjectMembershipRole.membership_id == membership.id)
            )
        )
        result.append(
            {
                **_model(membership),
                "display_name": member.display_name if member else "Unknown",
                "email": member.email if member else "",
                "role_keys": sorted(keys),
            }
        )
    return result


@router.get("/projects/{project_id}/available-users")
async def available_users(
    project_id: uuid.UUID, user: CurrentUser, db: DbSession
) -> list[dict[str, Any]]:
    await authorize_project(db, user, project_id, MEMBERSHIP_MANAGE)
    identities = {
        identity.user_id: identity for identity in await db.scalars(select(ProviderIdentity))
    }
    users = list(
        await db.scalars(
            select(User).where(User.is_active.is_(True)).order_by(User.display_name, User.email)
        )
    )
    return [
        {
            "id": item.id,
            "display_name": item.display_name,
            "email": item.email,
            "provider": identities[item.id].provider if item.id in identities else None,
            "provider_username": identities[item.id].username if item.id in identities else None,
        }
        for item in users
    ]


@router.put("/projects/{project_id}/memberships/{user_id}")
async def put_membership(
    project_id: uuid.UUID,
    user_id: uuid.UUID,
    request: MembershipRequest,
    user: CurrentUser,
    db: DbSession,
) -> dict[str, Any]:
    await authorize_project(db, user, project_id, MEMBERSHIP_MANAGE)
    if request.user_id != user_id or await db.get(User, user_id) is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Invalid membership user")
    roles = (
        list(
            await db.scalars(
                select(ProjectRole).where(
                    ProjectRole.project_id == project_id, ProjectRole.key.in_(request.role_keys)
                )
            )
        )
        if request.role_keys
        else []
    )
    if len(roles) != len(set(request.role_keys)):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "One or more role keys do not exist"
        )
    membership = await db.scalar(
        select(ProjectMembership).where(
            ProjectMembership.project_id == project_id, ProjectMembership.user_id == user_id
        )
    )
    if membership is None:
        membership = ProjectMembership(
            project_id=project_id, user_id=user_id, is_active=request.is_active
        )
        db.add(membership)
        await db.flush()
    else:
        membership.is_active = request.is_active
        await db.execute(
            delete(ProjectMembershipRole).where(
                ProjectMembershipRole.membership_id == membership.id
            )
        )
    db.add_all(
        ProjectMembershipRole(membership_id=membership.id, role_id=role.id) for role in roles
    )
    db.add(
        audit_event(
            user,
            "MEMBERSHIP_CHANGED",
            "project_membership",
            project_id=project_id,
            target_id=str(membership.id),
            details={
                "member_user_id": str(user_id),
                "role_keys": sorted(request.role_keys),
                "is_active": request.is_active,
            },
        )
    )
    await db.commit()
    return {
        "id": membership.id,
        "user_id": user_id,
        "role_keys": sorted(request.role_keys),
        "is_active": membership.is_active,
    }


@router.get("/projects/{project_id}/approval-policies")
async def list_policies(
    project_id: uuid.UUID, user: CurrentUser, db: DbSession
) -> list[dict[str, Any]]:
    await authorize_project(db, user, project_id, POLICY_VIEW)
    policies = list(
        await db.scalars(
            select(ApprovalPolicy)
            .where(ApprovalPolicy.project_id == project_id)
            .order_by(ApprovalPolicy.name)
        )
    )
    return [await _policy_payload(db, policy) for policy in policies]


@router.put("/projects/{project_id}/approval-policies/{policy_key}")
async def put_policy(
    project_id: uuid.UUID,
    policy_key: str,
    request: ApprovalPolicyRequest,
    user: CurrentUser,
    db: DbSession,
) -> dict[str, Any]:
    await authorize_project(db, user, project_id, POLICY_MANAGE)
    if request.key != policy_key:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Policy key mismatch")
    policy = await db.scalar(
        select(ApprovalPolicy).where(
            ApprovalPolicy.project_id == project_id, ApprovalPolicy.key == policy_key
        )
    )
    created = policy is None
    if policy is None:
        policy = ApprovalPolicy(project_id=project_id, key=request.key, name=request.name)
        db.add(policy)
        await db.flush()
    policy.name = request.name
    policy.description = request.description
    policy.enabled = request.enabled
    policy.initiator_may_approve = request.initiator_may_approve
    policy.distinct_approvers_across_requirements = request.distinct_approvers_across_requirements
    policy.eligible_approvers_may_give_feedback = request.eligible_approvers_may_give_feedback
    old_requirement_ids = list(
        await db.scalars(
            select(ApprovalPolicyRequirement.id).where(
                ApprovalPolicyRequirement.policy_id == policy.id
            )
        )
    )
    if old_requirement_ids:
        await db.execute(
            delete(ApprovalPolicyRequirement).where(
                ApprovalPolicyRequirement.policy_id == policy.id
            )
        )
    role_by_key = {
        role.key: role
        for role in await db.scalars(
            select(ProjectRole).where(ProjectRole.project_id == project_id)
        )
    }
    membership_user_ids = set(
        await db.scalars(
            select(ProjectMembership.user_id).where(
                ProjectMembership.project_id == project_id, ProjectMembership.is_active.is_(True)
            )
        )
    )
    for item in request.requirements:
        if not item.role_keys and not item.user_ids and not item.include_triggering_user:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT, f"Requirement {item.key} has no subjects"
            )
        missing_roles = set(item.role_keys) - role_by_key.keys()
        missing_users = set(item.user_ids) - membership_user_ids
        if missing_roles or missing_users:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                f"Requirement {item.key} references unknown or inactive project subjects",
            )
        requirement = ApprovalPolicyRequirement(
            policy_id=policy.id,
            key=item.key,
            name=item.name,
            quorum=item.quorum,
            include_triggering_user=item.include_triggering_user,
        )
        db.add(requirement)
        await db.flush()
        db.add_all(
            ApprovalRequirementRole(requirement_id=requirement.id, role_id=role_by_key[key].id)
            for key in set(item.role_keys)
        )
        db.add_all(
            ApprovalRequirementUser(requirement_id=requirement.id, user_id=subject)
            for subject in set(item.user_ids)
        )
    await db.flush()
    project = await db.get(Project, project_id)
    assert project is not None
    try:
        await ApprovalPolicyService(db).snapshot(
            project, policy.key, triggering_user_id=project.added_by
        )
    except ApprovalPolicyError as exc:
        await db.rollback()
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    db.add(
        audit_event(
            user,
            "POLICY_CREATED" if created else "POLICY_UPDATED",
            "approval_policy",
            project_id=project_id,
            target_id=str(policy.id),
            details={"key": policy.key},
        )
    )
    await db.commit()
    return await _policy_payload(db, policy)


@router.get("/projects/{project_id}/governance-profiles")
async def list_governance(
    project_id: uuid.UUID, user: CurrentUser, db: DbSession
) -> list[dict[str, Any]]:
    await authorize_project(db, user, project_id, POLICY_MANAGE)
    return [
        _model(item)
        for item in await db.scalars(
            select(GovernanceProfile)
            .where(GovernanceProfile.project_id == project_id)
            .order_by(GovernanceProfile.name)
        )
    ]


@router.put("/projects/{project_id}/governance-profiles/{profile_key}")
async def put_governance(
    project_id: uuid.UUID,
    profile_key: str,
    request: GovernanceProfileRequest,
    user: CurrentUser,
    db: DbSession,
) -> dict[str, Any]:
    await authorize_project(db, user, project_id, POLICY_MANAGE)
    if profile_key != request.key:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Profile key mismatch")
    known_policies = set(
        await db.scalars(
            select(ApprovalPolicy.key).where(
                ApprovalPolicy.project_id == project_id, ApprovalPolicy.enabled.is_(True)
            )
        )
    )
    if set(request.required_policy_keys) - known_policies:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "Profile references unknown or disabled policies"
        )
    profile = await db.scalar(
        select(GovernanceProfile).where(
            GovernanceProfile.project_id == project_id, GovernanceProfile.key == profile_key
        )
    )
    if profile is None:
        profile = GovernanceProfile(project_id=project_id, key=request.key, name=request.name)
        db.add(profile)
    profile.name = request.name
    profile.enabled = request.enabled
    profile.applies_to_tags = sorted(set(request.applies_to_tags))
    profile.required_policy_keys = sorted(set(request.required_policy_keys))
    profile.prohibit_self_approval = request.prohibit_self_approval
    profile.min_total_approvals = request.min_total_approvals
    db.add(
        audit_event(
            user,
            "GOVERNANCE_PROFILE_CHANGED",
            "governance_profile",
            project_id=project_id,
            target_id=profile_key,
        )
    )
    await db.commit()
    return _model(profile)


@router.get("/projects/{project_id}/authorization-audit")
async def project_audit(
    project_id: uuid.UUID, user: CurrentUser, db: DbSession
) -> list[dict[str, Any]]:
    await authorize_project(db, user, project_id, AUDIT_VIEW)
    events = list(
        await db.scalars(
            select(AuthorizationAuditEvent)
            .where(AuthorizationAuditEvent.project_id == project_id)
            .order_by(AuthorizationAuditEvent.id.desc())
            .limit(1000)
        )
    )
    return [_model(item) for item in events]


async def _policy_payload(db: DbSession, policy: ApprovalPolicy) -> dict[str, Any]:
    requirements = list(
        await db.scalars(
            select(ApprovalPolicyRequirement)
            .where(ApprovalPolicyRequirement.policy_id == policy.id)
            .order_by(ApprovalPolicyRequirement.key)
        )
    )
    items = []
    for requirement in requirements:
        role_keys = list(
            await db.scalars(
                select(ProjectRole.key)
                .join(ApprovalRequirementRole, ApprovalRequirementRole.role_id == ProjectRole.id)
                .where(ApprovalRequirementRole.requirement_id == requirement.id)
            )
        )
        user_ids = list(
            await db.scalars(
                select(ApprovalRequirementUser.user_id).where(
                    ApprovalRequirementUser.requirement_id == requirement.id
                )
            )
        )
        items.append(
            {
                "key": requirement.key,
                "name": requirement.name,
                "quorum": requirement.quorum,
                "role_keys": sorted(role_keys),
                "user_ids": user_ids,
                "include_triggering_user": requirement.include_triggering_user,
            }
        )
    return {**_model(policy), "requirements": items}


def _model(value: Any) -> dict[str, Any]:
    return {column.name: getattr(value, column.key) for column in value.__table__.columns}
