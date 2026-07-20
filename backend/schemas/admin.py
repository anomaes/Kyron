from __future__ import annotations

import uuid

from pydantic import BaseModel, Field


class UserAdminUpdate(BaseModel):
    is_active: bool | None = None
    is_system_admin: bool | None = None


class RoleRequest(BaseModel):
    key: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]*$", max_length=100)
    name: str = Field(min_length=1, max_length=255)
    description: str = Field(default="", max_length=2000)
    permissions: list[str] = Field(default_factory=list)


class MembershipRequest(BaseModel):
    user_id: uuid.UUID
    role_keys: list[str] = Field(default_factory=list)
    is_active: bool = True


class ApprovalRequirementRequest(BaseModel):
    key: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]*$", max_length=100)
    name: str = Field(min_length=1, max_length=255)
    quorum: int = Field(default=1, ge=1)
    role_keys: list[str] = Field(default_factory=list)
    user_ids: list[uuid.UUID] = Field(default_factory=list)


class ApprovalPolicyRequest(BaseModel):
    key: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]*$", max_length=100)
    name: str = Field(min_length=1, max_length=255)
    description: str = Field(default="", max_length=4000)
    enabled: bool = True
    initiator_may_approve: bool = False
    distinct_approvers_across_requirements: bool = True
    eligible_approvers_may_give_feedback: bool = True
    requirements: list[ApprovalRequirementRequest] = Field(min_length=1)


class GovernanceProfileRequest(BaseModel):
    key: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]*$", max_length=100)
    name: str = Field(min_length=1, max_length=255)
    enabled: bool = True
    applies_to_tags: list[str] = Field(default_factory=list)
    required_policy_keys: list[str] = Field(default_factory=list)
    prohibit_self_approval: bool = False
    min_total_approvals: int = Field(default=1, ge=1)


class GateOverrideRequest(BaseModel):
    reason: str = Field(min_length=3, max_length=4000)
