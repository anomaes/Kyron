from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.auth.authorization import GATE_RESPOND
from backend.db.models import (
    ApprovalPolicy,
    ApprovalPolicyRequirement,
    ApprovalRequirementRole,
    ApprovalRequirementUser,
    GovernanceProfile,
    Project,
    ProjectMembership,
    ProjectMembershipRole,
    ProjectRolePermission,
    ProviderIdentity,
    User,
)
from backend.schemas.workflow import (
    HumanFeedbackNode,
    ReviewLoopNode,
    WorkflowBundle,
    WorkflowDefinition,
)


class ApprovalPolicyError(ValueError):
    pass


class ApprovalPolicyService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def snapshot(
        self,
        project: Project,
        policy_key: str,
        *,
        triggering_user_id: uuid.UUID,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        policy = await self.session.scalar(
            select(ApprovalPolicy).where(
                ApprovalPolicy.project_id == project.id,
                ApprovalPolicy.key == policy_key,
                ApprovalPolicy.enabled.is_(True),
            )
        )
        if policy is None:
            raise ApprovalPolicyError(
                f"Approval policy '{policy_key}' does not exist or is disabled"
            )
        requirements = list(
            await self.session.scalars(
                select(ApprovalPolicyRequirement)
                .where(ApprovalPolicyRequirement.policy_id == policy.id)
                .order_by(ApprovalPolicyRequirement.key)
            )
        )
        if not requirements:
            raise ApprovalPolicyError(f"Approval policy '{policy_key}' has no requirements")

        eligible_requirements: list[dict[str, Any]] = []
        for requirement in requirements:
            role_ids = list(
                await self.session.scalars(
                    select(ApprovalRequirementRole.role_id).where(
                        ApprovalRequirementRole.requirement_id == requirement.id
                    )
                )
            )
            named_user_ids = set(
                await self.session.scalars(
                    select(ApprovalRequirementUser.user_id).where(
                        ApprovalRequirementUser.requirement_id == requirement.id
                    )
                )
            )
            if role_ids:
                named_user_ids.update(
                    await self.session.scalars(
                        select(ProjectMembership.user_id)
                        .join(
                            ProjectMembershipRole,
                            ProjectMembershipRole.membership_id == ProjectMembership.id,
                        )
                        .where(
                            ProjectMembership.project_id == project.id,
                            ProjectMembership.is_active.is_(True),
                            ProjectMembershipRole.role_id.in_(role_ids),
                        )
                    )
                )
            users = await self._eligible_users(project, named_user_ids)
            if not policy.initiator_may_approve:
                users = [item for item in users if item[0].id != triggering_user_id]
            actors = [self._actor(user, identity) for user, identity in users]
            if len(actors) < requirement.quorum:
                raise ApprovalPolicyError(
                    f"Approval policy '{policy_key}' requirement '{requirement.name}' needs "
                    f"{requirement.quorum} eligible approvers but has {len(actors)}"
                )
            eligible_requirements.append(
                {
                    "key": requirement.key,
                    "name": requirement.name,
                    "quorum": requirement.quorum,
                    "users": actors,
                }
            )

        if policy.distinct_approvers_across_requirements and not _requirements_satisfiable(
            eligible_requirements
        ):
            raise ApprovalPolicyError(
                f"Approval policy '{policy_key}' cannot satisfy its distinct-approver requirements"
            )
        policy_snapshot = {
            "key": policy.key,
            "name": policy.name,
            "description": policy.description,
            "initiator_may_approve": policy.initiator_may_approve,
            "distinct_approvers_across_requirements": policy.distinct_approvers_across_requirements,
            "eligible_approvers_may_give_feedback": policy.eligible_approvers_may_give_feedback,
            "requirements": [
                {"key": item["key"], "name": item["name"], "quorum": item["quorum"]}
                for item in eligible_requirements
            ],
        }
        return policy_snapshot, {"requirements": eligible_requirements}

    async def validate_bundle(self, project: Project, bundle: WorkflowBundle) -> None:
        policy_keys = {
            node.config.approval_policy
            for workflow in bundle.workflows.values()
            for node in workflow.nodes
            if isinstance(node, (HumanFeedbackNode, ReviewLoopNode))
        }
        if policy_keys:
            known = set(
                await self.session.scalars(
                    select(ApprovalPolicy.key).where(
                        ApprovalPolicy.project_id == project.id,
                        ApprovalPolicy.enabled.is_(True),
                        ApprovalPolicy.key.in_(policy_keys),
                    )
                )
            )
            missing = policy_keys - known
            if missing:
                raise ApprovalPolicyError(
                    f"Unknown or disabled approval policies: {', '.join(sorted(missing))}"
                )
        root = bundle.workflows[bundle.root_workflow_id]
        profiles = list(
            await self.session.scalars(
                select(GovernanceProfile).where(
                    GovernanceProfile.project_id == project.id,
                    GovernanceProfile.enabled.is_(True),
                )
            )
        )
        for profile in profiles:
            if profile.applies_to_tags and not set(profile.applies_to_tags).intersection(root.tags):
                continue
            missing = set(profile.required_policy_keys) - policy_keys
            if missing:
                raise ApprovalPolicyError(
                    f"Governance profile '{profile.name}' requires approval policies: "
                    f"{', '.join(sorted(missing))}"
                )
            selected = list(
                await self.session.scalars(
                    select(ApprovalPolicy).where(
                        ApprovalPolicy.project_id == project.id,
                        ApprovalPolicy.key.in_(policy_keys or {"__none__"}),
                    )
                )
            )
            if profile.prohibit_self_approval and any(
                policy.initiator_may_approve for policy in selected
            ):
                raise ApprovalPolicyError(
                    f"Governance profile '{profile.name}' prohibits initiator approval"
                )
            total = 0
            for policy in selected:
                total += sum(
                    await self.session.scalars(
                        select(ApprovalPolicyRequirement.quorum).where(
                            ApprovalPolicyRequirement.policy_id == policy.id
                        )
                    )
                )
            if total < profile.min_total_approvals:
                raise ApprovalPolicyError(
                    f"Governance profile '{profile.name}' requires at least "
                    f"{profile.min_total_approvals} approvals"
                )

    async def validate_definition(self, project: Project, workflow: WorkflowDefinition) -> None:
        await self.validate_bundle(
            project,
            WorkflowBundle(
                base_commit_sha="0" * 40,
                root_workflow_id=workflow.id,
                workflows={workflow.id: workflow},
                reference_graph={workflow.id: []},
            ),
        )

    async def _eligible_users(
        self, project: Project, user_ids: set[uuid.UUID]
    ) -> list[tuple[User, ProviderIdentity]]:
        if not user_ids:
            return []
        rows = await self.session.execute(
            select(User, ProviderIdentity)
            .join(ProviderIdentity, ProviderIdentity.user_id == User.id)
            .join(ProjectMembership, ProjectMembership.user_id == User.id)
            .where(
                User.id.in_(user_ids),
                User.is_active.is_(True),
                ProjectMembership.project_id == project.id,
                ProjectMembership.is_active.is_(True),
                ProviderIdentity.provider == project.provider,
            )
        )
        result: list[tuple[User, ProviderIdentity]] = []
        for user, identity in rows:
            if user.is_system_admin or await self._has_gate_permission(project.id, user.id):
                result.append((user, identity))
        return result

    async def _has_gate_permission(self, project_id: uuid.UUID, user_id: uuid.UUID) -> bool:
        return (
            await self.session.scalar(
                select(ProjectRolePermission.id)
                .join(
                    ProjectMembershipRole,
                    ProjectMembershipRole.role_id == ProjectRolePermission.role_id,
                )
                .join(
                    ProjectMembership, ProjectMembership.id == ProjectMembershipRole.membership_id
                )
                .where(
                    ProjectMembership.project_id == project_id,
                    ProjectMembership.user_id == user_id,
                    ProjectMembership.is_active.is_(True),
                    ProjectRolePermission.permission == GATE_RESPOND,
                )
                .limit(1)
            )
            is not None
        )

    @staticmethod
    def _actor(user: User, identity: ProviderIdentity) -> dict[str, Any]:
        return {
            "user_id": str(user.id),
            "display_name": user.display_name,
            "email": user.email,
            "provider": identity.provider,
            "provider_user_id": identity.provider_user_id,
            "provider_username": identity.username,
        }


def actor_requirement_keys(
    eligible_snapshot: dict[str, Any], provider: str, provider_user_id: str
) -> list[str]:
    return [
        str(requirement["key"])
        for requirement in eligible_snapshot.get("requirements", [])
        if any(
            actor.get("provider") == provider and actor.get("provider_user_id") == provider_user_id
            for actor in requirement.get("users", [])
        )
    ]


def approvals_satisfy(
    policy_snapshot: dict[str, Any],
    eligible_snapshot: dict[str, Any],
    approvals: list[dict[str, Any]],
) -> bool:
    requirements = eligible_snapshot.get("requirements", [])
    if not policy_snapshot.get("distinct_approvers_across_requirements", True):
        for requirement in requirements:
            actors = {
                approval["provider_identity"]
                for approval in approvals
                if requirement["key"] in approval["requirement_keys"]
            }
            if len(actors) < int(requirement["quorum"]):
                return False
        return True
    slots: list[str] = []
    eligible_by_slot: dict[str, set[str]] = {}
    for requirement in requirements:
        eligible = {
            f"{actor['provider']}:{actor['provider_user_id']}"
            for actor in requirement.get("users", [])
        }
        for index in range(int(requirement["quorum"])):
            slot = f"{requirement['key']}:{index}"
            slots.append(slot)
            eligible_by_slot[slot] = eligible
    approved = {approval["provider_identity"] for approval in approvals}
    return _maximum_match(
        slots, {slot: eligible_by_slot[slot] & approved for slot in slots}
    ) == len(slots)


def _requirements_satisfiable(requirements: list[dict[str, Any]]) -> bool:
    slots: list[str] = []
    eligible: dict[str, set[str]] = {}
    for requirement in requirements:
        actors = {
            f"{actor['provider']}:{actor['provider_user_id']}"
            for actor in requirement.get("users", [])
        }
        for index in range(int(requirement["quorum"])):
            slot = f"{requirement['key']}:{index}"
            slots.append(slot)
            eligible[slot] = actors
    return _maximum_match(slots, eligible) == len(slots)


def _maximum_match(slots: list[str], eligible: dict[str, set[str]]) -> int:
    actor_to_slot: dict[str, str] = {}

    def assign(slot: str, seen: set[str]) -> bool:
        for actor in eligible.get(slot, set()):
            if actor in seen:
                continue
            seen.add(actor)
            previous = actor_to_slot.get(actor)
            if previous is None or assign(previous, seen):
                actor_to_slot[actor] = slot
                return True
        return False

    return sum(1 for slot in slots if assign(slot, set()))
