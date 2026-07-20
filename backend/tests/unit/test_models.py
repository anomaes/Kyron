from sqlalchemy import inspect

from backend.db.database import Base


def test_complete_domain_tables_are_declared() -> None:
    assert set(Base.metadata.tables) == {
        "users",
        "provider_identities",
        "credentials",
        "projects",
        "workflow_runs",
        "workflow_invocations",
        "execution_waves",
        "node_executions",
        "node_attempts",
        "edge_evaluations",
        "feedback_events",
        "run_logs",
        "webhook_deliveries",
        "resource_audit_logs",
        "project_memberships",
        "project_roles",
        "project_role_permissions",
        "project_membership_roles",
        "approval_policies",
        "approval_policy_requirements",
        "approval_requirement_roles",
        "approval_requirement_users",
        "governance_profiles",
        "gate_instances",
        "gate_decisions",
        "authorization_audit_events",
        "run_reports",
        "change_request_lifecycle_events",
    }


def test_run_indexes_include_operational_queries() -> None:
    table = Base.metadata.tables["workflow_runs"]
    names = {index.name for index in inspect(table).indexes}
    assert "ix_workflow_runs_status_queued" in names
    assert "ix_workflow_runs_project_created" in names
