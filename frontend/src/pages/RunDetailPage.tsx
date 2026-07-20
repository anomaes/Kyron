import { useMemo, useState, type ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Background, Controls, ReactFlow, type Edge, type Node } from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { Link, useOutletContext, useParams } from "react-router-dom";
import { api, json } from "../api/client";
import { StatusBadge } from "../components/StatusBadge";
import { useRunLogs } from "../hooks/useRunLogs";
import type { ProjectAccess, Run, RunGraph, RunReport, User } from "../types";

const terminalStates = new Set(["COMPLETED", "CANCELLED"]);

function RunNodeLabel({ type, label, status }: { type: string; label: string; status: string }) {
  return <div className="run-flow-node"><span>{type.replaceAll("_", " ")}</span><strong>{label}</strong><StatusBadge status={status} /></div>;
}

function buildExpandedGraph(graph: RunGraph): { nodes: Node[]; edges: Edge[] } {
  const invocations = [...graph.invocations].sort((left, right) => {
    const depth = left.invocation_path.split("/").length - right.invocation_path.split("/").length;
    if (depth) return depth;
    const parent = String(left.parent_node_execution_id).localeCompare(String(right.parent_node_execution_id));
    return parent || left.loop_iteration - right.loop_iteration || left.invocation_path.localeCompare(right.invocation_path);
  });
  const executions = new Map(graph.nodes.map((execution) => [execution.id, execution]));
  const executionByNode = new Map(graph.nodes.map((execution) => [`${execution.invocation_id}:${execution.node_id}`, execution]));
  const childrenByParent = new Map<string, typeof invocations>();
  for (const invocation of invocations.filter((item) => item.parent_node_execution_id)) {
    const siblings = childrenByParent.get(invocation.parent_node_execution_id!) ?? [];
    siblings.push(invocation); childrenByParent.set(invocation.parent_node_execution_id!, siblings);
  }
  for (const siblings of childrenByParent.values()) siblings.sort((left, right) => left.loop_iteration - right.loop_iteration || left.invocation_path.localeCompare(right.invocation_path));
  const feedbackForIteration = new Map(graph.feedback.filter((item) => item.event_type === "comment").map((item) => [`${item.node_execution_id}:${item.iteration + 1}`, item.message]));
  const rootInvocation = invocations.find((item) => item.invocation_path === "root");
  const rootDefinition = rootInvocation ? graph.snapshot.workflows[rootInvocation.workflow_id] : undefined;
  const rootBottom = Math.max(0, ...(rootDefinition?.nodes.map((node) => node.position.y) ?? [])) + 190;
  const flowNodes: Node[] = [];
  const flowEdges: Edge[] = [];
  let childX = 40;

  for (const invocation of invocations) {
    const definition = graph.snapshot.workflows[invocation.workflow_id];
    if (!definition) continue;
    const isRoot = invocation.id === rootInvocation?.id;
    const minX = Math.min(0, ...definition.nodes.map((node) => node.position.x));
    const maxX = Math.max(0, ...definition.nodes.map((node) => node.position.x));
    const minY = Math.min(0, ...definition.nodes.map((node) => node.position.y));
    const blockWidth = Math.max(260, maxX - minX + 230);
    const offsetX = isRoot ? 0 : childX;
    const offsetY = isRoot ? 0 : rootBottom;
    const headerId = `invocation:${invocation.id}`;
    if (!isRoot) {
      const feedback = feedbackForIteration.get(`${invocation.parent_node_execution_id}:${invocation.loop_iteration}`);
      const isReviewIteration = /\/(initial|revision)\[\d+\]$/.test(invocation.invocation_path);
      const headerLabel: ReactNode = <div className="invocation-card"><span>{isReviewIteration ? `Review iteration ${invocation.loop_iteration}` : "Child invocation"}</span><strong>{definition.name}</strong><code>{invocation.invocation_path}</code>{feedback && <p title={feedback}>↳ {feedback}</p>}<StatusBadge status={invocation.status} /></div>;
      flowNodes.push({ id: headerId, position: { x: offsetX, y: offsetY }, data: { label: headerLabel }, className: "invocation-summary", draggable: false });
      const siblings = childrenByParent.get(invocation.parent_node_execution_id ?? "") ?? [];
      const siblingIndex = siblings.findIndex((item) => item.id === invocation.id);
      const previous = siblingIndex > 0 ? siblings[siblingIndex - 1] : undefined;
      const parentExecution = invocation.parent_node_execution_id ? executions.get(invocation.parent_node_execution_id) : undefined;
      const source = previous ? `invocation:${previous.id}` : parentExecution ? `${parentExecution.invocation_id}:${parentExecution.node_id}` : undefined;
      if (source) flowEdges.push({ id: `control:${source}:${headerId}`, source, target: headerId, label: previous ? "feedback" : "invoke", type: "smoothstep", animated: invocation.status === "RUNNING" });
    }
    for (const workflowNode of definition.nodes) {
      const execution = executionByNode.get(`${invocation.id}:${workflowNode.id}`);
      flowNodes.push({ id: `${invocation.id}:${workflowNode.id}`, position: isRoot ? workflowNode.position : { x: offsetX + workflowNode.position.x - minX, y: offsetY + 115 + workflowNode.position.y - minY }, data: { label: <RunNodeLabel type={workflowNode.type} label={workflowNode.label} status={execution?.status ?? "PENDING"} /> }, className: `status-${(execution?.status ?? "PENDING").toLowerCase()}`, draggable: false });
    }
    for (const edge of definition.edges) flowEdges.push({ id: `${invocation.id}:${edge.id}`, source: `${invocation.id}:${edge.source}`, target: `${invocation.id}:${edge.target}`, animated: true, type: "smoothstep" });
    if (!isRoot) {
      const targets = new Set(definition.edges.map((edge) => edge.target));
      for (const start of definition.nodes.filter((node) => !targets.has(node.id))) flowEdges.push({ id: `${headerId}:start:${start.id}`, source: headerId, target: `${invocation.id}:${start.id}`, type: "smoothstep" });
      childX += blockWidth + 70;
    }
  }
  return { nodes: flowNodes, edges: flowEdges };
}

export function RunDetailPage() {
  const { runId = "" } = useParams(); const client = useQueryClient();
  const { user } = useOutletContext<{ user?: User }>();
  const run = useQuery({ queryKey: ["run", runId], queryFn: () => api<Run>(`/runs/${runId}`), refetchInterval: 3000 });
  const graph = useQuery({ queryKey: ["run-graph", runId], queryFn: () => api<RunGraph>(`/runs/${runId}/graph`), refetchInterval: 3000 });
  const report = useQuery({ queryKey: ["run-report", runId], queryFn: () => api<RunReport>(`/runs/${runId}/report`), refetchInterval: terminalStates.has(run.data?.status ?? "") ? false : 5000 });
  const access = useQuery({ queryKey: ["project-access", run.data?.project_id], enabled: Boolean(run.data?.project_id), queryFn: () => api<ProjectAccess>(`/projects/${run.data?.project_id}/access`) });
  const logs = useRunLogs(runId, terminalStates.has(run.data?.status ?? ""));
  const [feedback, setFeedback] = useState("");
  const action = useMutation({ mutationFn: ({ path, body }: { path: string; body?: unknown }) => api(`/runs/${runId}/${path}`, body ? json("POST", body) : { method: "POST" }), onSuccess: () => { setFeedback(""); void client.invalidateQueries({ queryKey: ["run", runId] }); void client.invalidateQueries({ queryKey: ["run-graph", runId] }); void client.invalidateQueries({ queryKey: ["run-report", runId] }); } });
  const expandedGraph = useMemo(() => graph.data ? buildExpandedGraph(graph.data) : { nodes: [], edges: [] }, [graph.data]);
  const providerMatches = user?.provider === run.data?.reviewer_provider;
  const canOperateRun = providerMatches && Boolean(
    access.data?.permissions.includes("run.control.any") ||
    (access.data?.permissions.includes("run.control.own") && user?.id === run.data?.triggered_by),
  );
  const currentGate = graph.data?.gates.find((gate) => gate.status === "OPEN" && gate.node_execution_id === run.data?.current_node_execution_id);
  const canControl = Boolean(currentGate?.eligible_snapshot.requirements.some((requirement) => requirement.users.some((actor) => actor.provider === user?.provider && actor.provider_user_id === user?.provider_user_id)));
  const gateDecisions = graph.data?.gate_decisions.filter((decision) => decision.gate_instance_id === currentGate?.id) ?? [];
  const approvalCount = gateDecisions.filter((decision) => decision.event_type === "approval").length;
  return <section>{run.data && <><header className="run-header"><div><Link to="/runs" className="eyebrow">← All runs</Link><h1>{run.data.root_workflow_id}</h1><div className="run-meta"><StatusBadge status={run.data.status} />{run.data.local_definition_test && <span className="review-badge">Local definition test</span>}<code>{run.data.id}</code></div></div><div className="run-actions">{run.data.change_request_url && <a className="button secondary" href={run.data.change_request_url} target="_blank" rel="noreferrer">Open {run.data.reviewer_provider === "github" ? "PR" : "MR"} ↗</a>}{canOperateRun && ["FAILED", "INTERRUPTED"].includes(run.data.status) && <button onClick={() => action.mutate({ path: "resume" })}>Resume</button>}{canOperateRun && ["QUEUED", "RUNNING", "RESUMING", "AWAITING_FEEDBACK"].includes(run.data.status) && <button className="danger" onClick={() => action.mutate({ path: "cancel" })}>Cancel</button>}</div></header><div className="run-summary"><div><span>Base</span><strong>{run.data.base_ref}</strong><code>{run.data.base_commit_sha.slice(0, 12)}</code></div><div><span>Run branch</span><strong className="mono">{run.data.branch_name ?? "Preparing…"}</strong></div><div><span>Current HEAD</span><code>{run.data.current_head_sha?.slice(0, 12) ?? "—"}</code></div><div><span>Started</span><strong>{run.data.started_at ? new Date(run.data.started_at).toLocaleString() : "Queued"}</strong></div></div>{run.data.local_definition_test && <div className="feedback-banner"><div><p className="eyebrow">Local-only run</p><h2>Code-host push is disabled</h2><p>This run tests the exact local definition snapshot. Its worktree and results stay on the Kyron host.</p></div></div>}</>}
    {run.data?.status === "AWAITING_FEEDBACK" && <div className="feedback-banner"><div><p className="eyebrow">Governed human checkpoint</p><h2>{currentGate?.policy_snapshot.name ?? "Review requested"}</h2><p>{canControl ? "You are eligible to approve or request a revision." : "This gate is waiting for its configured approval policy."} {approvalCount > 0 && `${approvalCount} approval${approvalCount === 1 ? "" : "s"} recorded.`}</p><code>{currentGate?.checkpoint_commit_sha.slice(0, 12)}</code></div><div className="feedback-controls">{canControl && <><textarea value={feedback} onChange={(event) => setFeedback(event.target.value)} placeholder="Request a revision…" /><button className="secondary" disabled={!feedback} onClick={() => action.mutate({ path: "feedback", body: { message: feedback } })}>Send feedback</button><button onClick={() => action.mutate({ path: "approve" })}>Record approval</button></>}{access.data?.permissions.includes("gate.override") && <button className="danger" onClick={() => { const reason = window.prompt("Reason for overriding this gate"); if (reason) action.mutate({ path: "override-gate", body: { reason } }); }}>Override</button>}</div></div>}
    <div className="run-layout"><div className="panel graph-panel"><div className="panel-title"><h2>Workflow graph</h2><span>{graph.data?.invocations.length ?? 0} invocation{graph.data?.invocations.length === 1 ? "" : "s"} · {graph.data?.nodes.length ?? 0} executions</span></div><div className="flow-canvas expanded"><ReactFlow nodes={expandedGraph.nodes} edges={expandedGraph.edges} fitView nodesDraggable={false} nodesConnectable={false}><Background /><Controls showInteractive={false} /></ReactFlow></div></div><div className="panel log-panel"><div className="panel-title"><h2>Live stream</h2><span className="live-dot">live</span></div><div className="terminal">{logs.length ? logs.map((event, index) => <div className="log-line" key={`${event.sequence ?? index}-${index}`}><time>{event.timestamp?.slice(11, 19) ?? ""}</time><span className={`log-source ${event.source ?? event.level?.toLowerCase()}`}>{event.source ?? event.level ?? event.type}</span><pre>{event.line ?? event.message ?? event.event_type}</pre></div>) : <div className="terminal-empty">Waiting for engine output…</div>}</div></div></div>
    <div className="panel wave-panel"><div className="panel-title"><h2>Execution waves</h2><span>Git checkpoint boundaries</span></div><table><thead><tr><th>Wave</th><th>Status</th><th>Start SHA</th><th>End SHA</th><th>Started</th></tr></thead><tbody>{graph.data?.waves.map((wave) => <tr key={String(wave.id)}><td>#{String(wave.wave_index)}</td><td><StatusBadge status={String(wave.status)} /></td><td><code>{String(wave.start_commit_sha).slice(0, 10)}</code></td><td><code>{wave.end_commit_sha ? String(wave.end_commit_sha).slice(0, 10) : "—"}</code></td><td>{wave.started_at ? new Date(String(wave.started_at)).toLocaleString() : "—"}</td></tr>)}</tbody></table></div>
    <div className="panel report-panel"><div className="panel-title"><h2>Traceability report</h2><span>{report.data?.frozen ? "Final execution record" : "Live audit record"}</span></div><div className="report-summary"><div><span>Triggered by</span><strong>{String((report.data?.run.triggered_by as Record<string, unknown> | undefined)?.display_name ?? "—")}</strong></div><div><span>Definition</span><code>{String(report.data?.run.workflow_definition_commit_sha ?? "—").slice(0, 12)}</code></div><div><span>Gates</span><strong>{report.data?.gates.length ?? 0}</strong></div><div><span>Result</span><StatusBadge status={String(report.data?.run.status ?? "PENDING")} /></div></div>{report.data?.gates.map((gate) => <article className="report-gate" key={gate.id}><header><div><small>{gate.invocation_path}</small><h3>{gate.policy_snapshot.name} · {gate.node_id}</h3></div><StatusBadge status={gate.status} /></header><p>Checkpoint <code>{gate.checkpoint_commit_sha.slice(0, 12)}</code> · opened {new Date(gate.opened_at).toLocaleString()}</p>{gate.policy_snapshot.requirements.map((requirement) => <div className="report-requirement" key={requirement.key}><strong>{requirement.name}</strong><span>Quorum {requirement.quorum}</span></div>)}{gate.decisions.map((decision) => <div className={`report-decision ${decision.superseded ? "superseded" : ""}`} key={decision.id}><strong>{decision.event_type}</strong><span>{decision.actor_snapshot.display_name ?? decision.actor_snapshot.provider_username}</span><time>{new Date(decision.created_at).toLocaleString()}</time>{decision.message && <p>{decision.message}</p>}</div>)}</article>)}{report.data?.post_run_lifecycle.map((event, index) => <p className="lifecycle-event" key={index}>Post-run: {String(event.event_type)} by @{String(event.actor_username)}</p>)}</div>
  </section>;
}
