import { useMemo, useState, type FormEvent, type ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, json } from "../api/client";
import { EmptyState } from "../components/EmptyState";
import type { DefinitionChangeStatus, Project, ProjectAccess, User, WorkflowListItem } from "../types";

type WorkflowResponse = DefinitionChangeStatus & { base_commit_sha: string; items: WorkflowListItem[] };
type WorkflowFolder = { name: string; path: string; items: WorkflowListItem[]; children: Map<string, WorkflowFolder> };

function buildFolderTree(items: WorkflowListItem[]): WorkflowFolder {
  const root: WorkflowFolder = { name: ".workflowEngine", path: "", items: [], children: new Map() };
  for (const workflow of items) {
    let folder = root;
    for (const name of workflow.folder_path.split("/").filter(Boolean)) {
      const path = folder.path ? `${folder.path}/${name}` : name;
      let child = folder.children.get(name);
      if (!child) { child = { name, path, items: [], children: new Map() }; folder.children.set(name, child); }
      folder = child;
    }
    folder.items.push(workflow);
  }
  return root;
}

function folderWorkflowCount(folder: WorkflowFolder): number {
  return folder.items.length + Array.from(folder.children.values()).reduce((total, child) => total + folderWorkflowCount(child), 0);
}

function FolderTree({ folder, renderRows, root = false }: { folder: WorkflowFolder; renderRows: (items: WorkflowListItem[]) => ReactNode; root?: boolean }) {
  const children = Array.from(folder.children.values()).sort((left, right) => left.name.localeCompare(right.name));
  return <section className={root ? "workflow-folder-root" : "workflow-folder-branch"}><header className="workflow-folder-title"><h2><span>▾</span>{folder.name}{root && "/"}</h2><small>{folderWorkflowCount(folder)} workflow{folderWorkflowCount(folder) === 1 ? "" : "s"}</small></header>{folder.items.length > 0 && renderRows(folder.items)}{children.map((child) => <FolderTree key={child.path} folder={child} renderRows={renderRows} />)}</section>;
}

export function WorkflowListPage() {
  const { projectId = "" } = useParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const workflows = useQuery({ queryKey: ["workflows", projectId], queryFn: () => api<WorkflowResponse>(`/projects/${projectId}/workflows`) });
  const project = useQuery({ queryKey: ["project", projectId], queryFn: () => api<Project>(`/projects/${projectId}`) });
  const access = useQuery({ queryKey: ["project-access", projectId], queryFn: () => api<ProjectAccess>(`/projects/${projectId}/access`) });
  const user = useQuery({ queryKey: ["me"], queryFn: () => api<User>("/auth/me") });
  const usesProjectProvider = Boolean(project.data && user.data?.provider === project.data.provider);
  const canEdit = usesProjectProvider && Boolean(access.data?.permissions.includes("workflow.edit"));
  const canPublish = usesProjectProvider && Boolean(access.data?.permissions.includes("workflow.publish"));
  const canTrigger = usesProjectProvider && Boolean(access.data?.permissions.includes("run.trigger"));
  const [selected, setSelected] = useState<WorkflowListItem | null>(null);
  const [search, setSearch] = useState("");
  const [tag, setTag] = useState("");
  const [groupByTag, setGroupByTag] = useState(false);
  const [reviewUrl, setReviewUrl] = useState<string | null>(null);
  const trigger = useMutation({ mutationFn: (request: { workflow: string; body: unknown }) => api<{ run_id: string }>(`/projects/${projectId}/workflows/${request.workflow}/runs`, json("POST", request.body)), onSuccess: (run) => navigate(`/runs/${run.run_id}`) });
  const createReview = useMutation({
    mutationFn: () => api<{ change_request_url: string }>(`/projects/${projectId}/workflows/changes/review`, json("POST", { expected_base_commit_sha: workflows.data?.base_commit_sha })),
    onSuccess: (result) => {
      setReviewUrl(result.change_request_url);
      void queryClient.invalidateQueries({ queryKey: ["workflows", projectId] });
      void queryClient.invalidateQueries({ queryKey: ["workflow-templates", projectId] });
    },
  });
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (!selected) return;
    const data = new FormData(event.currentTarget); const inputs: Record<string, unknown> = {};
    for (const [name, definition] of Object.entries(selected.inputs)) {
      const raw = data.get(name); if (raw === null || raw === "") continue;
      inputs[name] = definition.type === "integer" ? Number(raw) : definition.type === "boolean" ? raw === "true" : raw;
    }
    trigger.mutate({ workflow: selected.id, body: { base_ref: data.get("base_ref") || project.data?.default_branch || "main", inputs, use_local_definitions: data.get("use_local_definitions") === "on" } });
  }
  const tags = useMemo(() => Array.from(new Set(workflows.data?.items.flatMap((item) => item.tags) ?? [])).sort(), [workflows.data?.items]);
  const filtered = useMemo(() => { const term = search.trim().toLowerCase(); return (workflows.data?.items ?? []).filter((item) => (!tag || item.tags.includes(tag)) && (!term || [item.id, item.name, item.description, item.folder_path, ...item.tags].some((value) => value.toLowerCase().includes(term)))); }, [search, tag, workflows.data?.items]);
  const folderTree = useMemo(() => buildFolderTree(filtered), [filtered]);
  const tagGroups = useMemo(() => { const names = tag ? [tag] : Array.from(new Set(filtered.flatMap((item) => item.tags.length ? item.tags : ["untagged"]))).sort(); return names.map((name) => ({ name, items: filtered.filter((item) => name === "untagged" ? !item.tags.length : item.tags.includes(name)) })); }, [filtered, tag]);
  const workflowRows = (items: WorkflowListItem[]) => <div className="workflow-list">{items.map((item) => <article className="workflow-row" key={item.id}><div className={`node-glyph type-${item.nodes[0]?.type ?? "bash"}`}>◈</div><div className="workflow-copy"><h2>{item.name}</h2><p>{item.description || "No description"}</p><span className="mono">{item.id}</span>{item.tags.length > 0 && <div className="tag-list">{item.tags.map((itemTag) => <button key={itemTag} className="tag-chip" onClick={() => setTag(itemTag)}>{itemTag}</button>)}</div>}</div><div className="workflow-stats"><strong>{item.node_count}</strong><span>nodes</span></div><div className="workflow-actions"><button className="secondary" disabled={!canTrigger} title={!usesProjectProvider ? `Sign in with ${project.data?.provider ?? "the project provider"} to run` : !canTrigger ? "Your project role cannot trigger workflows" : undefined} onClick={() => setSelected(item)}>Run</button>{canEdit && <Link className="button ghost" to={`/projects/${projectId}/workflows/${item.id}/edit`}>Edit</Link>}</div></article>)}</div>;
  const localChanges = (workflows.data?.outgoing_changes ?? 0) + (workflows.data?.in_review_changes ?? 0);
  return <section><header className="page-header"><div><p className="eyebrow"><Link to="/projects">Projects</Link> / workflow catalog</p><h1>Workflows</h1><p>Build and test project-local definitions, then send the batch for code review when it is ready.</p></div><div className="page-actions">{canEdit && <Link className="button secondary" to={`/projects/${projectId}/workflows/new`}>New workflow</Link>}{canPublish && <button disabled={!workflows.data?.outgoing_changes || createReview.isPending} onClick={() => createReview.mutate()}>Create review {workflows.data?.outgoing_changes ? `(${workflows.data.outgoing_changes})` : ""}</button>}</div></header>
    {workflows.data && <div className="revision-strip"><span>Base revision</span><code>{workflows.data.base_commit_sha}</code>{workflows.data.outgoing_changes > 0 && <span className="outgoing-badge">↑ {workflows.data.outgoing_changes} outgoing</span>}{workflows.data.in_review_changes > 0 && <span className="review-badge">◎ {workflows.data.in_review_changes} in review</span>}{workflows.data.change_request_url && <a href={workflows.data.change_request_url} target="_blank" rel="noreferrer">Open review ↗</a>}</div>}
    {createReview.error && <p className="error">{createReview.error.message}</p>}
    {workflows.data?.items.length ? <><div className="workflow-toolbar"><label><span>Search</span><input type="search" value={search} placeholder="Name, ID, folder, description, or tag…" onChange={(event) => setSearch(event.target.value)} /></label><label><span>Tag</span><select value={tag} onChange={(event) => setTag(event.target.value)}><option value="">All tags</option>{tags.map((itemTag) => <option key={itemTag} value={itemTag}>{itemTag}</option>)}</select></label><label className="group-toggle"><input type="checkbox" checked={groupByTag} onChange={(event) => setGroupByTag(event.target.checked)} />Group by tag</label></div>{filtered.length ? groupByTag ? <div className="workflow-groups">{tagGroups.map((group) => <section key={group.name}><header className="workflow-group-title"><h2>{group.name}</h2><span>{group.items.length} workflow{group.items.length === 1 ? "" : "s"}</span></header>{workflowRows(group.items)}</section>)}</div> : <div className="workflow-folder-tree"><FolderTree folder={folderTree} root renderRows={workflowRows} /></div> : <EmptyState title="No matching workflows">Adjust the search term or tag filter.</EmptyState>}</> : <EmptyState title="No workflows yet">Create and store a local workflow to get started.</EmptyState>}
    {selected && <div className="modal-backdrop"><form className="modal" onSubmit={submit}><h2>Run {selected.name}</h2><label>Base ref<input name="base_ref" defaultValue={project.data?.default_branch ?? "main"} /></label>{localChanges > 0 && <label className="check-field"><input name="use_local_definitions" type="checkbox" defaultChecked /><span>Use local definitions <small>Creates an exact local Git snapshot for this test run.</small></span></label>}{Object.entries(selected.inputs).map(([name, definition]) => <label key={name}>{name}{definition.required && " *"}<input name={name} type={definition.type === "integer" ? "number" : "text"} required={definition.required} defaultValue={String(definition.default ?? "")} /></label>)}{trigger.error && <p className="error">{trigger.error.message}</p>}<footer><button type="button" className="secondary" onClick={() => setSelected(null)}>Cancel</button><button disabled={trigger.isPending}>Trigger run</button></footer></form></div>}
    {reviewUrl && <div className="toast"><strong>Definition review created</strong><a href={reviewUrl} target="_blank" rel="noreferrer">Open change request ↗</a><button onClick={() => setReviewUrl(null)}>Done</button></div>}
  </section>;
}
