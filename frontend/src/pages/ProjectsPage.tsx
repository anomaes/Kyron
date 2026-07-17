import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api, json } from "../api/client";
import { EmptyState } from "../components/EmptyState";
import type { Project } from "../types";

export function ProjectsPage() {
  const queryClient = useQueryClient();
  const projects = useQuery({ queryKey: ["projects"], queryFn: () => api<Project[]>("/projects") });
  const [open, setOpen] = useState(false);
  const create = useMutation({
    mutationFn: (payload: Record<string, unknown>) => api<Project>("/projects", json("POST", payload)),
    onSuccess: () => { void queryClient.invalidateQueries({ queryKey: ["projects"] }); setOpen(false); },
  });
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    create.mutate({
      name: data.get("name"), git_url: data.get("git_url"),
      gitlab_project_id: Number(data.get("gitlab_project_id")),
      access_token: data.get("access_token"), default_branch: data.get("default_branch") || "main",
    });
  }
  return (
    <section>
      <header className="page-header"><div><p className="eyebrow">Repository registry</p><h1>Projects</h1><p>Connect GitLab repositories and manage their workflow catalog.</p></div><button onClick={() => setOpen(true)}>Add project</button></header>
      {projects.isLoading ? <div className="skeleton tall" /> : projects.data?.length ? (
        <div className="card-grid">{projects.data.map((project) => (
          <article className="card project-card" key={project.id}>
            <div className="card-top"><span className="repo-icon">⌘</span><span className="badge success">TOKEN READY</span></div>
            <h2>{project.name}</h2><p className="mono muted truncate">{project.git_url}</p>
            <dl><div><dt>GitLab ID</dt><dd>{project.gitlab_project_id}</dd></div><div><dt>Default branch</dt><dd>{project.default_branch}</dd></div></dl>
            <div className="card-actions"><Link className="button" to={`/projects/${project.id}/workflows`}>View workflows</Link><button className="secondary" onClick={() => api(`/projects/${project.id}/fetch`, { method: "POST" })}>Fetch</button></div>
          </article>
        ))}</div>
      ) : <EmptyState title="No projects connected">Register a GitLab repository to begin creating workflows.</EmptyState>}
      {open && <div className="modal-backdrop" onMouseDown={() => setOpen(false)}><form className="modal" onSubmit={submit} onMouseDown={(e) => e.stopPropagation()}><h2>Add GitLab project</h2><label>Name<input name="name" required /></label><label>HTTPS clone URL<input name="git_url" type="url" required /></label><div className="form-row"><label>GitLab project ID<input name="gitlab_project_id" type="number" required /></label><label>Default branch<input name="default_branch" defaultValue="main" /></label></div><label>Project access token<input name="access_token" type="password" required autoComplete="new-password" /></label>{create.error && <p className="error">{create.error.message}</p>}<footer><button type="button" className="secondary" onClick={() => setOpen(false)}>Cancel</button><button disabled={create.isPending}>Validate & add</button></footer></form></div>}
    </section>
  );
}
