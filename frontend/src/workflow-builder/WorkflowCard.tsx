import { Handle, Position, type NodeProps } from "@xyflow/react";
import type { BuilderNode } from "./store";

const icons = { bash: ">_", script: "Py", prompt: "✦", human_feedback: "◎", subworkflow: "◇", review_loop: "↻" };

export function WorkflowCard({ data, selected }: NodeProps<BuilderNode>) {
  const config = data.workflowNode.config;
  const preview = data.type === "bash" ? String(config.command ?? "") : data.type === "prompt" ? String(config.prompt ?? "") : data.type === "script" ? String(config.script ?? "") : data.type === "subworkflow" ? String(config.workflow_id ?? "") : data.type === "review_loop" ? `${String(config.initial_workflow_id ?? "")} · ${String(config.approval_policy ?? "no policy")}` : `Policy: ${String(config.approval_policy ?? "not selected")}`;
  return <div className={`builder-node type-${data.type} ${selected ? "selected" : ""}`}><Handle type="target" position={Position.Top} /><div className="builder-node-head"><span>{icons[data.type]}</span><small>{data.type.replaceAll("_", " ")}</small>{data.workflowNode.join === "or" && <b>OR</b>}</div><strong>{data.label}</strong><p>{preview}</p><Handle type="source" position={Position.Bottom} /></div>;
}
