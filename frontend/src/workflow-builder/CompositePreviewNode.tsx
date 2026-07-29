import { Handle, Position, type Node, type NodeProps } from "@xyflow/react";
import type { KeyboardEvent, MouseEvent } from "react";
import { useWorkflowExpansion } from "./expansion-context";
import type { CompositeContainerData, ReviewBranch } from "./projection";
import { focusExpansionToggle, previewPanelId } from "./preview-target";

type CompositeFlowNode = Node<CompositeContainerData>;

function stop(event: MouseEvent<HTMLElement>) {
  event.stopPropagation();
}

export function CompositePreviewNode({ data, selected }: NodeProps<CompositeFlowNode>) {
  const expansion = useWorkflowExpansion();
  const panelId = previewPanelId(data.instanceKey);
  const isReview = data.callNode.type === "review_loop";
  const childName = data.childWorkflow?.name
    ?? String(data.callNode.config[
      data.branch === "subworkflow"
        ? "workflow_id"
        : data.branch === "initial"
          ? "initial_workflow_id"
          : "revision_workflow_id"
    ] ?? "Child workflow");
  const childId = data.childWorkflow?.id ?? "";
  const breadcrumb = [...data.breadcrumb, data.callNode.label].join(" / ");
  const revisionId = String(data.callNode.config.revision_workflow_id ?? "");
  const initialId = String(data.callNode.config.initial_workflow_id ?? "");
  const revision = expansion.catalogById.get(revisionId);
  const initial = expansion.catalogById.get(initialId);

  const collapse = (event: MouseEvent<HTMLButtonElement>) => {
    stop(event);
    expansion.collapse(data.instanceKey, childName);
    focusExpansionToggle(data.instanceKey);
  };
  const selectTab = (branch: ReviewBranch) => {
    const workflow = branch === "initial" ? initial : revision;
    if (branch === "revision" && !revisionId) return;
    const workflowId = branch === "initial" ? initialId : revisionId;
    expansion.selectReviewTab(data.instanceKey, branch, workflowId, workflow?.name ?? workflowId);
  };
  const onTabKeyDown = (event: KeyboardEvent<HTMLButtonElement>) => {
    const ordered: ReviewBranch[] = revisionId ? ["initial", "revision"] : ["initial"];
    const current = ordered.indexOf(data.branch === "subworkflow" ? "initial" : data.branch);
    let next = current;
    if (event.key === "ArrowRight") next = (current + 1) % ordered.length;
    else if (event.key === "ArrowLeft") next = (current - 1 + ordered.length) % ordered.length;
    else if (event.key === "Home") next = 0;
    else if (event.key === "End") next = ordered.length - 1;
    else if (event.key === "Enter" || event.key === " ") {
      selectTab(event.currentTarget.dataset.branch as ReviewBranch);
      event.preventDefault();
      return;
    } else return;
    event.preventDefault();
    const branch = ordered[next];
    if (!branch) return;
    selectTab(branch);
    event.currentTarget.parentElement?.querySelector<HTMLButtonElement>(`[data-branch="${branch}"]`)?.focus();
  };

  return <div
    className={`composite-preview type-${data.callNode.type} depth-${Math.min(data.depth, 4)} ${selected ? "selected" : ""}`}
    id={panelId}
    data-preview-panel
  >
    <Handle type="target" position={Position.Left} isConnectable={false} />
    <header className="composite-preview-header">
      <div className="composite-preview-title">
        <small>{isReview ? "Review loop" : "Sub-workflow"}{data.depth > 0 ? ` · nested level ${data.depth}` : ""}</small>
        <strong>{data.callNode.label}</strong>
        <span title={breadcrumb}>{breadcrumb}</span>
      </div>
      <div className="composite-preview-summary">
        <b>{childName}</b>
        {childId && <code>{childId}</code>}
        <span>
          {isReview
            ? `${String(data.callNode.config.approval_policy ?? "No policy")} · ${Number(data.callNode.config.max_iterations ?? 5)} iterations`
            : `${String(data.callNode.config.execution_mode ?? "shared")} · ${data.childWorkflow?.nodes.length ?? 0} nodes`}
        </span>
      </div>
      <div className="composite-preview-actions">
        {childId && <a
          className="preview-open nodrag nopan"
          href={`/projects/${encodeURIComponent(expansion.projectId)}/workflows/${encodeURIComponent(childId)}/edit`}
          target="_blank"
          rel="noreferrer"
          aria-label={`Open ${childName} workflow in a new tab`}
          onPointerDown={stop}
          onClick={stop}
        >Open workflow <span aria-hidden="true">↗</span></a>}
        <button
          type="button"
          className="preview-collapse nodrag nopan"
          aria-expanded="true"
          aria-controls={panelId}
          aria-label={`Collapse ${childName}`}
          onPointerDown={stop}
          onClick={collapse}
        >Collapse</button>
      </div>
    </header>
    {isReview && <div className="review-preview-tabs" role="tablist" aria-label={`${data.callNode.label} child workflow`}>
      <button
        type="button"
        role="tab"
        className="nodrag nopan"
        id={`${panelId}-tab-initial`}
        data-branch="initial"
        aria-selected={data.branch === "initial"}
        aria-controls={`${panelId}-panel-initial`}
        tabIndex={data.branch === "initial" ? 0 : -1}
        onPointerDown={stop}
        onClick={(event) => { stop(event); selectTab("initial"); }}
        onKeyDown={onTabKeyDown}
      >Initial</button>
      <button
        type="button"
        role="tab"
        className="nodrag nopan"
        id={`${panelId}-tab-revision`}
        data-branch="revision"
        aria-selected={data.branch === "revision"}
        aria-controls={`${panelId}-panel-revision`}
        aria-describedby={!revisionId ? `${panelId}-revision-help` : undefined}
        tabIndex={data.branch === "revision" ? 0 : -1}
        disabled={!revisionId}
        onPointerDown={stop}
        onClick={(event) => { stop(event); selectTab("revision"); }}
        onKeyDown={onTabKeyDown}
      >Revision</button>
      {!revisionId && <span id={`${panelId}-revision-help`}>No separate revision workflow; later iterations reuse the initial workflow.</span>}
    </div>}
    <div
      className="composite-preview-body"
      id={`${panelId}-panel-${data.branch === "subworkflow" ? "subworkflow" : data.branch}`}
      role={isReview ? "tabpanel" : "group"}
      aria-labelledby={isReview ? `${panelId}-tab-${data.branch}` : undefined}
      aria-label={!isReview ? `${childName} read-only child graph` : undefined}
    >
      {data.warning && <div className="composite-preview-state" role="status">{data.warning}</div>}
      {data.empty && <div className="composite-preview-state">This workflow has no nodes.</div>}
      {data.clamped && <div className="composite-preview-limit">Preview dimensions limited; use zoom and pan to inspect the visible graph.</div>}
    </div>
    <Handle type="source" position={Position.Right} isConnectable={false} />
  </div>;
}
