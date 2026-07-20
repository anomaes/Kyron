import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api, json } from "../api/client";
import { EmptyState } from "../components/EmptyState";
import type { Project, User } from "../types";

export function ProjectsPage() {
  const queryClient = useQueryClient();
  const projects = useQuery({ queryKey: ["projects"], queryFn: () => api<Project[]>("/projects") });
  const user = useQuery({ queryKey: ["me"], queryFn: () => api<User>("/auth/me") });
  const [open, setOpen] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<Project | null>(null);
  const create = useMutation({
    mutationFn: (payload: Record<string, unknown>) => api<Project>("/projects", json("POST", payload)),
    onSuccess: () => { void queryClient.invalidateQueries({ queryKey: ["projects"] }); setOpen(false); },
  });
  const remove = useMutation({
    mutationFn: (projectId: string) => api<void>(`/projects/${projectId}`, { method: "DELETE" }),
    onSuccess: () => {
      setDeleteTarget(null);
      void queryClient.invalidateQueries({ queryKey: ["projects"] });
    },
  });
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    create.mutate({
      name: data.get("name"), git_url: data.get("git_url"),
      provider: user.data?.provider, provider_project: data.get("provider_project"),
      access_token: data.get("access_token"), default_branch: data.get("default_branch") || "main",
    });
  }
  return (
    <section>
      <header className="page-header"><div><p className="eyebrow">Repository registry</p><h1>Projects</h1><p>Connect GitLab and GitHub repositories and manage their workflow catalog.</p></div><button onClick={() => setOpen(true)}>Add project</button></header>
      {projects.isLoading ? <div className="skeleton tall" /> : projects.data?.length ? (
        <div className="card-grid">{projects.data.map((project) => (
          <article className="card project-card" key={project.id}>
            <div className="card-top"><span className="repo-icon">⌘</span><span className="badge success">{project.provider.toUpperCase()} · TOKEN READY</span></div>
            <h2>{project.name}</h2><p className="mono muted truncate">{project.git_url}</p>
            <dl><div><dt>Repository</dt><dd>{project.provider_project_path}</dd></div><div><dt>Default branch</dt><dd>{project.default_branch}</dd></div></dl>
            <div className="card-actions project-actions"><Link className="button" to={`/projects/${project.id}/workflows`}>View workflows</Link><button className="secondary" disabled={user.data?.provider !== project.provider} title={user.data?.provider !== project.provider ? `Sign in with ${project.provider} to fetch` : undefined} onClick={() => api(`/projects/${project.id}/fetch`, { method: "POST" })}>Fetch</button><button className="danger" disabled={user.data?.provider !== project.provider} title={user.data?.provider !== project.provider ? `Sign in with ${project.provider} to remove` : "Remove project"} onClick={() => { remove.reset(); setDeleteTarget(project); }}>Remove</button></div>
          </article>
        ))}</div>
      ) : <EmptyState title="No projects connected">Register a repository to begin creating workflows.</EmptyState>}
      {open && <div className="modal-backdrop" onMouseDown={() => setOpen(false)}><form className="modal" onSubmit={submit} onMouseDown={(e) => e.stopPropagation()}><h2>Add {user.data?.provider === "github" ? "GitHub" : "GitLab"} project</h2><p className="muted">This session is signed in with {user.data?.provider}. Sign out to register a project from another provider.</p><label>Name<input name="name" required /></label><label>HTTPS clone URL<input name="git_url" type="url" required /></label><div className="form-row"><label>{user.data?.provider === "github" ? "Repository (owner/name)" : "GitLab project ID or path"}<input name="provider_project" required placeholder={user.data?.provider === "github" ? "owner/repository" : "12345"} /></label><label>Default branch<input name="default_branch" defaultValue="main" /></label></div><label>Project access token<input name="access_token" type="password" required autoComplete="new-password" /></label>{create.error && <p className="error">{create.error.message}</p>}<footer><button type="button" className="secondary" onClick={() => setOpen(false)}>Cancel</button><button disabled={create.isPending || !user.data}>Validate & add</button></footer></form></div>}
      {deleteTarget && <div className="modal-backdrop" onMouseDown={() => setDeleteTarget(null)}><div className="modal confirm-modal" onMouseDown={(event) => event.stopPropagation()}><span className="danger-mark">×</span><h2>Remove {deleteTarget.name}?</h2><p>This removes the local repository clone and any locally stored workflow or node-template changes. It does not delete the remote repository.</p><p className="hint">Projects with workflow run history cannot be removed, so their audit trail remains intact.</p>{remove.error && <p className="error">{remove.error.message}</p>}<footer><button type="button" className="secondary" onClick={() => setDeleteTarget(null)}>Cancel</button><button type="button" className="danger" disabled={remove.isPending} onClick={() => remove.mutate(deleteTarget.id)}>{remove.isPending ? "Removing…" : "Remove project"}</button></footer></div></div>}
    </section>
  );
}
