import { Handle, Position, type Node, type NodeProps } from "@xyflow/react";
import type { PreviewNodeData } from "./projection";
import { focusExpansionToggle, previewPanelId, resolvePreviewTarget } from "./preview-target";
import { useWorkflowExpansion } from "./expansion-context";

type PreviewFlowNode = Node<PreviewNodeData>;

const icons = { bash: ">_", script: "Py", prompt: "✦", human_feedback: "◎", subworkflow: "◇", review_loop: "↻" };

export function WorkflowPreviewNode({ data }: NodeProps<PreviewFlowNode>) {
  const expansion = useWorkflowExpansion();
  const node = data.workflowNode;
  const composite = node.type === "subworkflow" || node.type === "review_loop";
  const target = composite
    ? resolvePreviewTarget(
      node,
      data.instanceKey,
      expansion.catalogById,
      expansion.catalogStatus,
      expansion.snapshot.reviewTabs,
    )
    : null;
  const path = [...data.breadcrumb, node.label].join(" / ");

  const expand = (event: React.MouseEvent<HTMLButtonElement>) => {
    event.stopPropagation();
    if (!target?.canExpand) return;
    expansion.expand(
      data.instanceKey,
      data.topLevelKey,
      target.workflowId,
      target.label,
      target.workflow?.nodes.length ?? 0,
    );
  };

  return <div
    className={`workflow-preview-node type-${node.type}`}
    aria-label={`${data.workflowName}, ${node.type.replaceAll("_", " ")}, ${node.label}, read-only preview`}
    title={path}
  >
    <Handle type="target" position={Position.Left} isConnectable={false} />
    <div className="workflow-preview-node-head">
      <span aria-hidden="true">{icons[node.type]}</span>
      <small>{node.type.replaceAll("_", " ")}</small>
      <b>Read-only</b>
    </div>
    <strong>{node.label}</strong>
    {target?.unavailableMessage && <p className="preview-inline-warning">{target.unavailableMessage}</p>}
    {target && <button
      type="button"
      className="preview-toggle nodrag nopan"
      aria-expanded="false"
      aria-controls={previewPanelId(data.instanceKey)}
      aria-label={`Expand ${target.label}`}
      data-expansion-key={data.instanceKey}
      disabled={!target.canExpand}
      onPointerDown={(event) => event.stopPropagation()}
      onClick={expand}
    >Expand</button>}
    <Handle type="source" position={Position.Right} isConnectable={false} />
  </div>;
}

export { focusExpansionToggle };
