import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { EmptyState } from "../components/EmptyState";
import { StatusBadge } from "../components/StatusBadge";
import type { Run } from "../types";

type RunsResponse = { items: Run[]; total: number };
const active = new Set(["QUEUED", "RUNNING", "RESUMING", "AWAITING_FEEDBACK"]);

export function RunsPage() {
  const runs = useQuery({ queryKey: ["runs"], queryFn: () => api<RunsResponse>("/runs?page_size=100"), refetchInterval: (query) => query.state.data?.items.some((run) => active.has(run.status)) ? 3000 : 10000 });
  return <section><header className="page-header"><div><p className="eyebrow">Execution history</p><h1>Runs</h1><p>Every run is pinned to an exact commit and preserves its attempt history.</p></div></header>
    {runs.data?.items.length ? <div className="table-card"><table><thead><tr><th>Status</th><th>Workflow</th><th>Base revision</th><th>Triggered by</th><th>Started</th><th>Current</th><th>Review</th></tr></thead><tbody>{runs.data.items.map((run) => <tr key={run.id}><td><StatusBadge status={run.status} /></td><td><Link to={`/runs/${run.id}`}><strong>{run.root_workflow_id}</strong><small className="mono block">{run.id.slice(0, 8)}</small></Link></td><td><span>{run.base_ref}</span><code className="block">{run.base_commit_sha.slice(0, 10)}</code></td><td>@{run.reviewer_provider_username}</td><td>{run.started_at ? new Date(run.started_at).toLocaleString() : "Queued"}</td><td className="mono">{run.current_node_execution_id?.slice(0, 8) ?? "—"}</td><td>{run.change_request_url ? <a href={run.change_request_url} target="_blank" rel="noreferrer">{run.reviewer_provider === "gitlab" ? "!" : "#"}{run.change_request_number}</a> : "—"}</td></tr>)}</tbody></table></div> : <EmptyState title="No workflow runs yet">Trigger a merged workflow from its project catalog.</EmptyState>}
  </section>;
}
