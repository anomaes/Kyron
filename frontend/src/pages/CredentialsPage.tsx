import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, json } from "../api/client";
import { EmptyState } from "../components/EmptyState";
import type { Credential } from "../types";

export function CredentialsPage() {
  const client = useQueryClient();
  const query = useQuery({ queryKey: ["credentials"], queryFn: () => api<Credential[]>("/credentials") });
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState<Credential | null>(null);

  const closeEditor = () => {
    create.reset();
    update.reset();
    setEditing(null);
    setOpen(false);
  };
  const saved = () => {
    void client.invalidateQueries({ queryKey: ["credentials"] });
    setEditing(null);
    setOpen(false);
  };
  const create = useMutation({
    mutationFn: (body: unknown) => api("/credentials", json("POST", body)),
    onSuccess: saved,
  });
  const update = useMutation({
    mutationFn: ({ id, body }: { id: string; body: unknown }) => api(`/credentials/${id}`, json("PUT", body)),
    onSuccess: saved,
  });
  const remove = useMutation({
    mutationFn: (id: string) => api(`/credentials/${id}`, { method: "DELETE" }),
    onSuccess: () => void client.invalidateQueries({ queryKey: ["credentials"] }),
  });

  function openCreator() {
    create.reset();
    update.reset();
    setEditing(null);
    setOpen(true);
  }

  function openEditor(credential: Credential) {
    create.reset();
    update.reset();
    setEditing(credential);
    setOpen(true);
  }

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    const description = String(data.get("description") ?? "") || null;
    const value = String(data.get("value") ?? "");
    if (editing) {
      update.mutate({
        id: editing.id,
        body: { key_name: data.get("key_name"), description, ...(value ? { value } : {}) },
      });
      return;
    }
    create.mutate({ key_name: data.get("key_name"), value, description });
  }

  const saving = create.isPending || update.isPending;
  const saveError = editing ? update.error : create.error;

  return <section><header className="page-header"><div><p className="eyebrow">Personal secret store</p><h1>Credentials</h1><p>Provider keys are encrypted at rest and injected only when a process starts.</p></div><button onClick={openCreator}>Add credential</button></header>
    {query.error && <p className="error" role="alert">{query.error.message}</p>}
    {query.data?.length ? <div className="table-card"><table><thead><tr><th>Key</th><th>Description</th><th>Updated</th><th>Value</th><th /></tr></thead><tbody>{query.data.map((item) => <tr key={item.id}><td className="mono">{item.key_name}</td><td>{item.description ?? "—"}</td><td>{new Date(item.updated_at).toLocaleString()}</td><td><span className="secret-dots">••••••••••••</span></td><td><div className="credential-actions"><button className="ghost" onClick={() => openEditor(item)}>Edit</button><button className="danger-link" onClick={() => { if (confirm(`Delete ${item.key_name}?`)) remove.mutate(item.id); }}>Delete</button></div></td></tr>)}</tbody></table></div> : <EmptyState title="No credentials stored">Add an AI-provider API key for prompt nodes.</EmptyState>}
    {remove.error && <p className="error" role="alert">{remove.error.message}</p>}
    {open && <div className="modal-backdrop"><form className="modal" onSubmit={submit}><h2>{editing ? "Edit credential" : "Add credential"}</h2><label>Environment key<input name="key_name" pattern="[A-Za-z_][A-Za-z0-9_]*" placeholder="ANTHROPIC_API_KEY" defaultValue={editing?.key_name ?? ""} required /></label><label>{editing ? "New secret value (optional)" : "Secret value"}<input className={editing ? "credential-secret-input" : undefined} name="value" type="password" autoComplete="new-password" placeholder={editing ? "••••••••" : undefined} required={!editing} /></label><label>Description<input name="description" defaultValue={editing?.description ?? ""} /></label><p className="hint">{editing ? "The dots represent the stored secret. Leave this field unchanged to keep its current value." : "Credential names must be unique. Stored values can be replaced, never retrieved."}</p>{saveError && <p className="error" role="alert">{saveError.message}</p>}<footer><button type="button" className="secondary" onClick={closeEditor}>Cancel</button><button disabled={saving}>{saving ? "Encrypting…" : editing ? "Save changes" : "Encrypt & save"}</button></footer></form></div>}
  </section>;
}
