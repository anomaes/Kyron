from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.approval_policy_defaults import (
    DEFAULT_APPROVAL_POLICY_DESCRIPTION,
    DEFAULT_APPROVAL_POLICY_KEY,
    DEFAULT_APPROVAL_POLICY_NAME,
    DEFAULT_APPROVAL_REQUIREMENT_KEY,
    DEFAULT_APPROVAL_REQUIREMENT_NAME,
)
from backend.db.models import ApprovalPolicy, ApprovalPolicyRequirement


async def seed_default_approval_policy(
    session: AsyncSession, project_id: uuid.UUID
) -> ApprovalPolicy:
    existing = await session.scalar(
        select(ApprovalPolicy).where(
            ApprovalPolicy.project_id == project_id,
            ApprovalPolicy.key == DEFAULT_APPROVAL_POLICY_KEY,
        )
    )
    if existing is not None:
        return existing
    policy = ApprovalPolicy(
        project_id=project_id,
        key=DEFAULT_APPROVAL_POLICY_KEY,
        name=DEFAULT_APPROVAL_POLICY_NAME,
        description=DEFAULT_APPROVAL_POLICY_DESCRIPTION,
        enabled=True,
        initiator_may_approve=True,
        distinct_approvers_across_requirements=True,
        eligible_approvers_may_give_feedback=True,
    )
    session.add(policy)
    await session.flush()
    session.add(
        ApprovalPolicyRequirement(
            policy_id=policy.id,
            key=DEFAULT_APPROVAL_REQUIREMENT_KEY,
            name=DEFAULT_APPROVAL_REQUIREMENT_NAME,
            quorum=1,
            include_triggering_user=True,
        )
    )
    await session.flush()
    return policy
