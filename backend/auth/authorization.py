from __future__ import annotations

import uuid
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.auth.dependencies import AuthenticatedUser
from backend.db.models import (
    AuthorizationAuditEvent,
    ProjectMembership,
    ProjectMembershipRole,
    ProjectRole,
    ProjectRolePermission,
)
from backend.services.approval_policy_seed import seed_default_approval_policy

PROJECT_VIEW = "project.view"
PROJECT_MANAGE = "project.manage"
MEMBERSHIP_MANAGE = "membership.manage"
ROLE_MANAGE = "role.manage"
POLICY_MANAGE = "policy.manage"
POLICY_VIEW = "policy.view"
WORKFLOW_VIEW = "workflow.view"
WORKFLOW_EDIT = "workflow.edit"
WORKFLOW_PUBLISH = "workflow.publish"
RUN_VIEW = "run.view"
RUN_TRIGGER = "run.trigger"
RUN_CONTROL_OWN = "run.control.own"
RUN_CONTROL_ANY = "run.control.any"
GATE_RESPOND = "gate.respond"
GATE_OVERRIDE = "gate.override"
REPORT_VIEW = "report.view"
AUDIT_VIEW = "audit.view"

PERMISSIONS = {
    PROJECT_VIEW,
    PROJECT_MANAGE,
    MEMBERSHIP_MANAGE,
    ROLE_MANAGE,
    POLICY_MANAGE,
    POLICY_VIEW,
    WORKFLOW_VIEW,
    WORKFLOW_EDIT,
    WORKFLOW_PUBLISH,
    RUN_VIEW,
    RUN_TRIGGER,
    RUN_CONTROL_OWN,
    RUN_CONTROL_ANY,
    GATE_RESPOND,
    GATE_OVERRIDE,
    REPORT_VIEW,
    AUDIT_VIEW,
}

BUILTIN_ROLES: dict[str, tuple[str, str, set[str]]] = {
    "project-admin": (
        "Project Administrator",
        "Manage this project, its access, policies, workflows, and runs.",
        set(PERMISSIONS),
    ),
    "workflow-author": (
        "Workflow Author",
        "Create, edit, validate, and publish workflow definitions.",
        {
            PROJECT_VIEW,
            POLICY_VIEW,
            WORKFLOW_VIEW,
            WORKFLOW_EDIT,
            WORKFLOW_PUBLISH,
            RUN_VIEW,
            REPORT_VIEW,
        },
    ),
    "operator": (
        "Operator",
        "Trigger workflows and control runs they started.",
        {
            PROJECT_VIEW,
            POLICY_VIEW,
            WORKFLOW_VIEW,
            RUN_VIEW,
            RUN_TRIGGER,
            RUN_CONTROL_OWN,
            REPORT_VIEW,
        },
    ),
    "approver": (
        "Approver",
        "Review run context and respond to gates when selected by a policy.",
        {PROJECT_VIEW, POLICY_VIEW, WORKFLOW_VIEW, RUN_VIEW, GATE_RESPOND, REPORT_VIEW},
    ),
    "viewer": (
        "Viewer",
        "View project workflows, runs, logs, and reports.",
        {PROJECT_VIEW, POLICY_VIEW, WORKFLOW_VIEW, RUN_VIEW, REPORT_VIEW},
    ),
}


async def seed_project_roles(
    session: AsyncSession, project_id: uuid.UUID, owner_user_id: uuid.UUID
) -> None:
    roles: dict[str, ProjectRole] = {}
    for key, (name, description, permissions) in BUILTIN_ROLES.items():
        role = ProjectRole(
            project_id=project_id,
            key=key,
            name=name,
            description=description,
            is_builtin=True,
        )
        session.add(role)
        await session.flush()
        roles[key] = role
        session.add_all(
            ProjectRolePermission(role_id=role.id, permission=permission)
            for permission in sorted(permissions)
        )
    membership = ProjectMembership(project_id=project_id, user_id=owner_user_id)
    session.add(membership)
    await session.flush()
    session.add(
        ProjectMembershipRole(membership_id=membership.id, role_id=roles["project-admin"].id)
    )
    await seed_default_approval_policy(session, project_id)


async def project_permissions(
    session: AsyncSession, user: AuthenticatedUser, project_id: uuid.UUID
) -> set[str]:
    if user.is_system_admin:
        return set(PERMISSIONS)
    rows = await session.scalars(
        select(ProjectRolePermission.permission)
        .join(ProjectMembershipRole, ProjectMembershipRole.role_id == ProjectRolePermission.role_id)
        .join(ProjectMembership, ProjectMembership.id == ProjectMembershipRole.membership_id)
        .where(
            ProjectMembership.project_id == project_id,
            ProjectMembership.user_id == user.id,
            ProjectMembership.is_active.is_(True),
        )
    )
    return set(rows)


async def authorize_project(
    session: AsyncSession,
    user: AuthenticatedUser,
    project_id: uuid.UUID,
    permission: str,
) -> None:
    if permission not in PERMISSIONS:
        raise RuntimeError(f"Unknown permission: {permission}")
    if permission not in await project_permissions(session, user, project_id):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "You do not have permission for this project action"
        )


async def accessible_project_ids(
    session: AsyncSession, user: AuthenticatedUser
) -> list[uuid.UUID] | None:
    if user.is_system_admin:
        return None
    return list(
        await session.scalars(
            select(ProjectMembership.project_id).where(
                ProjectMembership.user_id == user.id,
                ProjectMembership.is_active.is_(True),
            )
        )
    )


async def replace_role_permissions(
    session: AsyncSession, role: ProjectRole, permissions: set[str]
) -> None:
    unknown = permissions - PERMISSIONS
    if unknown:
        raise ValueError(f"Unknown permissions: {', '.join(sorted(unknown))}")
    await session.execute(
        delete(ProjectRolePermission).where(ProjectRolePermission.role_id == role.id)
    )
    session.add_all(
        ProjectRolePermission(role_id=role.id, permission=permission)
        for permission in sorted(permissions)
    )


def actor_snapshot(user: AuthenticatedUser) -> dict[str, Any]:
    return {
        "user_id": str(user.id),
        "email": user.email,
        "display_name": user.display_name,
        "provider": user.provider,
        "provider_user_id": user.provider_user_id,
        "provider_username": user.provider_username,
    }


def audit_event(
    user: AuthenticatedUser,
    action: str,
    target_type: str,
    *,
    project_id: uuid.UUID | None = None,
    run_id: uuid.UUID | None = None,
    target_id: str | None = None,
    details: dict[str, Any] | None = None,
) -> AuthorizationAuditEvent:
    return AuthorizationAuditEvent(
        project_id=project_id,
        run_id=run_id,
        actor_user_id=user.id,
        actor_snapshot=actor_snapshot(user),
        action=action,
        target_type=target_type,
        target_id=target_id,
        details=details or {},
    )
