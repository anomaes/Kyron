import { useMemo, useState, type FormEvent } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, json } from "../api/client";
import { EmptyState } from "../components/EmptyState";
import type { Project, User, WorkflowListItem } from "../types";

type WorkflowResponse = { base_commit_sha: string; items: WorkflowListItem[] };

export function WorkflowListPage() {
  const { projectId = "" } = useParams();
  const navigate = useNavigate();
  const workflows = useQuery({ queryKey: ["workflows", projectId], queryFn: () => api<WorkflowResponse>(`/projects/${projectId}/workflows`) });
  const project = useQuery({ queryKey: ["project", projectId], queryFn: () => api<Project>(`/projects/${projectId}`) });
  const user = useQuery({ queryKey: ["me"], queryFn: () => api<User>("/auth/me") });
  const canControl = Boolean(project.data && user.data?.provider === project.data.provider);
  const [selected, setSelected] = useState<WorkflowListItem | null>(null);
  const [search, setSearch] = useState("");
  const [tag, setTag] = useState("");
  const [groupByTag, setGroupByTag] = useState(false);
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
  const tags = useMemo(() => Array.from(new Set(workflows.data?.items.flatMap((item) => item.tags) ?? [])).sort(), [workflows.data?.items]);
  const filtered = useMemo(() => { const term = search.trim().toLowerCase(); return (workflows.data?.items ?? []).filter((item) => (!tag || item.tags.includes(tag)) && (!term || [item.id, item.name, item.description, ...item.tags].some((value) => value.toLowerCase().includes(term)))); }, [search, tag, workflows.data?.items]);
  const groups = useMemo(() => { if (!groupByTag) return [{ name: "", items: filtered }]; const names = tag ? [tag] : Array.from(new Set(filtered.flatMap((item) => item.tags.length ? item.tags : ["untagged"]))).sort(); return names.map((name) => ({ name, items: filtered.filter((item) => name === "untagged" ? !item.tags.length : item.tags.includes(name)) })); }, [filtered, groupByTag, tag]);
  const workflowRows = (items: WorkflowListItem[]) => <div className="workflow-list">{items.map((item) => <article className="workflow-row" key={item.id}><div className={`node-glyph type-${item.nodes[0]?.type ?? "bash"}`}>◈</div><div className="workflow-copy"><h2>{item.name}</h2><p>{item.description || "No description"}</p><span className="mono">{item.id}</span>{item.tags.length > 0 && <div className="tag-list">{item.tags.map((itemTag) => <button key={itemTag} className="tag-chip" onClick={() => setTag(itemTag)}>{itemTag}</button>)}</div>}</div><div className="workflow-stats"><strong>{item.node_count}</strong><span>nodes</span></div><div className="workflow-actions"><button className="secondary" disabled={!canControl} title={!canControl ? `Sign in with ${project.data?.provider ?? "the project provider"} to run` : undefined} onClick={() => setSelected(item)}>Run</button>{canControl && <Link className="button ghost" to={`/projects/${projectId}/workflows/${item.id}/edit`}>Edit</Link>}</div></article>)}</div>;
  return <section><header className="page-header"><div><p className="eyebrow"><Link to="/projects">Projects</Link> / workflow catalog</p><h1>Workflows</h1><p>Definitions are loaded from the repository’s exact default-branch revision.</p></div>{canControl && <Link className="button" to={`/projects/${projectId}/workflows/new`}>New workflow</Link>}</header>
    {workflows.data && <div className="revision-strip"><span>Catalog revision</span><code>{workflows.data.base_commit_sha}</code></div>}
    {workflows.data?.items.length ? <><div className="workflow-toolbar"><label><span>Search</span><input type="search" value={search} placeholder="Name, ID, description, or tag…" onChange={(event) => setSearch(event.target.value)} /></label><label><span>Tag</span><select value={tag} onChange={(event) => setTag(event.target.value)}><option value="">All tags</option>{tags.map((itemTag) => <option key={itemTag} value={itemTag}>{itemTag}</option>)}</select></label><label className="group-toggle"><input type="checkbox" checked={groupByTag} onChange={(event) => setGroupByTag(event.target.checked)} />Group by tag</label></div>{filtered.length ? <div className="workflow-groups">{groups.map((group) => <section key={group.name || "all"}>{group.name && <header className="workflow-group-title"><h2>{group.name}</h2><span>{group.items.length} workflow{group.items.length === 1 ? "" : "s"}</span></header>}{workflowRows(group.items)}</section>)}</div> : <EmptyState title="No matching workflows">Adjust the search term or tag filter.</EmptyState>}</> : <EmptyState title="No merged workflows">Create a workflow definition and merge its code-host review.</EmptyState>}
    {selected && <div className="modal-backdrop"><form className="modal" onSubmit={submit}><h2>Run {selected.name}</h2><label>Base ref<input name="base_ref" defaultValue="main" /></label>{Object.entries(selected.inputs).map(([name, definition]) => <label key={name}>{name}{definition.required && " *"}<input name={name} type={definition.type === "integer" ? "number" : "text"} required={definition.required} defaultValue={String(definition.default ?? "")} /></label>)}{trigger.error && <p className="error">{trigger.error.message}</p>}<footer><button type="button" className="secondary" onClick={() => setSelected(null)}>Cancel</button><button disabled={trigger.isPending}>Trigger run</button></footer></form></div>}
  </section>;
}
