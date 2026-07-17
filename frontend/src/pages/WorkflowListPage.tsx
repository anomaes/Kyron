import { useState, type FormEvent } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, json } from "../api/client";
import { EmptyState } from "../components/EmptyState";
import type { WorkflowListItem } from "../types";

type WorkflowResponse = { base_commit_sha: string; items: WorkflowListItem[] };

export function WorkflowListPage() {
  const { projectId = "" } = useParams();
  const navigate = useNavigate();
  const workflows = useQuery({ queryKey: ["workflows", projectId], queryFn: () => api<WorkflowResponse>(`/projects/${projectId}/workflows`) });
  const [selected, setSelected] = useState<WorkflowListItem | null>(null);
  const trigger = useMutation({ mutationFn: (request: { workflow: string; body: unknown }) => api<{ run_id: string }>(`/projects/${projectId}/workflows/${request.workflow}/runs`, json("POST", request.body)), onSuccess: (run) => navigate(`/runs/${run.run_id}`) });
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (!selected) return;
    const data = new FormData(event.currentTarget); const inputs: Record<string, unknown> = {};
    for (const [name, definition] of Object.entries(selected.inputs)) {
      const raw = data.get(name); if (raw === null || raw === "") continue;
      inputs[name] = definition.type === "integer" ? Number(raw) : definition.type === "boolean" ? raw === "true" : raw;
    }
    trigger.mutate({ workflow: selected.id, body: { base_ref: data.get("base_ref") || "main", inputs } });
  }
  return <section><header className="page-header"><div><p className="eyebrow"><Link to="/projects">Projects</Link> / workflow catalog</p><h1>Workflows</h1><p>Definitions are loaded from the repository’s exact default-branch revision.</p></div><Link className="button" to={`/projects/${projectId}/workflows/new`}>New workflow</Link></header>
    {workflows.data && <div className="revision-strip"><span>Catalog revision</span><code>{workflows.data.base_commit_sha}</code></div>}
    {workflows.data?.items.length ? <div className="workflow-list">{workflows.data.items.map((item) => <article className="workflow-row" key={item.id}><div className={`node-glyph type-${item.nodes[0]?.type ?? "bash"}`}>◈</div><div className="workflow-copy"><h2>{item.name}</h2><p>{item.description || "No description"}</p><span className="mono">{item.id}</span></div><div className="workflow-stats"><strong>{item.node_count}</strong><span>nodes</span></div><div className="workflow-actions"><button className="secondary" onClick={() => setSelected(item)}>Run</button><Link className="button ghost" to={`/projects/${projectId}/workflows/${item.id}/edit`}>Edit</Link></div></article>)}</div> : <EmptyState title="No merged workflows">Create a workflow definition and merge its GitLab review.</EmptyState>}
    {selected && <div className="modal-backdrop"><form className="modal" onSubmit={submit}><h2>Run {selected.name}</h2><label>Base ref<input name="base_ref" defaultValue="main" /></label>{Object.entries(selected.inputs).map(([name, definition]) => <label key={name}>{name}{definition.required && " *"}<input name={name} type={definition.type === "integer" ? "number" : "text"} required={definition.required} defaultValue={String(definition.default ?? "")} /></label>)}{trigger.error && <p className="error">{trigger.error.message}</p>}<footer><button type="button" className="secondary" onClick={() => setSelected(null)}>Cancel</button><button disabled={trigger.isPending}>Trigger run</button></footer></form></div>}
  </section>;
}
