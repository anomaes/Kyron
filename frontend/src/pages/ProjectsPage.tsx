import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router";
import { api, json } from "../api/client";
import { EmptyState } from "../components/EmptyState";
import type { PiModelsCatalog, Project, User } from "../types";

function randomWebhookSecret() {
  return Array.from(crypto.getRandomValues(new Uint8Array(32)), (value) => value.toString(16).padStart(2, "0")).join("");
}

export function ProjectsPage() {
  const queryClient = useQueryClient();
  const projects = useQuery({ queryKey: ["projects"], queryFn: () => api<Project[]>("/projects") });
  const user = useQuery({ queryKey: ["me"], queryFn: () => api<User>("/auth/me") });
  const piCatalog = useQuery({ queryKey: ["pi-models-catalog"], queryFn: () => api<PiModelsCatalog>("/pi/models/catalog"), staleTime: 30_000 });
  const [open, setOpen] = useState(false);
  const [newProjectWebhookSecret, setNewProjectWebhookSecret] = useState("");
  const [piTarget, setPiTarget] = useState<Project | null>(null);
  const [webhookTarget, setWebhookTarget] = useState<Project | null>(null);
  const [webhookSecret, setWebhookSecret] = useState("");
  const [deleteTarget, setDeleteTarget] = useState<Project | null>(null);
  const [fetchNotice, setFetchNotice] = useState<string | null>(null);
  const create = useMutation({
    mutationFn: (payload: Record<string, unknown>) => api<Project>("/projects", json("POST", payload)),
    onSuccess: () => { void queryClient.invalidateQueries({ queryKey: ["projects"] }); setOpen(false); setNewProjectWebhookSecret(""); },
  });
  const remove = useMutation({
    mutationFn: (projectId: string) => api<void>(`/projects/${projectId}`, { method: "DELETE" }),
    onSuccess: () => {
      setDeleteTarget(null);
      void queryClient.invalidateQueries({ queryKey: ["projects"] });
    },
  });
  const updatePi = useMutation({
    mutationFn: ({ projectId, pi }: { projectId: string; pi: Project["pi"] }) => api<Project>(`/projects/${projectId}/pi`, json("PUT", pi)),
    onSuccess: () => { setPiTarget(null); void queryClient.invalidateQueries({ queryKey: ["projects"] }); },
  });
  const updateWebhookSecret = useMutation({
    mutationFn: ({ projectId, webhook_secret, webhook_signing_secret, clear_webhook_signing_secret }: { projectId: string; webhook_secret: string; webhook_signing_secret: string | null; clear_webhook_signing_secret: boolean }) => api<Project>(`/projects/${projectId}/webhook-secret`, json("PUT", { webhook_secret, webhook_signing_secret, clear_webhook_signing_secret })),
    onSuccess: () => { setWebhookTarget(null); setWebhookSecret(""); void queryClient.invalidateQueries({ queryKey: ["projects"] }); },
  });
  const fetchProject = useMutation({
    mutationFn: (projectId: string) => api<{ commit_sha: string }>(`/projects/${projectId}/fetch`, { method: "POST" }),
    onSuccess: (result, projectId) => {
      const name = projects.data?.find((project) => project.id === projectId)?.name ?? "Project";
      setFetchNotice(`${name} fetched successfully at ${result.commit_sha.slice(0, 12)}`);
      void queryClient.invalidateQueries({ queryKey: ["projects"] });
      void queryClient.invalidateQueries({ queryKey: ["workflows", projectId] });
    },
  });
  const piFrom = (data: FormData): Project["pi"] => Object.fromEntries(
    (["provider", "model", "skill"] as const)
      .map((field) => [field, String(data.get(`pi_${field}`) ?? "").trim()] as const)
      .filter(([, value]) => value),
  );
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    create.mutate({
      name: data.get("name"), git_url: data.get("git_url"),
      provider: user.data?.provider, provider_project: data.get("provider_project"),
      access_token: data.get("access_token"), default_branch: data.get("default_branch") || "main",
      webhook_secret: data.get("webhook_secret"),
      webhook_signing_secret: data.get("webhook_signing_secret") || null,
      pi: piFrom(data),
    });
  }
  function submitPi(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!piTarget) return;
    updatePi.mutate({ projectId: piTarget.id, pi: piFrom(new FormData(event.currentTarget)) });
  }
  function submitWebhookSecret(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!webhookTarget) return;
    const data = new FormData(event.currentTarget);
    updateWebhookSecret.mutate({
      projectId: webhookTarget.id,
      webhook_secret: String(data.get("webhook_secret") ?? ""),
      webhook_signing_secret: String(data.get("webhook_signing_secret") ?? "") || null,
      clear_webhook_signing_secret: data.get("clear_webhook_signing_secret") === "on",
    });
  }
  function openWebhookEditor(project: Project) {
    updateWebhookSecret.reset();
    setWebhookSecret(randomWebhookSecret());
    setWebhookTarget(project);
  }
  function closeProjectEditor() {
    setOpen(false);
    setNewProjectWebhookSecret("");
  }
  function closeWebhookEditor() {
    setWebhookTarget(null);
    setWebhookSecret("");
  }
  return (
    <section>
      <header className="page-header"><div><p className="eyebrow">Repository registry</p><h1>Projects</h1><p>Connect GitLab and GitHub repositories and manage their workflow catalog.</p></div>{user.data?.is_system_admin && <button onClick={() => { setNewProjectWebhookSecret(randomWebhookSecret()); setOpen(true); }}>Add project</button>}</header>
      {projects.isLoading ? <div className="skeleton tall" /> : projects.data?.length ? (
        <div className="card-grid">{projects.data.map((project) => (
          <article className="card project-card" key={project.id}>
            <div className="card-top"><span className="repo-icon">⌘</span><span className={`badge ${project.webhook_secret_configured ? "success" : "waiting"}`}>{project.provider.toUpperCase()} · {project.webhook_secret_configured ? "WEBHOOK READY" : "WEBHOOK REQUIRED"}</span></div>
            <h2>{project.name}</h2><p className="mono muted truncate">{project.git_url}</p>
            <dl><div><dt>Repository</dt><dd>{project.provider_project_path}</dd></div><div><dt>Default branch</dt><dd>{project.default_branch}</dd></div><div><dt>Pi defaults</dt><dd className="pi-defaults-status"><input type="checkbox" checked={Object.values(project.pi).some(Boolean)} disabled aria-label={Object.values(project.pi).some(Boolean) ? "Pi defaults configured" : "Pi defaults not configured"} title={Object.values(project.pi).some(Boolean) ? "Pi defaults configured" : "Pi defaults not configured"} /></dd></div></dl>
            <div className="card-actions project-actions"><Link className="button" to={`/projects/${project.id}/workflows`}>View workflows</Link><Link className="button secondary" to={`/projects/${project.id}/admin`}>Access & governance</Link>{project.can_manage && <button className="secondary" disabled={user.data?.provider !== project.provider} onClick={() => openWebhookEditor(project)}>Webhook</button>}{user.data?.is_system_admin && <><button className="secondary" disabled={user.data?.provider !== project.provider} onClick={() => setPiTarget(project)}>Pi defaults</button><button className="secondary" disabled={user.data?.provider !== project.provider || (fetchProject.isPending && fetchProject.variables === project.id)} title={user.data?.provider !== project.provider ? `Sign in with ${project.provider} to fetch` : undefined} onClick={() => { fetchProject.reset(); setFetchNotice(null); fetchProject.mutate(project.id); }}>{fetchProject.isPending && fetchProject.variables === project.id ? "Fetching…" : "Fetch"}</button><button className="danger" disabled={user.data?.provider !== project.provider} title={user.data?.provider !== project.provider ? `Sign in with ${project.provider} to remove` : "Remove project"} onClick={() => { remove.reset(); setDeleteTarget(project); }}>Remove</button></>}</div>
          </article>
        ))}</div>
      ) : <EmptyState title="No projects connected">Register a repository to begin creating workflows.</EmptyState>}
      <datalist id="configured-pi-providers">{piCatalog.data?.providers.map((provider) => <option key={provider.id} value={provider.id} />)}</datalist><datalist id="configured-pi-models">{piCatalog.data?.providers.flatMap((provider) => provider.models.map((model) => <option key={`${provider.id}:${model}`} value={model} />))}</datalist>
      {open && <div className="modal-backdrop" onMouseDown={closeProjectEditor}><form className="modal" onSubmit={submit} onMouseDown={(e) => e.stopPropagation()}><h2>Add {user.data?.provider === "github" ? "GitHub" : "GitLab"} project</h2><p className="muted">This session is signed in with {user.data?.provider}. Sign out to register a project from another provider.</p><label>Name<input name="name" required /></label><label>HTTPS clone URL<input name="git_url" type="url" required /></label><div className="form-row"><label>{user.data?.provider === "github" ? "Repository (owner/name)" : "GitLab project ID or path"}<input name="provider_project" required placeholder={user.data?.provider === "github" ? "owner/repository" : "12345"} /></label><label>Default branch<input name="default_branch" defaultValue="main" /></label></div><label>Project access token<input name="access_token" type="password" required autoComplete="new-password" /></label><label>Webhook secret<input name="webhook_secret" type="password" minLength={16} value={newProjectWebhookSecret} onChange={(event) => setNewProjectWebhookSecret(event.target.value)} required autoComplete="new-password" /><span className="field-help">Use this same value when creating the repository webhook.</span></label><div className="form-row"><button type="button" className="secondary" onClick={() => setNewProjectWebhookSecret(randomWebhookSecret())}>Generate secret</button><button type="button" className="secondary" onClick={() => void navigator.clipboard.writeText(newProjectWebhookSecret)}>Copy secret</button></div>{user.data?.provider === "gitlab" && <label>Standard Webhooks signing secret (optional)<input name="webhook_signing_secret" type="password" minLength={16} autoComplete="new-password" /></label>}<details className="advanced-json"><summary>Pi defaults</summary><label>Provider<input name="pi_provider" list="configured-pi-providers" placeholder="anthropic or configured provider" /></label><label>Model<input name="pi_model" list="configured-pi-models" placeholder="Model ID" /></label><label>Skill path<input name="pi_skill" placeholder=".agents/skills/example/SKILL.md" /><span className="field-help">Relative to the repository root.</span></label></details>{create.error && <p className="error">{create.error.message}</p>}<footer><button type="button" className="secondary" onClick={closeProjectEditor}>Cancel</button><button disabled={create.isPending || !user.data}>Validate & add</button></footer></form></div>}
      {webhookTarget && <div className="modal-backdrop" onMouseDown={closeWebhookEditor}><form className="modal" onSubmit={submitWebhookSecret} onMouseDown={(event) => event.stopPropagation()}><h2>Webhook for {webhookTarget.name}</h2><p className="muted">Replacing this value immediately invalidates deliveries signed with the previous secret. Copy the new value into the repository webhook configuration.</p><label>Webhook URL<input value={`${window.location.origin}/api/webhook/${webhookTarget.provider}`} readOnly /></label><label>New webhook secret<input name="webhook_secret" type="password" minLength={16} value={webhookSecret} onChange={(event) => setWebhookSecret(event.target.value)} required autoComplete="new-password" /></label><div className="form-row"><button type="button" className="secondary" onClick={() => setWebhookSecret(randomWebhookSecret())}>Generate secret</button><button type="button" className="secondary" onClick={() => void navigator.clipboard.writeText(webhookSecret)}>Copy secret</button></div>{webhookTarget.provider === "gitlab" && <><label>New Standard Webhooks signing secret (optional)<input name="webhook_signing_secret" type="password" minLength={16} autoComplete="new-password" /><span className="field-help">Leave empty to preserve the stored signing secret.</span></label>{webhookTarget.webhook_signing_secret_configured && <label className="check-field"><input name="clear_webhook_signing_secret" type="checkbox" /> Clear the stored signing secret</label>}</>}{updateWebhookSecret.error && <p className="error">{updateWebhookSecret.error.message}</p>}<footer><button type="button" className="secondary" onClick={closeWebhookEditor}>Cancel</button><button disabled={updateWebhookSecret.isPending}>{updateWebhookSecret.isPending ? "Encrypting…" : "Replace secret"}</button></footer></form></div>}
      {piTarget && <div className="modal-backdrop" onMouseDown={() => setPiTarget(null)}><form className="modal" onSubmit={submitPi} onMouseDown={(event) => event.stopPropagation()}><h2>Pi defaults for {piTarget.name}</h2><p className="muted">Workflow and prompt-node values override these defaults field by field. Custom admin-configured providers appear as suggestions.</p><label>Provider<input name="pi_provider" list="configured-pi-providers" defaultValue={piTarget.pi.provider ?? ""} placeholder="Use Pi default" /></label><label>Model<input name="pi_model" list="configured-pi-models" defaultValue={piTarget.pi.model ?? ""} placeholder="Use Pi default" /></label><label>Skill path<input name="pi_skill" defaultValue={piTarget.pi.skill ?? ""} placeholder=".agents/skills/example/SKILL.md" /><span className="field-help">Relative to the repository root at the run's pinned commit.</span></label>{updatePi.error && <p className="error">{updatePi.error.message}</p>}<footer><button type="button" className="secondary" onClick={() => setPiTarget(null)}>Cancel</button><button disabled={updatePi.isPending}>Save defaults</button></footer></form></div>}
      {deleteTarget && <div className="modal-backdrop" onMouseDown={() => setDeleteTarget(null)}><div className="modal confirm-modal" onMouseDown={(event) => event.stopPropagation()}><span className="danger-mark">×</span><h2>Remove {deleteTarget.name}?</h2><p>This removes the local repository clone and any locally stored workflow or node-template changes. It does not delete the remote repository.</p><p className="hint">Projects with workflow run history cannot be removed, so their audit trail remains intact.</p>{remove.error && <p className="error">{remove.error.message}</p>}<footer><button type="button" className="secondary" onClick={() => setDeleteTarget(null)}>Cancel</button><button type="button" className="danger" disabled={remove.isPending} onClick={() => remove.mutate(deleteTarget.id)}>{remove.isPending ? "Removing…" : "Remove project"}</button></footer></div></div>}
      {(fetchNotice || fetchProject.error) && <div className="toast"><strong>{fetchNotice ?? "Repository fetch failed"}</strong>{fetchProject.error && <span>{fetchProject.error.message}</span>}<button onClick={() => { setFetchNotice(null); fetchProject.reset(); }}>Done</button></div>}
    </section>
  );
}
