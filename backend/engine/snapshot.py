from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from backend.engine.validation import direct_references, parse_workflow, validate_workflow_bundle
from backend.integrations.git_manager import GitManager
from backend.schemas.workflow import WorkflowBundle, WorkflowDefinition


class BundleResolutionError(RuntimeError):
    pass


class WorkflowSnapshotLoader:
    def __init__(self, git: GitManager) -> None:
        self.git = git

    async def load(
        self,
        repository_path: Path,
        commit_sha: str,
        root_workflow_id: str,
        *,
        max_timeout: int,
        max_review_iterations: int,
        max_subworkflow_depth: int,
    ) -> WorkflowBundle:
        workflows: dict[str, WorkflowDefinition] = {}
        pending = [root_workflow_id]
        while pending:
            workflow_id = pending.pop()
            if workflow_id in workflows:
                continue
            raw = await self.git.show_file(
                repository_path,
                commit_sha,
                f".workflowEngine/{workflow_id}.json",
            )
            try:
                data: Any = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise BundleResolutionError(f"Workflow '{workflow_id}' is not valid JSON") from exc
            if not isinstance(data, dict):
                raise BundleResolutionError(f"Workflow '{workflow_id}' must be a JSON object")
            workflow, parse_errors = parse_workflow(data, f"workflows.{workflow_id}")
            if parse_errors or workflow is None:
                details = "; ".join(issue.message for issue in parse_errors)
                raise BundleResolutionError(f"Workflow '{workflow_id}' is invalid: {details}")
            if workflow.id != workflow_id:
                raise BundleResolutionError(
                    f"Workflow file '{workflow_id}.json' declares ID '{workflow.id}'"
                )
            workflows[workflow_id] = workflow
            pending.extend(direct_references(workflow))

        report = validate_workflow_bundle(
            root_workflow_id,
            workflows,
            filename=f"{root_workflow_id}.json",
            max_timeout=max_timeout,
            max_review_iterations=max_review_iterations,
            max_subworkflow_depth=max_subworkflow_depth,
        )
        if not report.valid:
            details = "; ".join(f"{issue.code}: {issue.message}" for issue in report.errors)
            raise BundleResolutionError(details)
        return WorkflowBundle(
            base_commit_sha=commit_sha,
            root_workflow_id=root_workflow_id,
            workflows=workflows,
            reference_graph={key: direct_references(value) for key, value in workflows.items()},
        )
