import type { Workflow, WorkflowNode } from "../types";
import type { CatalogStatus, CompositeBranch, ReviewBranch } from "./projection";

export type PreviewTarget = {
  branch: CompositeBranch;
  workflowId: string;
  workflow: Workflow | null;
  label: string;
  unavailableMessage?: string;
  canExpand: boolean;
};

export function resolvePreviewTarget(
  node: WorkflowNode,
  instanceKey: string,
  catalogById: ReadonlyMap<string, Workflow>,
  catalogStatus: CatalogStatus,
  reviewTabs: ReadonlyMap<string, ReviewBranch>,
): PreviewTarget {
  const branch: CompositeBranch = node.type === "review_loop"
    ? reviewTabs.get(instanceKey) ?? "initial"
    : "subworkflow";
  const key = branch === "subworkflow"
    ? "workflow_id"
    : branch === "initial"
      ? "initial_workflow_id"
      : "revision_workflow_id";
  const workflowId = String(node.config[key] ?? "");
  const workflow = catalogById.get(workflowId) ?? null;
  const label = workflow?.name || workflowId || "child workflow";

  if (!workflowId) {
    return {
      branch,
      workflowId,
      workflow,
      label,
      unavailableMessage: branch === "revision"
        ? "No separate revision workflow"
        : "Referenced workflow is not configured",
      canExpand: false,
    };
  }
  if (catalogStatus === "ready" && !workflow) {
    return {
      branch,
      workflowId,
      workflow,
      label,
      unavailableMessage: "Referenced workflow not found",
      canExpand: false,
    };
  }

  return {
    branch,
    workflowId,
    workflow,
    label,
    unavailableMessage: catalogStatus === "loading" && !workflow
      ? "Loading preview"
      : catalogStatus === "error" && !workflow
        ? "Preview unavailable"
        : undefined,
    canExpand: true,
  };
}

export function previewPanelId(instanceKey: string): string {
  return `workflow-preview-${instanceKey.replace(/[^A-Za-z0-9_-]/g, "-")}`;
}

export function focusExpansionToggle(instanceKey: string): void {
  window.requestAnimationFrame(() => {
    document.querySelector<HTMLElement>(`[data-expansion-key="${CSS.escape(instanceKey)}"]`)?.focus();
  });
}

