import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Background, Controls, ReactFlow, type Edge, type Node } from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { Link, useOutletContext, useParams } from "react-router-dom";
import { api, json } from "../api/client";
import { StatusBadge } from "../components/StatusBadge";
import { useRunLogs } from "../hooks/useRunLogs";
import type { Run, RunGraph, User } from "../types";

const terminalStates = new Set(["COMPLETED", "CANCELLED"]);

export function RunDetailPage() {
  const { runId = "" } = useParams(); const client = useQueryClient();
  const { user } = useOutletContext<{ user?: User }>();
  const run = useQuery({ queryKey: ["run", runId], queryFn: () => api<Run>(`/runs/${runId}`), refetchInterval: 3000 });
  const graph = useQuery({ queryKey: ["run-graph", runId], queryFn: () => api<RunGraph>(`/runs/${runId}/graph`), refetchInterval: 3000 });
  const logs = useRunLogs(runId, terminalStates.has(run.data?.status ?? ""));
  const [feedback, setFeedback] = useState("");
  const action = useMutation({ mutationFn: ({ path, body }: { path: string; body?: unknown }) => api(`/runs/${runId}/${path}`, body ? json("POST", body) : { method: "POST" }), onSuccess: () => { setFeedback(""); void client.invalidateQueries({ queryKey: ["run", runId] }); } });
  const root = graph.data?.snapshot.workflows[graph.data.snapshot.root_workflow_id];
  const executionByNode = useMemo(() => new Map(graph.data?.nodes.filter((node) => node.invocation_id === graph.data?.invocations.find((item) => item.invocation_path === "root")?.id).map((node) => [String(node.node_id), String(node.status)]) ?? []), [graph.data]);
  const nodes: Node[] = root?.nodes.map((node) => ({ id: node.id, position: node.position, data: { label: <div className="run-node"><span>{node.type.replaceAll("_", " ")}</span><strong>{node.label}</strong><StatusBadge status={executionByNode.get(node.id) ?? "PENDING"} /></div> }, className: `run-flow-node status-${(executionByNode.get(node.id) ?? "PENDING").toLowerCase()}` })) ?? [];
  const edges: Edge[] = root?.edges.map((edge) => ({ id: edge.id, source: edge.source, target: edge.target, animated: true })) ?? [];
  const canControl = user?.id === run.data?.triggered_by;
  return <section>{run.data && <><header className="run-header"><div><Link to="/runs" className="eyebrow">← All runs</Link><h1>{run.data.root_workflow_id}</h1><div className="run-meta"><StatusBadge status={run.data.status} /><code>{run.data.id}</code></div></div><div className="run-actions">{run.data.mr_url && <a className="button secondary" href={run.data.mr_url} target="_blank" rel="noreferrer">Open MR ↗</a>}{["FAILED", "INTERRUPTED"].includes(run.data.status) && <button onClick={() => action.mutate({ path: "resume" })}>Resume</button>}{["QUEUED", "RUNNING", "RESUMING", "AWAITING_FEEDBACK"].includes(run.data.status) && <button className="danger" onClick={() => action.mutate({ path: "cancel" })}>Cancel</button>}</div></header><div className="run-summary"><div><span>Base</span><strong>{run.data.base_ref}</strong><code>{run.data.base_commit_sha.slice(0, 12)}</code></div><div><span>Run branch</span><strong className="mono">{run.data.branch_name ?? "Preparing…"}</strong></div><div><span>Current HEAD</span><code>{run.data.current_head_sha?.slice(0, 12) ?? "—"}</code></div><div><span>Started</span><strong>{run.data.started_at ? new Date(run.data.started_at).toLocaleString() : "Queued"}</strong></div></div></>}
    {run.data?.status === "AWAITING_FEEDBACK" && <div className="feedback-banner"><div><p className="eyebrow">Human checkpoint</p><h2>Review requested</h2><p>{canControl ? "Approve to continue, or describe what should change." : "Only the user who triggered this run can continue it."}</p></div>{canControl && <div className="feedback-controls"><textarea value={feedback} onChange={(event) => setFeedback(event.target.value)} placeholder="Request a revision…" /><button className="secondary" disabled={!feedback} onClick={() => action.mutate({ path: "feedback", body: { message: feedback } })}>Send feedback</button><button onClick={() => action.mutate({ path: "approve" })}>Approve & continue</button></div>}</div>}
    <div className="run-layout"><div className="panel graph-panel"><div className="panel-title"><h2>Workflow graph</h2><span>{graph.data?.nodes.length ?? 0} executions</span></div><div className="flow-canvas"><ReactFlow nodes={nodes} edges={edges} fitView nodesDraggable={false} nodesConnectable={false}><Background /><Controls showInteractive={false} /></ReactFlow></div></div><div className="panel log-panel"><div className="panel-title"><h2>Live stream</h2><span className="live-dot">live</span></div><div className="terminal">{logs.length ? logs.map((event, index) => <div className="log-line" key={`${event.sequence ?? index}-${index}`}><time>{event.timestamp?.slice(11, 19) ?? ""}</time><span className={`log-source ${event.source ?? event.level?.toLowerCase()}`}>{event.source ?? event.level ?? event.type}</span><pre>{event.line ?? event.message ?? event.event_type}</pre></div>) : <div className="terminal-empty">Waiting for engine output…</div>}</div></div></div>
    <div className="panel wave-panel"><div className="panel-title"><h2>Execution waves</h2><span>Git checkpoint boundaries</span></div><table><thead><tr><th>Wave</th><th>Status</th><th>Start SHA</th><th>End SHA</th><th>Started</th></tr></thead><tbody>{graph.data?.waves.map((wave) => <tr key={String(wave.id)}><td>#{String(wave.wave_index)}</td><td><StatusBadge status={String(wave.status)} /></td><td><code>{String(wave.start_commit_sha).slice(0, 10)}</code></td><td><code>{wave.end_commit_sha ? String(wave.end_commit_sha).slice(0, 10) : "—"}</code></td><td>{wave.started_at ? new Date(String(wave.started_at)).toLocaleString() : "—"}</td></tr>)}</tbody></table></div>
  </section>;
}
