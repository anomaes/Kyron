import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, json } from "../api/client";
import { EmptyState } from "../components/EmptyState";
import type { Credential } from "../types";

export function CredentialsPage() {
  const client = useQueryClient();
  const query = useQuery({ queryKey: ["credentials"], queryFn: () => api<Credential[]>("/credentials") });
  const [open, setOpen] = useState(false);
  const create = useMutation({ mutationFn: (body: unknown) => api("/credentials", json("POST", body)), onSuccess: () => { void client.invalidateQueries({ queryKey: ["credentials"] }); setOpen(false); } });
  const remove = useMutation({ mutationFn: (id: string) => api(`/credentials/${id}`, { method: "DELETE" }), onSuccess: () => void client.invalidateQueries({ queryKey: ["credentials"] }) });
  function submit(event: FormEvent<HTMLFormElement>) { event.preventDefault(); const data = new FormData(event.currentTarget); create.mutate({ key_name: data.get("key_name"), value: data.get("value"), description: data.get("description") || null }); }
  return <section><header className="page-header"><div><p className="eyebrow">Personal secret store</p><h1>Credentials</h1><p>Provider keys are encrypted at rest and injected only when a process starts.</p></div><button onClick={() => setOpen(true)}>Add credential</button></header>
    {query.data?.length ? <div className="table-card"><table><thead><tr><th>Key</th><th>Description</th><th>Updated</th><th>Value</th><th /></tr></thead><tbody>{query.data.map((item) => <tr key={item.id}><td className="mono">{item.key_name}</td><td>{item.description ?? "—"}</td><td>{new Date(item.updated_at).toLocaleString()}</td><td><span className="secret-dots">••••••••••••</span></td><td><button className="danger-link" onClick={() => { if (confirm(`Delete ${item.key_name}?`)) remove.mutate(item.id); }}>Delete</button></td></tr>)}</tbody></table></div> : <EmptyState title="No credentials stored">Add an AI-provider API key for prompt nodes.</EmptyState>}
    {open && <div className="modal-backdrop"><form className="modal" onSubmit={submit}><h2>Add credential</h2><label>Environment key<input name="key_name" pattern="[A-Za-z_][A-Za-z0-9_]*" placeholder="ANTHROPIC_API_KEY" required /></label><label>Secret value<input name="value" type="password" autoComplete="new-password" required /></label><label>Description<input name="description" /></label><p className="hint">Stored values can be replaced, never retrieved.</p><footer><button type="button" className="secondary" onClick={() => setOpen(false)}>Cancel</button><button>Encrypt & save</button></footer></form></div>}
  </section>;
}
