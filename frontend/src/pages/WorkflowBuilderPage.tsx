import { useEffect, useRef, useState, type CSSProperties, type FormEvent, type KeyboardEvent, type PointerEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Background, Controls, MarkerType, MiniMap, ReactFlow, ReactFlowProvider, type Connection, type Edge, type NodeTypes } from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { Link, useNavigate, useOutletContext, useParams } from "react-router-dom";
import { api, json } from "../api/client";
import type { ApprovalPolicy, DefinitionChangeStatus, NodeTemplate, NodeType, User, Workflow } from "../types";
import { CompositeNodeConfig } from "../workflow-builder/CompositeNodeConfig";
import { PromptNodeConfig } from "../workflow-builder/PromptNodeConfig";
import { useBuilderStore, wouldCreateCycle } from "../workflow-builder/store";
import { WorkflowInterfaceEditor } from "../workflow-builder/WorkflowInterfaceEditor";
import { WorkflowCard } from "../workflow-builder/WorkflowCard";

const nodeTypes: NodeTypes = { workflow: WorkflowCard };
const DEFAULT_INSPECTOR_WIDTH = 340;
const MIN_INSPECTOR_WIDTH = 300;
type WorkflowCatalogItem = Workflow & { folder_path: string };
type WorkflowCatalogResponse = DefinitionChangeStatus & { base_commit_sha: string; items: WorkflowCatalogItem[] };
type TemplateCatalogResponse = DefinitionChangeStatus & { base_commit_sha: string; items: NodeTemplate[] };
const palette: Array<{ type: NodeType; label: string; help: string }> = [
  { type: "bash", label: "Bash", help: "Shell command" },
  { type: "script", label: "Python Script", help: "Repository script" },
  { type: "prompt", label: "Pi Prompt", help: "Coding agent" },
  { type: "human_feedback", label: "Human Feedback", help: "Pause for review" },
  { type: "subworkflow", label: "Sub-workflow", help: "Invoke child DAG" },
  { type: "review_loop", label: "Review Loop", help: "Iterative revision" },
];

function Builder() {
  const { projectId = "", workflowId } = useParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { user } = useOutletContext<{ user?: User }>();
  const store = useBuilderStore();
  const [configText, setConfigText] = useState("");
  const [tagText, setTagText] = useState("");
  const [folderPath, setFolderPath] = useState("");
  const [advanced, setAdvanced] = useState(false);
  const [showTemplates, setShowTemplates] = useState(false);
  const [templateNodeId, setTemplateNodeId] = useState<string | null>(null);
  const [interfaceOpen, setInterfaceOpen] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [inspectorWidth, setInspectorWidth] = useState(() => {
    const stored = typeof window === "undefined" ? null : Number(window.sessionStorage.getItem("kyron.inspectorWidth"));
    return stored && Number.isFinite(stored) ? Math.max(MIN_INSPECTOR_WIDTH, stored) : DEFAULT_INSPECTOR_WIDTH;
  });
  const resizePointer = useRef<number | null>(null);
  useEffect(() => {
    window.sessionStorage.setItem("kyron.inspectorWidth", String(inspectorWidth));
  }, [inspectorWidth]);
  useEffect(() => {
    const fitInspector = () => setInspectorWidth((width) => Math.min(Math.max(MIN_INSPECTOR_WIDTH, Math.min(720, window.innerWidth - 230 - 190 - 280)), width));
    window.addEventListener("resize", fitInspector);
    fitInspector();
    return () => { window.removeEventListener("resize", fitInspector); document.body.classList.remove("inspector-resizing"); };
  }, []);
  const existing = useQuery({ queryKey: ["workflow", projectId, workflowId], enabled: Boolean(workflowId), queryFn: () => api<{ base_commit_sha: string; workflow: Workflow; folder_path: string }>(`/projects/${projectId}/workflows/${workflowId}`) });
  const catalog = useQuery({ queryKey: ["workflows", projectId], queryFn: () => api<WorkflowCatalogResponse>(`/projects/${projectId}/workflows`) });
  const templates = useQuery({ queryKey: ["workflow-templates", projectId], queryFn: () => api<TemplateCatalogResponse>(`/projects/${projectId}/workflows/templates`) });
  const policies = useQuery({ queryKey: ["approval-policies", projectId], queryFn: () => api<ApprovalPolicy[]>(`/projects/${projectId}/approval-policies`) });
  useEffect(() => {
    if (existing.data) { store.setWorkflow(existing.data.workflow); setFolderPath(existing.data.folder_path); }
    else if (!workflowId) { store.setWorkflow({ id: "new_workflow", name: "New workflow", description: "", version: 2, created_by: user?.email ?? "", tags: [], inputs: {}, outputs: {}, variables: {}, nodes: [], edges: [], settings: {} }); setFolderPath(""); }
  }, [existing.data, workflowId, user?.email]);
  useEffect(() => { setTagText(store.workflow.tags.join(", ")); }, [store.workflow.tags]);
  const selected = store.nodes.find((node) => node.id === store.selectedNodeId);
  const templateNode = store.nodes.find((node) => node.id === templateNodeId)?.data.workflowNode;
  useEffect(() => { setConfigText(selected ? JSON.stringify(selected.data.workflowNode.config, null, 2) : ""); }, [selected?.id, selected?.data.workflowNode.config]);
  const validate = useMutation({ mutationFn: (workflow: Workflow) => api<{ valid: boolean; errors: Array<{ path: string; message: string }> }>(`/projects/${projectId}/workflows/validate`, json("POST", { workflow, proposed_related_workflows: {} })) });
  const save = useMutation({
    mutationFn: (workflow: Workflow) => api<DefinitionChangeStatus>(`/projects/${projectId}/workflows/${workflow.id}`, json("PUT", { workflow, folder_path: folderPath, expected_base_commit_sha: existing.data?.base_commit_sha ?? catalog.data?.base_commit_sha })),
    onSuccess: (_, workflow) => {
      setNotice("Workflow stored locally");
      void queryClient.invalidateQueries({ queryKey: ["workflows", projectId] });
      if (!workflowId) navigate(`/projects/${projectId}/workflows/${workflow.id}/edit`, { replace: true });
    },
  });
  const saveTemplate = useMutation({
    mutationFn: (template: NodeTemplate) => api(`/projects/${projectId}/workflows/templates`, json("POST", { template, expected_base_commit_sha: existing.data?.base_commit_sha ?? catalog.data?.base_commit_sha })),
    onSuccess: () => {
      setTemplateNodeId(null);
      setNotice("Node template stored locally");
      void queryClient.invalidateQueries({ queryKey: ["workflow-templates", projectId] });
      void queryClient.invalidateQueries({ queryKey: ["workflows", projectId] });
    },
  });
  const isValidConnection = (connection: Connection | Edge) => !wouldCreateCycle(connection, store.nodes, store.edges);
  const commitConfig = () => { if (!selected) return; try { store.updateNode(selected.id, { config: JSON.parse(configText) as Record<string, unknown> }); } catch { /* retain text so the user can fix it */ } };
  const commitTags = () => { const tags = Array.from(new Set(tagText.split(",").map((tag) => tag.trim().toLowerCase()).filter(Boolean))); store.patchWorkflow({ tags }); setTagText(tags.join(", ")); };
  const updatePiDefault = (field: "provider" | "model" | "skill", value: string) => {
    const pi = { ...(store.workflow.settings.pi ?? {}), [field]: value || null };
    store.patchWorkflow({ settings: { ...store.workflow.settings, pi } });
  };
  const storeWorkflow = () => {
    const workflow = store.serialize();
    validate.mutate(workflow, { onSuccess: (report) => { if (report.valid) save.mutate(workflow); } });
  };
  const submitTemplate = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!templateNode) return;
    const data = new FormData(event.currentTarget);
    saveTemplate.mutate({
      id: String(data.get("id")),
      name: String(data.get("name")),
      description: String(data.get("description")),
      node: structuredClone(templateNode),
    });
  };
  const errors = validate.data?.errors ?? [];
  const maximumInspectorWidth = () => Math.max(MIN_INSPECTOR_WIDTH, Math.min(720, window.innerWidth - 230 - 190 - 280));
  const updateInspectorWidth = (width: number) => setInspectorWidth(Math.min(maximumInspectorWidth(), Math.max(MIN_INSPECTOR_WIDTH, width)));
  const startInspectorResize = (event: PointerEvent<HTMLDivElement>) => {
    event.preventDefault();
    resizePointer.current = event.pointerId;
    event.currentTarget.setPointerCapture(event.pointerId);
    document.body.classList.add("inspector-resizing");
  };
  const moveInspectorResize = (event: PointerEvent<HTMLDivElement>) => {
    if (resizePointer.current !== event.pointerId) return;
    updateInspectorWidth(window.innerWidth - event.clientX);
  };
  const stopInspectorResize = (event: PointerEvent<HTMLDivElement>) => {
    if (resizePointer.current !== event.pointerId) return;
    resizePointer.current = null;
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
    document.body.classList.remove("inspector-resizing");
  };
  const resizeInspectorWithKeyboard = (event: KeyboardEvent<HTMLDivElement>) => {
    if (!event.key.startsWith("Arrow")) return;
    event.preventDefault();
    const direction = event.key === "ArrowLeft" ? 1 : event.key === "ArrowRight" ? -1 : 0;
    if (!direction) return;
    const width = Math.min(maximumInspectorWidth(), Math.max(MIN_INSPECTOR_WIDTH, inspectorWidth + direction * 24));
    setInspectorWidth(width);
  };
  return <div className="builder-page">
    <header className="builder-header"><div><Link to={`/projects/${projectId}/workflows`} className="eyebrow">← Workflow catalog</Link><input className="title-input" value={store.workflow.name} onChange={(event) => store.patchWorkflow({ name: event.target.value })} /><span className="mono">{store.workflow.id}</span></div><div>{(catalog.data?.outgoing_changes ?? 0) > 0 && <span className="outgoing-badge">↑ {catalog.data?.outgoing_changes} outgoing</span>}<button className="secondary" onClick={() => setInterfaceOpen(true)}>Inputs & outputs</button><button className="secondary" onClick={() => validate.mutate(store.serialize())}>Validate</button><button disabled={save.isPending || !(existing.data?.base_commit_sha ?? catalog.data?.base_commit_sha)} onClick={storeWorkflow}>Store</button></div></header>
    <div className="builder-shell" style={{ "--inspector-width": `${inspectorWidth}px` } as CSSProperties}><aside className="palette"><div className="palette-tabs"><button className={!showTemplates ? "active" : ""} onClick={() => setShowTemplates(false)}>Nodes</button><button className={showTemplates ? "active" : ""} onClick={() => setShowTemplates(true)}>Templates</button></div>{showTemplates ? <div className="template-browser">{templates.data?.items.length ? templates.data.items.map((template) => <button key={template.id} onClick={() => store.addTemplate(template.node)}><span className={`palette-icon type-${template.node.type}`}>◈</span><div><strong>{template.name}</strong><small>{template.description || template.node.label}</small></div><b>+</b></button>) : <p>No templates yet. Select a node and store it as your first template.</p>}</div> : <>{palette.map((item) => <button key={item.type} onClick={() => store.addNode(item.type)}><span className={`palette-icon type-${item.type}`}>◈</span><div><strong>{item.label}</strong><small>{item.help}</small></div><b>+</b></button>)}</>}<hr /><button className="plain" onClick={() => setAdvanced(!advanced)}>Workflow settings <span>›</span></button>{advanced && <div className="advanced-settings"><label>ID<input value={store.workflow.id} onChange={(event) => store.patchWorkflow({ id: event.target.value })} /></label><label>Folder<input value={folderPath} placeholder="teams/platform" onChange={(event) => setFolderPath(event.target.value)} /><span className="field-help">Relative to .workflowEngine; leave empty for the root.</span></label><label>Description<textarea value={store.workflow.description} onChange={(event) => store.patchWorkflow({ description: event.target.value })} /></label><label>Tags<input value={tagText} placeholder="implementation, backend" onChange={(event) => setTagText(event.target.value)} onBlur={commitTags} /><span className="field-help">Comma-separated lowercase tags.</span></label><label>Pi provider<input value={store.workflow.settings.pi?.provider ?? ""} placeholder="Inherit project default" onChange={(event) => updatePiDefault("provider", event.target.value)} /></label><label>Pi model<input value={store.workflow.settings.pi?.model ?? ""} placeholder="Inherit project default" onChange={(event) => updatePiDefault("model", event.target.value)} /></label><label>Pi skill<input value={store.workflow.settings.pi?.skill ?? ""} placeholder=".agents/skills/example/SKILL.md" onChange={(event) => updatePiDefault("skill", event.target.value)} /><span className="field-help">Repository-relative path; prompt nodes may override it.</span></label><label>Variables JSON<textarea value={JSON.stringify(store.workflow.variables, null, 2)} onChange={(event) => { try { store.patchWorkflow({ variables: JSON.parse(event.target.value) as Workflow["variables"] }); } catch { /* wait for valid JSON */ } }} /></label></div>}</aside>
      <main className="builder-canvas"><ReactFlow nodes={store.nodes} edges={store.edges} nodeTypes={nodeTypes} onNodesChange={store.onNodesChange} onEdgesChange={store.onEdgesChange} onConnect={store.connect} isValidConnection={isValidConnection} onNodeClick={(_, node) => store.selectNode(node.id)} onPaneClick={() => store.selectNode(null)} defaultEdgeOptions={{ type: "smoothstep", markerEnd: { type: MarkerType.ArrowClosed } }} fitView><Background gap={22} size={1} /><MiniMap pannable /><Controls /></ReactFlow>{errors.length > 0 && <div className="validation-drawer"><strong>{errors.length} validation issue{errors.length === 1 ? "" : "s"}</strong>{errors.slice(0, 5).map((error) => <p key={`${error.path}-${error.message}`}><code>{error.path}</code> {error.message}</p>)}</div>}</main>
      <div className="inspector-resize-handle" role="separator" aria-label="Resize node editor" aria-orientation="vertical" aria-valuemin={MIN_INSPECTOR_WIDTH} aria-valuemax={maximumInspectorWidth()} aria-valuenow={inspectorWidth} tabIndex={0} onPointerDown={startInspectorResize} onPointerMove={moveInspectorResize} onPointerUp={stopInspectorResize} onPointerCancel={stopInspectorResize} onKeyDown={resizeInspectorWithKeyboard} onDoubleClick={() => setInspectorWidth(DEFAULT_INSPECTOR_WIDTH)} />
      <aside className="inspector">{selected ? <><div className="inspector-head"><div><span className={`palette-icon type-${selected.data.type}`}>◈</span><div><small>{selected.data.type.replaceAll("_", " ")}</small><strong>{selected.data.label}</strong></div></div><button className="icon-button" onClick={store.removeSelected}>×</button></div><button className="store-template-button" onClick={() => setTemplateNodeId(selected.id)}>Store as template</button><label>Node ID<input value={selected.data.workflowNode.id} disabled /></label><label>Label<input value={selected.data.workflowNode.label} onChange={(event) => store.updateNode(selected.id, { label: event.target.value })} /></label><label>Join<select value={selected.data.workflowNode.join ?? "and"} onChange={(event) => store.updateNode(selected.id, { join: event.target.value as "and" | "or" })}><option value="and">AND — wait for all</option><option value="or">OR — first matching edge</option></select></label>{["human_feedback", "review_loop"].includes(selected.data.type) && <label>Approval policy<select value={String(selected.data.workflowNode.config.approval_policy ?? "")} onChange={(event) => store.updateNode(selected.id, { config: { ...selected.data.workflowNode.config, approval_policy: event.target.value } })}><option value="select-policy" disabled>Select a policy…</option>{policies.data?.filter((policy) => policy.enabled).map((policy) => <option key={policy.id} value={policy.key}>{policy.name}</option>)}</select><span className="field-help">Managed in Project access & governance.</span></label>}{selected.data.type === "prompt" && <PromptNodeConfig node={selected.data.workflowNode} onChange={(config) => store.updateNode(selected.id, { config })} />}{["subworkflow", "review_loop"].includes(selected.data.type) && <CompositeNodeConfig node={selected.data.workflowNode} workflows={(catalog.data?.items ?? []).filter((workflow) => workflow.id !== store.workflow.id)} onChange={(config) => store.updateNode(selected.id, { config })} />}{["prompt", "subworkflow", "review_loop"].includes(selected.data.type) ? <details className="advanced-json"><summary>Advanced configuration JSON</summary><label>Configuration JSON<textarea className="code-editor" value={configText} onChange={(event) => setConfigText(event.target.value)} onBlur={commitConfig} /></label></details> : <label>Configuration JSON<textarea className="code-editor" value={configText} onChange={(event) => setConfigText(event.target.value)} onBlur={commitConfig} /></label>}<p className="hint">Public placeholders use <code>{"${NAME}"}</code>. Secrets use shell-native <code>$NAME</code>.</p></> : <div className="inspector-empty"><span>◎</span><h3>Select a node</h3><p>Choose a card to edit it or store it as a reusable template.</p></div>}</aside></div>
    {interfaceOpen && <div className="modal-backdrop" onMouseDown={() => setInterfaceOpen(false)}><div className="modal interface-modal" onMouseDown={(event) => event.stopPropagation()}><h2>Workflow inputs & outputs</h2><p className="muted">These declarations become editable mapping rows when this workflow is selected by a sub-workflow or review-loop node.</p><WorkflowInterfaceEditor workflow={store.workflow} onChange={(patch) => store.patchWorkflow(patch)} /><footer><button type="button" onClick={() => setInterfaceOpen(false)}>Done</button></footer></div></div>}
    {templateNode && <div className="modal-backdrop"><form className="modal" onSubmit={submitTemplate}><h2>Store node as template</h2><label>Template ID<input name="id" required pattern="[A-Za-z][A-Za-z0-9_]*" defaultValue={`${templateNode.id}_template`} /></label><label>Name<input name="name" required defaultValue={templateNode.label} /></label><label>Description<textarea name="description" placeholder="When should this node be used?" /></label>{saveTemplate.error && <p className="error">{saveTemplate.error.message}</p>}<footer><button type="button" className="secondary" onClick={() => setTemplateNodeId(null)}>Cancel</button><button disabled={saveTemplate.isPending}>Store template</button></footer></form></div>}
    {notice && <div className="toast"><strong>{notice}</strong><span>Review it from the workflow catalog when ready.</span><button onClick={() => setNotice(null)}>Done</button></div>}
  </div>;
}

export function WorkflowBuilderPage() { return <ReactFlowProvider><Builder /></ReactFlowProvider>; }
