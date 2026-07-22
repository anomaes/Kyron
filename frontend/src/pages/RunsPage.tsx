import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { EmptyState } from "../components/EmptyState";
import { StatusBadge } from "../components/StatusBadge";
import type { ProjectAccess, Run } from "../types";

type RunsResponse = { items: Run[]; total: number };
const active = new Set(["QUEUED", "RUNNING", "RESUMING", "AWAITING_FEEDBACK"]);
const deletable = new Set(["COMPLETED", "FAILED", "INTERRUPTED", "CANCELLED"]);

function RunRow({ run }: { run: Run }) {
  const client = useQueryClient();
  const access = useQuery({ queryKey: ["project-access", run.project_id], enabled: deletable.has(run.status), queryFn: () => api<ProjectAccess>(`/projects/${run.project_id}/access`) });
  const remove = useMutation({ mutationFn: () => api(`/runs/${run.id}`, { method: "DELETE" }), onSuccess: () => { client.removeQueries({ queryKey: ["run", run.id] }); void client.invalidateQueries({ queryKey: ["runs"] }); } });
  const canDelete = Boolean(access.data?.permissions.includes("run.delete") && deletable.has(run.status));
  const confirmDelete = () => {
    if (window.confirm(`Permanently delete ${run.root_workflow_id} run ${run.id.slice(0, 8)} and all of its local resources?`)) remove.mutate();
  };
  return <tr><td><StatusBadge status={run.status} /></td><td><Link to={`/runs/${run.id}`}><strong>{run.root_workflow_id}</strong>{run.local_definition_test && <small className="block">Local test</small>}<small className="mono block">{run.id.slice(0, 8)}</small></Link></td><td><span>{run.base_ref}</span><code className="block">{run.base_commit_sha.slice(0, 10)}</code></td><td>@{run.reviewer_provider_username}</td><td>{run.started_at ? new Date(run.started_at).toLocaleString() : "Queued"}</td><td className="mono">{run.current_node_execution_id?.slice(0, 8) ?? "—"}</td><td>{run.change_request_url ? <a href={run.change_request_url} target="_blank" rel="noreferrer">{run.reviewer_provider === "gitlab" ? "!" : "#"}{run.change_request_number}</a> : run.local_definition_test ? "Local only" : "—"}</td><td>{canDelete && <button className="danger" disabled={remove.isPending} onClick={confirmDelete}>{remove.isPending ? "Deleting…" : "Delete"}</button>}{remove.error && <small className="error block">{remove.error.message}</small>}</td></tr>;
}

export function RunsPage() {
  const runs = useQuery({ queryKey: ["runs"], queryFn: () => api<RunsResponse>("/runs?page_size=100"), refetchInterval: (query) => query.state.data?.items.some((run) => active.has(run.status)) ? 3000 : 10000 });
  return <section><header className="page-header"><div><p className="eyebrow">Execution history</p><h1>Runs</h1><p>Runs are pinned to exact commits and retain attempt history until an authorized deletion.</p></div></header>
    {runs.data?.items.length ? <div className="table-card"><table><thead><tr><th>Status</th><th>Workflow</th><th>Base revision</th><th>Triggered by</th><th>Started</th><th>Current</th><th>Review</th><th>Actions</th></tr></thead><tbody>{runs.data.items.map((run) => <RunRow key={run.id} run={run} />)}</tbody></table></div> : <EmptyState title="No workflow runs yet">Trigger a workflow from its project catalog.</EmptyState>}
  </section>;
}
