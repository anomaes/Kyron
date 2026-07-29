import { Handle, Position, type NodeProps } from "@xyflow/react";
import { useWorkflowExpansion } from "./expansion-context";
import { previewPanelId, resolvePreviewTarget } from "./preview-target";
import { topLevelInstanceKey } from "./projection";
import type { BuilderNode } from "./store";

const icons = { bash: ">_", script: "Py", prompt: "✦", human_feedback: "◎", subworkflow: "◇", review_loop: "↻" };

export function WorkflowCard({ data, selected }: NodeProps<BuilderNode>) {
  const expansion = useWorkflowExpansion();
  const config = data.workflowNode.config;
  const preview = data.type === "bash" ? String(config.command ?? "") : data.type === "prompt" ? String(config.prompt ?? "") : data.type === "script" ? String(config.script ?? "") : data.type === "subworkflow" ? String(config.workflow_id ?? "") : data.type === "review_loop" ? `${String(config.initial_workflow_id ?? "")} · ${String(config.approval_policy ?? "no policy")}` : `Policy: ${String(config.approval_policy ?? "not selected")}`;
  const composite = data.type === "subworkflow" || data.type === "review_loop";
  const instanceKey = topLevelInstanceKey(data.workflowNode.id);
  const target = composite
    ? resolvePreviewTarget(
      data.workflowNode,
      instanceKey,
      expansion.catalogById,
      expansion.catalogStatus,
      expansion.snapshot.reviewTabs,
    )
    : null;
  return <div className={`builder-node type-${data.type} ${selected ? "selected" : ""}`}>
    <Handle type="target" position={Position.Left} />
    <div className="builder-node-head"><span aria-hidden="true">{icons[data.type]}</span><small>{data.type.replaceAll("_", " ")}</small>{data.workflowNode.join === "or" && <b>OR</b>}</div>
    <strong>{data.label}</strong>
    <p>{target?.workflow?.name ?? preview}</p>
    {target?.unavailableMessage && <span className="builder-preview-warning">{target.unavailableMessage}</span>}
    {target && <button
      type="button"
      className="preview-toggle nodrag nopan"
      aria-expanded="false"
      aria-controls={previewPanelId(instanceKey)}
      aria-label={`Expand ${target.label}`}
      data-expansion-key={instanceKey}
      disabled={!target.canExpand}
      onPointerDown={(event) => event.stopPropagation()}
      onClick={(event) => {
        event.stopPropagation();
        if (!target.canExpand) return;
        expansion.expand(instanceKey, instanceKey, target.workflowId, target.label, target.workflow?.nodes.length ?? 0);
      }}
    >Expand</button>}
    <Handle type="source" position={Position.Right} />
  </div>;
}
