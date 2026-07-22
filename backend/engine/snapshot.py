from __future__ import annotations

import json
import logging
from pathlib import Path, PurePosixPath
from typing import Any

from backend.engine.validation import direct_references, parse_workflow, validate_workflow_bundle
from backend.integrations.git_manager import GitManager
from backend.schemas.pi import PiSettings
from backend.schemas.workflow import WorkflowBundle, WorkflowDefinition

logger = logging.getLogger(__name__)


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
        project_pi: PiSettings | None = None,
    ) -> WorkflowBundle:
        logger.info(
            "Resolving workflow snapshot (workflow=%s, commit=%s)",
            root_workflow_id,
            _short_sha(commit_sha),
        )
        workflows: dict[str, WorkflowDefinition] = {}
        workflow_paths = await self._workflow_paths(repository_path, commit_sha)
        pending = [root_workflow_id]
        while pending:
            workflow_id = pending.pop()
            if workflow_id in workflows:
                continue
            candidates = workflow_paths.get(workflow_id, [])
            if not candidates:
                raise BundleResolutionError(
                    f"Workflow '{workflow_id}' does not exist at commit {_short_sha(commit_sha)}"
                )
            if len(candidates) > 1:
                raise BundleResolutionError(
                    f"Workflow ID '{workflow_id}' is used by multiple files: "
                    + ", ".join(candidates)
                )
            filename = candidates[0]
            try:
                raw = await self.git.show_file(repository_path, commit_sha, filename)
            except Exception as exc:
                logger.warning(
                    "Could not read workflow definition (workflow=%s, file=%s, commit=%s): %s",
                    workflow_id,
                    filename,
                    _short_sha(commit_sha),
                    exc,
                )
                raise
            try:
                data: Any = json.loads(raw)
            except json.JSONDecodeError as exc:
                logger.warning(
                    "Workflow JSON parsing failed (workflow=%s, file=%s, commit=%s, "
                    "line=%s, column=%s): %s",
                    workflow_id,
                    filename,
                    _short_sha(commit_sha),
                    exc.lineno,
                    exc.colno,
                    exc.msg,
                )
                raise BundleResolutionError(
                    f"Workflow '{workflow_id}' is not valid JSON at line {exc.lineno}, "
                    f"column {exc.colno}: {exc.msg}"
                ) from exc
            if not isinstance(data, dict):
                logger.warning(
                    "Workflow parsing failed (workflow=%s, file=%s, commit=%s): "
                    "top-level JSON value is %s, expected an object",
                    workflow_id,
                    filename,
                    _short_sha(commit_sha),
                    type(data).__name__,
                )
                raise BundleResolutionError(f"Workflow '{workflow_id}' must be a JSON object")
            workflow, parse_errors = parse_workflow(data, f"workflows.{workflow_id}")
            if parse_errors or workflow is None:
                details = _issue_details(parse_errors)
                logger.warning(
                    "Workflow schema parsing failed (workflow=%s, file=%s, commit=%s): %s",
                    workflow_id,
                    filename,
                    _short_sha(commit_sha),
                    details,
                )
                raise BundleResolutionError(f"Workflow '{workflow_id}' is invalid: {details}")
            if workflow.id != workflow_id:
                logger.warning(
                    "Workflow parsing failed (workflow=%s, file=%s, commit=%s): "
                    "declared ID is %s",
                    workflow_id,
                    filename,
                    _short_sha(commit_sha),
                    workflow.id,
                )
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
            details = _issue_details(report.errors)
            logger.warning(
                "Workflow bundle validation failed (workflow=%s, commit=%s): %s",
                root_workflow_id,
                _short_sha(commit_sha),
                details,
            )
            raise BundleResolutionError(details)
        logger.info(
            "Workflow snapshot resolved (workflow=%s, commit=%s, definitions=%s)",
            root_workflow_id,
            _short_sha(commit_sha),
            len(workflows),
        )
        return WorkflowBundle(
            base_commit_sha=commit_sha,
            root_workflow_id=root_workflow_id,
            project_pi=project_pi or PiSettings(),
            workflows=workflows,
            reference_graph={key: direct_references(value) for key, value in workflows.items()},
        )

    async def _workflow_paths(
        self, repository_path: Path, commit_sha: str
    ) -> dict[str, list[str]]:
        paths: dict[str, list[str]] = {}
        for filename in await self.git.list_files(
            repository_path, commit_sha, ".workflowEngine"
        ):
            path = PurePosixPath(filename)
            try:
                relative = path.relative_to(".workflowEngine")
            except ValueError:
                continue
            if (
                path.suffix != ".json"
                or not relative.parts
                or relative.parts[0] == "templates"
            ):
                continue
            paths.setdefault(path.stem, []).append(filename)
        return paths


def _issue_details(issues: list[Any]) -> str:
    return "; ".join(f"{issue.path} [{issue.code}]: {issue.message}" for issue in issues)


def _short_sha(commit_sha: str) -> str:
    return commit_sha[:12]
