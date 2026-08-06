import { forwardRef, useImperativeHandle, useMemo, useRef, useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, json } from "../api/client";
import type { PiModelsAdminState, PiProviderCatalogEntry } from "../types";

type ProviderDocument = {
  baseUrl?: string;
  api?: string;
  apiKey?: string;
  authHeader?: boolean;
  headers?: Record<string, string>;
  models?: Array<Record<string, unknown> & { id?: string }>;
  [key: string]: unknown;
};

type ModelsDocument = { providers: Record<string, ProviderDocument>; [key: string]: unknown };

const EMPTY_DOCUMENT: ModelsDocument = { providers: {} };
const CREDENTIAL_PATTERN = /^[A-Za-z_][A-Za-z0-9_]*$/;

function modelsDocument(value: unknown): ModelsDocument {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("Configuration must be a JSON object");
  const document = value as Record<string, unknown>;
  if (!document.providers || typeof document.providers !== "object" || Array.isArray(document.providers)) throw new Error('Configuration must contain a "providers" object');
  return document as ModelsDocument;
}

function variableName(value: unknown): string {
  return typeof value === "string" && /^\$[A-Za-z_][A-Za-z0-9_]*$/.test(value) ? value.slice(1) : "";
}

function headerValue(headers: Record<string, string> | undefined, name: string): string | undefined {
  return Object.entries(headers ?? {}).find(([header]) => header.toLowerCase() === name.toLowerCase())?.[1];
}

function sourceLabel(state: PiModelsAdminState): string {
  if (state.source === "database") return state.providers.length ? `${state.providers.length} custom provider${state.providers.length === 1 ? "" : "s"} active` : "Built-in providers only";
  if (state.source === "file") return state.providers.length ? `${state.providers.length} deployment provider${state.providers.length === 1 ? "" : "s"} active` : "Deployment configuration";
  return "Built-in providers";
}

function sourceBadge(state: PiModelsAdminState): string {
  if (state.source === "database") return "MANAGED HERE";
  if (state.source === "file") return "DEPLOYMENT FILE";
  return "BUILT IN";
}

export function PiModelsAdminPanel() {
  const client = useQueryClient();
  const query = useQuery({ queryKey: ["admin-pi-models"], queryFn: () => api<PiModelsAdminState>("/admin/pi-models") });
  const [editorOpen, setEditorOpen] = useState(false);
  const [editorText, setEditorText] = useState(JSON.stringify(EMPTY_DOCUMENT, null, 2));
  const [selectedProvider, setSelectedProvider] = useState("");
  const [notice, setNotice] = useState<string | null>(null);
  const [builderError, setBuilderError] = useState<string | null>(null);
  const [validation, setValidation] = useState<{ providers: PiProviderCatalogEntry[]; required_credentials: string[] } | null>(null);
  const builderRef = useRef<ProviderBuilderHandle>(null);

  const refresh = async () => {
    await Promise.all([
      client.invalidateQueries({ queryKey: ["admin-pi-models"] }),
      client.invalidateQueries({ queryKey: ["pi-models-catalog"] }),
    ]);
  };
  const validate = useMutation({
    mutationFn: (document: ModelsDocument) => api<{ providers: PiProviderCatalogEntry[]; required_credentials: string[] }>("/admin/pi-models/validate", json("POST", { document })),
    onSuccess: setValidation,
  });
  const save = useMutation({
    mutationFn: (document: ModelsDocument) => api<PiModelsAdminState>("/admin/pi-models", json("PUT", { document })),
    onSuccess: async (result) => { setEditorOpen(false); setValidation(null); setNotice(`Version ${result.active_version} is active for new runs`); await refresh(); },
  });
  const activate = useMutation({
    mutationFn: (id: string) => api<PiModelsAdminState>(`/admin/pi-models/revisions/${id}/activate`, { method: "POST" }),
    onSuccess: async (result) => { setNotice(`Version ${result.active_version} restored for new runs`); await refresh(); },
  });
  const deactivate = useMutation({
    mutationFn: () => api<void>("/admin/pi-models/active", { method: "DELETE" }),
    onSuccess: async () => { setNotice("Custom configuration disabled; deployment defaults are now active"); await refresh(); },
  });

  const parsed = useMemo(() => {
    try { return modelsDocument(JSON.parse(editorText)); } catch { return null; }
  }, [editorText]);

  const prepareVisibleConfiguration = () => {
    try {
      setBuilderError(null);
      return builderRef.current?.prepareDocument() ?? parsed;
    } catch (error) {
      setBuilderError(error instanceof Error ? error.message : "Complete the endpoint configuration before continuing");
      return null;
    }
  };

  const openEditor = (providerId = "") => {
    setEditorText(JSON.stringify(query.data?.document ?? EMPTY_DOCUMENT, null, 2));
    setSelectedProvider(providerId);
    setBuilderError(null);
    setValidation(null);
    validate.reset();
    save.reset();
    setEditorOpen(true);
  };

  if (query.isLoading) return <div className="skeleton tall" />;
  if (query.error || !query.data) return <p className="error">{query.error?.message ?? "Provider configuration is unavailable"}</p>;
  const state = query.data;

  return <>
    <div className="provider-overview">
      <section className="provider-status-card">
        <div><span className="provider-orbit">π</span><div><p className="eyebrow">Active configuration</p><h2>{sourceLabel(state)}</h2><p>{state.providers.length ? "Ready to select in project defaults, workflow settings, and prompt nodes." : "No custom endpoints are active. Workflows can still use Pi's built-in providers."}</p>{state.source === "database" && state.active_version !== null && <small className="provider-source-meta">Managed in Administration · Version {state.active_version}</small>}</div></div>
        <div className="provider-status-actions"><button onClick={() => openEditor()}>Configure providers</button>{state.source === "database" && <button className="secondary" disabled={deactivate.isPending} onClick={() => deactivate.mutate()}>Use deployment defaults</button>}</div>
      </section>
      <aside className="provider-workflow-guide">
        <p className="eyebrow">Use in workflows</p>
        <p>Choose the provider and model in project defaults, workflow settings, or a prompt node. More specific values override inherited ones.</p>
        {state.providers[0] ? <pre>{`pi:\n  provider: ${state.providers[0].id}\n  model: ${state.providers[0].models[0] ?? "model-id"}`}</pre> : <p className="hint">Configured providers will appear as suggestions in workflow editors.</p>}
      </aside>
    </div>
    {state.configuration_error && <div className="provider-config-warning" role="alert"><strong>Bootstrap configuration needs attention</strong><span>{state.configuration_error}</span><button onClick={() => openEditor()}>Replace in Administration</button></div>}

    <section className="panel provider-panel">
      <div className="panel-title"><h2>Configured endpoints</h2><span>{sourceBadge(state)}</span></div>
      {state.providers.length ? <div className="provider-card-grid">{state.providers.map((provider) => <article className="provider-endpoint-card" key={provider.id}>
        <header><span className="provider-glyph">AI</span><div><h3>{provider.id}</h3><small>{provider.models.length ? `${provider.models.length} declared model${provider.models.length === 1 ? "" : "s"}` : "Built-in model catalog override"}</small></div><button className="ghost" onClick={() => openEditor(provider.id)}>Edit</button></header>
        <div className="model-chip-list">{provider.models.length ? provider.models.map((model) => <code key={model}>{model}</code>) : <span>Models supplied by Pi</span>}</div>
        <footer><span>Credentials</span><strong>{provider.required_credentials.join(", ") || "None referenced"}</strong></footer>
      </article>)}</div> : <div className="provider-empty"><span>＋</span><div><h3>No custom endpoints active</h3><p>Pi's built-in catalog remains available. Add an endpoint for a private gateway, Ollama, or another compatible API.</p></div><button onClick={() => openEditor()}>Add endpoint</button></div>}
    </section>

    <section className="panel provider-history">
      <div className="panel-title"><h2>Configuration history</h2><span>{state.revisions.length} VERSION{state.revisions.length === 1 ? "" : "S"}</span></div>
      {state.revisions.length ? state.revisions.map((revision) => <div className="provider-revision" key={revision.id}><div><strong>Version {revision.version}</strong>{revision.active && <span className="badge success">ACTIVE</span>}<small>{new Date(revision.created_at).toLocaleString()} · {revision.providers.map((item) => item.id).join(", ") || "No custom endpoints"}</small></div>{!revision.active && <button className="secondary" disabled={activate.isPending} onClick={() => activate.mutate(revision.id)}>Restore</button>}</div>) : <p className="provider-history-empty">Saved versions will appear here and can be restored without editing JSON.</p>}
    </section>

    {editorOpen && <div className="modal-backdrop" onMouseDown={() => setEditorOpen(false)}><div className="modal provider-editor-modal" onMouseDown={(event) => event.stopPropagation()}>
      <header className="provider-editor-head"><div><p className="eyebrow">AI provider registry</p><h2>Configure endpoints</h2><p>Build common providers with the form, then inspect or extend the generated Pi configuration.</p></div><button className="icon-button" aria-label="Close" onClick={() => setEditorOpen(false)}>×</button></header>
      <ProviderBuilder ref={builderRef} document={parsed} selectedProvider={selectedProvider} onSelect={setSelectedProvider} onChange={(document) => { setEditorText(JSON.stringify(document, null, 2)); setBuilderError(null); setValidation(null); }} onError={setBuilderError} />
      <details className="provider-json" open={!parsed}><summary>Advanced models.json</summary><textarea aria-label="Pi models configuration JSON" value={editorText} onChange={(event) => { setEditorText(event.target.value); setValidation(null); }} /></details>
      {(builderError || validate.error || save.error) && <p className="error provider-editor-error">{builderError ?? validate.error?.message ?? save.error?.message}</p>}
      {validation && <div className="provider-validation"><strong>✓ Configuration accepted by Pi</strong><span>{validation.providers.length} provider{validation.providers.length === 1 ? "" : "s"}; credentials: {validation.required_credentials.join(", ") || "none"}</span></div>}
      <footer><span className="provider-save-help">Visible form changes are included automatically.</span><button className="secondary" onClick={() => setEditorOpen(false)}>Cancel</button><button className="secondary" disabled={!parsed || validate.isPending} onClick={() => { const document = prepareVisibleConfiguration(); if (document) validate.mutate(document); }}>{validate.isPending ? "Validating…" : "Validate"}</button><button disabled={!parsed || save.isPending} onClick={() => { const document = prepareVisibleConfiguration(); if (document) save.mutate(document); }}>{save.isPending ? "Activating…" : "Save & activate"}</button></footer>
    </div></div>}
    {notice && <div className="toast"><strong>{notice}</strong><span>Existing runs keep their snapshotted provider configuration.</span><button onClick={() => setNotice(null)}>Done</button></div>}
  </>;
}

type ProviderBuilderHandle = {
  prepareDocument: () => ModelsDocument | null;
};

const ProviderBuilder = forwardRef<ProviderBuilderHandle, {
  document: ModelsDocument | null;
  selectedProvider: string;
  onSelect: (value: string) => void;
  onChange: (document: ModelsDocument) => void;
  onError: (message: string | null) => void;
}>(function ProviderBuilder({ document, selectedProvider, onSelect, onChange, onError }, ref) {
  const provider = document?.providers[selectedProvider];
  const xApiKey = headerValue(provider?.headers, "x-api-key");
  const bearerApiKey = provider?.authHeader === true ? variableName(provider.apiKey) : "";
  const formRef = useRef<HTMLFormElement>(null);
  const dirtyRef = useRef(false);

  function prepareDocument(): ModelsDocument | null {
    if (!document) throw new Error("Fix the advanced JSON before using the guided editor");
    const form = formRef.current;
    if (!form) return document;
    if (!selectedProvider && !dirtyRef.current) return document;
    if (!form.checkValidity()) {
      form.reportValidity();
      throw new Error("Complete the required endpoint fields before continuing");
    }
    const data = new FormData(form);
    const id = String(data.get("provider_id") ?? "").trim();
    const bearer = String(data.get("bearer_credential") ?? "").trim();
    const xKey = String(data.get("x_api_key_credential") ?? "").trim();
    if (!/^[A-Za-z0-9][A-Za-z0-9._-]*$/.test(id)) throw new Error("Provider ID must use letters, numbers, dots, underscores, or hyphens");
    if ((bearer && !CREDENTIAL_PATTERN.test(bearer)) || (xKey && !CREDENTIAL_PATTERN.test(xKey))) throw new Error("Credential names must be valid environment variable names");
    const old = document.providers[selectedProvider] ?? {};
    const headers = Object.fromEntries(
      Object.entries(old.headers ?? {}).filter(([header]) => header.toLowerCase() !== "x-api-key"),
    );
    if (xKey) headers["x-api-key"] = `$${xKey}`;
    const modelIds = String(data.get("models") ?? "").split(/\r?\n|,/).map((item) => item.trim()).filter(Boolean);
    const oldModels = new Map((old.models ?? []).filter((item) => typeof item.id === "string").map((item) => [item.id as string, item]));
    const updated: ProviderDocument = {
      ...old,
      baseUrl: String(data.get("base_url") ?? "").trim(),
      api: String(data.get("api") ?? "openai-completions"),
      models: modelIds.map((id) => oldModels.get(id) ?? { id }),
    };
    if (bearer) {
      updated.apiKey = `$${bearer}`;
      updated.authHeader = true;
    } else if (xKey) {
      // Pi requires custom models to resolve provider auth even when the gateway
      // authenticates through a custom header. Reuse the x-api-key credential
      // without enabling Pi's explicit Authorization: Bearer header.
      updated.apiKey = `$${xKey}`;
      delete updated.authHeader;
    } else if (old.authHeader === true || old.apiKey === xApiKey) {
      delete updated.apiKey;
      delete updated.authHeader;
    }
    if (Object.keys(headers).length) updated.headers = headers; else delete updated.headers;
    const providers = { ...document.providers };
    if (selectedProvider && selectedProvider !== id) delete providers[selectedProvider];
    providers[id] = updated;
    const nextDocument = { ...document, providers };
    dirtyRef.current = false;
    onChange(nextDocument);
    onSelect(id);
    return nextDocument;
  }

  useImperativeHandle(ref, () => ({ prepareDocument }));

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    try {
      onError(null);
      prepareDocument();
    } catch (error) {
      onError(error instanceof Error ? error.message : "Could not add the endpoint");
    }
  }

  function remove() {
    if (!document || !selectedProvider) return;
    const providers = { ...document.providers };
    delete providers[selectedProvider];
    onChange({ ...document, providers });
    onSelect(Object.keys(providers)[0] ?? "");
  }

  return <div className="provider-builder">
    <aside><button className={!selectedProvider ? "active" : ""} onClick={() => onSelect("")}><span>＋</span><div><strong>New provider</strong><small>Register an endpoint</small></div></button>{Object.keys(document?.providers ?? {}).map((id) => <button className={selectedProvider === id ? "active" : ""} key={id} onClick={() => onSelect(id)}><span>AI</span><div><strong>{id}</strong><small>{document?.providers[id]?.models?.length ?? 0} models</small></div></button>)}</aside>
    <form ref={formRef} key={selectedProvider || "new"} onSubmit={submit} onChange={() => { dirtyRef.current = true; onError(null); }}>
      <div className="form-row"><label>Provider ID<input name="provider_id" defaultValue={selectedProvider} placeholder="private-gateway" required /></label><label>API protocol<select name="api" defaultValue={provider?.api ?? "openai-completions"}><option value="openai-completions">OpenAI Chat Completions</option><option value="openai-responses">OpenAI Responses</option><option value="anthropic-messages">Anthropic Messages</option><option value="google-generative-ai">Google Generative AI</option></select></label></div>
      <label>Endpoint URL<input name="base_url" type="url" defaultValue={provider?.baseUrl ?? ""} placeholder="https://llm.example.com/v1" required /></label>
      <div className="provider-auth-box"><div><strong>Authentication headers</strong><small>Enter Kyron credential names, never token values. Both headers may be enabled together.</small></div><div className="form-row"><label>Bearer credential<input name="bearer_credential" defaultValue={bearerApiKey} placeholder="CUSTOM_LLM_TOKEN" pattern="[A-Za-z_][A-Za-z0-9_]*" /><span className="field-help">Sent as Authorization: Bearer …</span></label><label>x-api-key credential<input name="x_api_key_credential" defaultValue={variableName(xApiKey)} placeholder="CUSTOM_LLM_API_KEY" pattern="[A-Za-z_][A-Za-z0-9_]*" /><span className="field-help">Used as provider authentication and sent in the x-api-key header.</span></label></div></div>
      <label>Model IDs<textarea name="models" defaultValue={(provider?.models ?? []).map((item) => item.id).filter(Boolean).join("\n")} placeholder={"example-chat-model\nexample-reasoning-model"} required /><span className="field-help">One model ID per line. Advanced model metadata remains intact when IDs are unchanged.</span></label>
      <div className="provider-builder-actions">{selectedProvider && <button className="danger" type="button" onClick={remove}>Remove provider</button>}<span>{selectedProvider ? "Changes are applied when you validate or save." : "Saving this configuration will add the endpoint."}</span>{!selectedProvider && <button className="secondary" type="submit">Add another endpoint</button>}</div>
    </form>
  </div>;
});
