from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import (
    EdgeEvaluation,
    NodeExecution,
    Project,
    User,
    WorkflowInvocation,
    WorkflowRun,
)
from backend.db.statuses import InvocationStatus, NodeStatus, RunStatus
from backend.engine.conditions import evaluate_condition
from backend.engine.context import expand_public_variables
from backend.engine.scheduler import DagScheduler, GraphDeadlockError, LogicalStatus
from backend.engine.waves import WaveExecutionError, WaveExecutor
from backend.integrations.code_host import (
    CodeHostClient,
    ProviderUser,
    git_username,
    repository_locator,
)
from backend.integrations.git_manager import GitManager, project_git_locks
from backend.schemas.workflow import (
    HumanFeedbackNode,
    ReviewLoopNode,
    SubworkflowNode,
    WorkflowBundle,
    WorkflowDefinition,
)
from backend.services.crypto import SecretCipher


class RunPaused(RuntimeError):
    pass


class RunExecutionError(RuntimeError):
    pass


class RunCoordinator:
    def __init__(
        self,
        session: AsyncSession,
        git: GitManager,
        code_host: CodeHostClient,
        cipher: SecretCipher,
        wave_executor: WaveExecutor,
    ) -> None:
        self.session = session
        self.git = git
        self.code_host = code_host
        self.cipher = cipher
        self.wave_executor = wave_executor

    async def execute_run(self, run_id: uuid.UUID) -> None:
        run = await self._run(run_id)
        project = await self._project(run.project_id)
        user = await self._user(run.triggered_by)
        bundle = WorkflowBundle.model_validate(run.workflow_bundle_snapshot)
        if run.status == RunStatus.QUEUED:
            async with project_git_locks.for_project(project.id):
                branch, worktree, run_data = await self.git.create_run_worktree(
                    Path(project.local_path),
                    run.id,
                    run.root_workflow_id,
                    run.base_commit_sha,
                )
            run.branch_name = branch
            run.worktree_path = str(worktree)
            run.run_data_path = str(run_data)
            run.current_head_sha = run.base_commit_sha
            run.public_context = {
                **run.public_context,
                **self._builtins(run, project, user, bundle.workflows[run.root_workflow_id]),
            }
            root = WorkflowInvocation(
                run_id=run.id,
                workflow_id=run.root_workflow_id,
                invocation_path="root",
                input_context=dict(run.public_context),
                status=InvocationStatus.PENDING,
            )
            self.session.add(root)
            run.status = RunStatus.RUNNING
            run.started_at = datetime.now(UTC)
            await self.session.commit()
        else:
            existing_root = await self.session.scalar(
                select(WorkflowInvocation).where(
                    WorkflowInvocation.run_id == run.id,
                    WorkflowInvocation.invocation_path == "root",
                )
            )
            if existing_root is None:
                raise RunExecutionError("Run has no root invocation")
            root = existing_root
            if run.status == RunStatus.RESUMING:
                run.status = RunStatus.RUNNING
                await self.session.commit()

        try:
            await self.execute_invocation(run, root, bundle, project, user)
        except RunPaused:
            return
        except (WaveExecutionError, GraphDeadlockError, RunExecutionError) as exc:
            if run.status != RunStatus.FAILED:
                run.status = RunStatus.FAILED
                run.error_type = (
                    "GRAPH_DEADLOCK" if isinstance(exc, GraphDeadlockError) else "NODE_FAILURE"
                )
                run.error_message = str(exc)
                await self.session.commit()
            return

        workflow = bundle.workflows[run.root_workflow_id]
        run.public_context = {
            **run.public_context,
            "WORKFLOW_ID": workflow.id,
            "WORKFLOW_NAME": workflow.name,
        }
        assert run.worktree_path and run.branch_name
        final_message = expand_public_variables(
            workflow.settings.final_commit_message_template, run.public_context
        )
        final_sha = await self.git.checkpoint(Path(run.worktree_path), final_message)
        token = self.cipher.decrypt(project.encrypted_access_token)
        try:
            await self.git.push(
                Path(run.worktree_path),
                run.branch_name,
                token,
                username=git_username(project.provider),
            )
            await self._ensure_merge_request(run, project, workflow, token)
        finally:
            token = ""
        run.final_commit_sha = final_sha
        run.current_head_sha = final_sha
        run.status = RunStatus.COMPLETED
        run.finished_at = datetime.now(UTC)
        run.current_invocation_id = None
        run.current_node_execution_id = None
        run.current_wave_id = None
        await self.session.commit()

    async def execute_invocation(
        self,
        run: WorkflowRun,
        invocation: WorkflowInvocation,
        bundle: WorkflowBundle,
        project: Project,
        user: User,
    ) -> dict[str, Any]:
        workflow = bundle.workflows[invocation.workflow_id]
        run.public_context = {
            **workflow.variables,
            **run.public_context,
            **invocation.input_context,
            "WORKFLOW_ID": workflow.id,
            "WORKFLOW_NAME": workflow.name,
            "INVOCATION_ID": str(invocation.id),
            "INVOCATION_PATH": invocation.invocation_path,
        }
        invocation.status = InvocationStatus.RUNNING
        invocation.started_at = invocation.started_at or datetime.now(UTC)
        await self.session.commit()
        scheduler = DagScheduler(workflow)
        while True:
            executions = list(
                await self.session.scalars(
                    select(NodeExecution).where(NodeExecution.invocation_id == invocation.id)
                )
            )
            statuses = {
                execution.node_id: _logical_status(execution.status) for execution in executions
            }
            edges = list(
                await self.session.scalars(
                    select(EdgeEvaluation).where(EdgeEvaluation.invocation_id == invocation.id)
                )
            )
            edge_results = {edge.edge_id: edge.condition_result for edge in edges}
            if scheduler.complete(statuses):
                outputs = self._workflow_outputs(workflow, run.public_context)
                invocation.output_context = outputs
                invocation.status = InvocationStatus.SUCCESS
                invocation.finished_at = datetime.now(UTC)
                await self.session.commit()
                return outputs
            decision = scheduler.next(statuses, edge_results)
            for node_id in decision.skipped_node_ids:
                execution = await self._node_execution(run, invocation, workflow, node_id)
                execution.status = NodeStatus.SKIPPED
                execution.finished_at = datetime.now(UTC)
                await self._persist_control_edges(
                    run, invocation, workflow, execution, success=False
                )
            if decision.skipped_node_ids:
                await self.session.commit()
            if not decision.nodes:
                continue
            if not decision.control_boundary:
                process_nodes = [
                    node for node in decision.nodes if node.type in {"bash", "script", "prompt"}
                ]
                await self.wave_executor.execute(
                    run,
                    invocation,
                    workflow,
                    process_nodes,  # type: ignore[arg-type]
                )
                continue
            node = decision.nodes[0]
            if isinstance(node, SubworkflowNode):
                await self._execute_subworkflow(
                    run, invocation, workflow, node, bundle, project, user
                )
            elif isinstance(node, HumanFeedbackNode):
                await self._pause_for_feedback(
                    run, invocation, workflow, node, project, user, iteration=1
                )
            elif isinstance(node, ReviewLoopNode):
                await self._execute_review_loop(
                    run, invocation, workflow, node, bundle, project, user
                )
            else:
                raise RunExecutionError(f"Unsupported control node '{node.type}'")

    async def _execute_subworkflow(
        self,
        run: WorkflowRun,
        invocation: WorkflowInvocation,
        workflow: WorkflowDefinition,
        node: SubworkflowNode,
        bundle: WorkflowBundle,
        project: Project,
        user: User,
    ) -> None:
        execution = await self._node_execution(run, invocation, workflow, node.id)
        execution.status = NodeStatus.RUNNING
        execution.started_at = execution.started_at or datetime.now(UTC)
        child_path = f"{invocation.invocation_path}/{node.id}"
        child = await self.session.scalar(
            select(WorkflowInvocation).where(
                WorkflowInvocation.run_id == run.id,
                WorkflowInvocation.invocation_path == child_path,
            )
        )
        if child is None:
            mapped = {
                name: expand_public_variables(value, run.public_context)
                for name, value in node.config.inputs.items()
            }
            child = WorkflowInvocation(
                run_id=run.id,
                workflow_id=node.config.workflow_id,
                invocation_path=child_path,
                parent_invocation_id=invocation.id,
                parent_node_execution_id=execution.id,
                input_context=mapped,
                status=InvocationStatus.PENDING,
            )
            self.session.add(child)
            run.public_context = {
                **run.public_context,
                **bundle.workflows[node.config.workflow_id].variables,
                **mapped,
            }
            await self.session.commit()
        try:
            outputs = await self.execute_invocation(run, child, bundle, project, user)
        except Exception:
            execution.status = NodeStatus.FAILED
            execution.finished_at = datetime.now(UTC)
            await self.session.commit()
            raise
        mapped_outputs = {
            parent_name: outputs[child_name]
            for child_name, parent_name in node.config.output_mapping.items()
            if child_name in outputs
        }
        run.public_context = {**run.public_context, **mapped_outputs}
        execution.output_values = mapped_outputs
        execution.status = NodeStatus.SUCCESS
        execution.finished_at = datetime.now(UTC)
        await self._persist_control_edges(run, invocation, workflow, execution, success=True)
        await self.session.commit()

    async def _execute_review_loop(
        self,
        run: WorkflowRun,
        invocation: WorkflowInvocation,
        workflow: WorkflowDefinition,
        node: ReviewLoopNode,
        bundle: WorkflowBundle,
        project: Project,
        user: User,
    ) -> None:
        execution = await self._node_execution(run, invocation, workflow, node.id)
        metadata = dict(execution.output_values)
        iteration = int(metadata.get("review_iteration", 1))
        maximum = node.config.max_iterations or workflow.settings.max_review_iterations
        if iteration > maximum:
            execution.status = NodeStatus.FAILED
            execution.error_message = "Maximum review iterations reached"
            run.status = RunStatus.FAILED
            run.error_type = "MAX_REVIEW_ITERATIONS_REACHED"
            run.error_message = execution.error_message
            await self.session.commit()
            raise RunExecutionError(execution.error_message)
        child_workflow_id = (
            node.config.initial_workflow_id
            if iteration == 1
            else node.config.revision_workflow_id or node.config.initial_workflow_id
        )
        mapping = node.config.inputs if iteration == 1 else node.config.revision_inputs
        kind = "initial" if iteration == 1 else "revision"
        child_path = f"{invocation.invocation_path}/{node.id}/{kind}[{iteration}]"
        child = await self.session.scalar(
            select(WorkflowInvocation).where(
                WorkflowInvocation.run_id == run.id,
                WorkflowInvocation.invocation_path == child_path,
            )
        )
        execution.status = NodeStatus.RUNNING
        execution.started_at = execution.started_at or datetime.now(UTC)
        if child is None:
            child_inputs = {
                name: expand_public_variables(value, run.public_context)
                for name, value in mapping.items()
            }
            child = WorkflowInvocation(
                run_id=run.id,
                workflow_id=child_workflow_id,
                invocation_path=child_path,
                parent_invocation_id=invocation.id,
                parent_node_execution_id=execution.id,
                loop_iteration=iteration,
                input_context=child_inputs,
                status=InvocationStatus.PENDING,
            )
            self.session.add(child)
            run.public_context = {
                **run.public_context,
                **bundle.workflows[child_workflow_id].variables,
                **child_inputs,
                "REVIEW_ITERATION": iteration,
            }
            await self.session.commit()
        outputs = await self.execute_invocation(run, child, bundle, project, user)
        mapped_outputs = {
            parent_name: outputs[child_name]
            for child_name, parent_name in node.config.output_mapping.items()
            if child_name in outputs
        }
        run.public_context = {**run.public_context, **mapped_outputs}
        execution.output_values = {
            **mapped_outputs,
            "review_iteration": iteration,
            "max_iterations": maximum,
            "last_child_invocation_id": str(child.id),
        }
        await self._pause_for_feedback(
            run, invocation, workflow, node, project, user, iteration=iteration
        )

    async def _pause_for_feedback(
        self,
        run: WorkflowRun,
        invocation: WorkflowInvocation,
        workflow: WorkflowDefinition,
        node: HumanFeedbackNode | ReviewLoopNode,
        project: Project,
        user: User,
        *,
        iteration: int,
    ) -> None:
        assert run.worktree_path and run.branch_name
        execution = await self._node_execution(run, invocation, workflow, node.id)
        context = {**run.public_context, "REVIEW_ITERATION": iteration}
        message = expand_public_variables(node.config.commit_message, context)
        head = await self.git.checkpoint(Path(run.worktree_path), message)
        token = self.cipher.decrypt(project.encrypted_access_token)
        try:
            await self.git.push(
                Path(run.worktree_path),
                run.branch_name,
                token,
                username=git_username(project.provider),
            )
            await self._ensure_merge_request(run, project, workflow, token, node=node)
        finally:
            token = ""
        execution.status = NodeStatus.AWAITING_FEEDBACK
        execution.output_values = {
            **execution.output_values,
            "review_iteration": iteration,
        }
        run.status = RunStatus.AWAITING_FEEDBACK
        run.current_head_sha = head
        run.current_invocation_id = invocation.id
        run.current_node_execution_id = execution.id
        run.current_wave_id = None
        await self.session.commit()
        raise RunPaused()

    async def _ensure_merge_request(
        self,
        run: WorkflowRun,
        project: Project,
        workflow: WorkflowDefinition,
        token: str,
        *,
        node: HumanFeedbackNode | ReviewLoopNode | None = None,
    ) -> None:
        assert run.branch_name
        title_template = (
            node.config.mr_title
            if node and node.config.mr_title
            else workflow.settings.mr_title_template
        )
        description_template = (
            node.config.mr_description
            if node and node.config.mr_description
            else workflow.settings.mr_description_template
        )
        title = expand_public_variables(title_template, run.public_context)
        description = expand_public_variables(description_template, run.public_context)
        reviewer = ProviderUser(
            id=run.reviewer_provider_user_id,
            username=run.reviewer_provider_username,
        )
        if run.change_request_number:
            await self.code_host.update_change_request_reviewer(
                repository_locator(
                    project.provider,
                    project.provider_project_id,
                    project.provider_project_path,
                ),
                run.change_request_number,
                token,
                reviewer,
            )
            return
        change_request = await self.code_host.create_change_request(
            repository_locator(
                project.provider, project.provider_project_id, project.provider_project_path
            ),
            token,
            source_branch=run.branch_name,
            target_branch=run.base_ref,
            title=title,
            description=description,
            reviewer=reviewer,
        )
        run.change_request_number = change_request.number
        run.change_request_url = change_request.url
        await self.session.commit()

    async def _node_execution(
        self,
        run: WorkflowRun,
        invocation: WorkflowInvocation,
        workflow: WorkflowDefinition,
        node_id: str,
    ) -> NodeExecution:
        execution = await self.session.scalar(
            select(NodeExecution).where(
                NodeExecution.invocation_id == invocation.id,
                NodeExecution.node_id == node_id,
            )
        )
        if execution is not None:
            return execution
        node = next(item for item in workflow.nodes if item.id == node_id)
        execution = NodeExecution(
            run_id=run.id,
            invocation_id=invocation.id,
            node_id=node.id,
            node_path=f"{invocation.invocation_path}/{node.id}",
            node_type=node.type,
            status=NodeStatus.PENDING,
        )
        self.session.add(execution)
        await self.session.flush()
        return execution

    async def _persist_control_edges(
        self,
        run: WorkflowRun,
        invocation: WorkflowInvocation,
        workflow: WorkflowDefinition,
        execution: NodeExecution,
        *,
        success: bool,
    ) -> None:
        assert run.worktree_path
        existing = set(
            await self.session.scalars(
                select(EdgeEvaluation.edge_id).where(
                    EdgeEvaluation.source_node_execution_id == execution.id
                )
            )
        )
        for edge in workflow.edges:
            if edge.source != execution.node_id or edge.id in existing:
                continue
            if success:
                result, value = evaluate_condition(
                    edge.condition,
                    exit_code=0,
                    stdout="",
                    stderr="",
                    public_context=run.public_context,
                    worktree=Path(run.worktree_path),
                )
            else:
                result, value = False, None
            self.session.add(
                EdgeEvaluation(
                    run_id=run.id,
                    invocation_id=invocation.id,
                    source_node_execution_id=execution.id,
                    edge_id=edge.id,
                    target_node_id=edge.target,
                    condition_result=result,
                    evaluated_value=value,
                )
            )

    @staticmethod
    def _workflow_outputs(workflow: WorkflowDefinition, context: dict[str, Any]) -> dict[str, Any]:
        return {
            name: expand_public_variables(definition.source, context)
            for name, definition in workflow.outputs.items()
        }

    @staticmethod
    def _builtins(
        run: WorkflowRun, project: Project, user: User, workflow: WorkflowDefinition
    ) -> dict[str, str]:
        return {
            "RUN_ID": str(run.id),
            "RUN_ID_SHORT": run.id.hex[:8],
            "ROOT_WORKFLOW_ID": run.root_workflow_id,
            "WORKFLOW_ID": workflow.id,
            "WORKFLOW_NAME": workflow.name,
            "PROJECT_ID": str(project.id),
            "PROJECT_NAME": project.name,
            "BASE_REF": run.base_ref,
            "BASE_COMMIT_SHA": run.base_commit_sha,
            "BRANCH": run.branch_name or "",
            "WORKTREE_PATH": run.worktree_path or "",
            "RUN_DATA_PATH": run.run_data_path or "",
            "USER_NAME": user.display_name,
            "USER_EMAIL": user.email,
            "CODE_HOST_PROVIDER": run.reviewer_provider,
            "PROVIDER_USER_ID": run.reviewer_provider_user_id,
            "PROVIDER_USERNAME": run.reviewer_provider_username,
            "GITLAB_USER_ID": (
                run.reviewer_provider_user_id if run.reviewer_provider == "gitlab" else ""
            ),
            "GITLAB_USERNAME": (
                run.reviewer_provider_username if run.reviewer_provider == "gitlab" else ""
            ),
        }

    async def _run(self, run_id: uuid.UUID) -> WorkflowRun:
        run = await self.session.get(WorkflowRun, run_id)
        if run is None:
            raise RunExecutionError("Run does not exist")
        return run

    async def _project(self, project_id: uuid.UUID) -> Project:
        project = await self.session.get(Project, project_id)
        if project is None:
            raise RunExecutionError("Project does not exist")
        return project

    async def _user(self, user_id: uuid.UUID) -> User:
        user = await self.session.get(User, user_id)
        if user is None:
            raise RunExecutionError("Triggering user does not exist")
        return user


def _logical_status(status: str) -> LogicalStatus:
    mapping = {
        NodeStatus.PENDING: LogicalStatus.PENDING,
        NodeStatus.RUNNING: LogicalStatus.RUNNING,
        NodeStatus.SUCCESS: LogicalStatus.SUCCESS,
        NodeStatus.SKIPPED: LogicalStatus.SKIPPED,
        NodeStatus.FAILED: LogicalStatus.FAILED,
        NodeStatus.CANCELLED: LogicalStatus.FAILED,
        NodeStatus.INTERRUPTED: LogicalStatus.FAILED,
        NodeStatus.AWAITING_FEEDBACK: LogicalStatus.RUNNING,
    }
    return mapping[NodeStatus(status)]
