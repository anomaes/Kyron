import type { Workflow, WorkflowNode } from "../types";

type Props = {
  node: WorkflowNode;
  workflows: Workflow[];
  onChange: (config: Record<string, unknown>) => void;
};

function record(value: unknown): Record<string, string> {
  if (!value || typeof value !== "object" || Array.isArray(value)) return {};
  return Object.fromEntries(
    Object.entries(value).filter((entry): entry is [string, string] => typeof entry[1] === "string"),
  );
}

function WorkflowPicker({
  id,
  label,
  value,
  workflows,
  optional = false,
  onChange,
}: {
  id: string;
  label: string;
  value: string;
  workflows: Workflow[];
  optional?: boolean;
  onChange: (value: string) => void;
}) {
  const listId = `${id}-workflow-options`;
  const selected = workflows.find((workflow) => workflow.id === value);
  return <label>{label}<input list={listId} value={value} placeholder={optional ? "Search workflows (optional)…" : "Search workflows…"} onChange={(event) => onChange(event.target.value)} /><datalist id={listId}>{workflows.map((workflow) => <option key={workflow.id} value={workflow.id}>{workflow.name}{workflow.tags.length ? ` · ${workflow.tags.join(", ")}` : ""}</option>)}</datalist>{selected && <span className="field-help">{selected.name}{selected.tags.length ? ` · ${selected.tags.join(" · ")}` : ""}</span>}</label>;
}

function MappingFields({
  title,
  definitions,
  values,
  valuePlaceholder,
  onChange,
}: {
  title: string;
  definitions: Record<string, { required?: boolean; description?: string }>;
  values: Record<string, string>;
  valuePlaceholder: string;
  onChange: (values: Record<string, string>) => void;
}) {
  const names = Array.from(new Set([...Object.keys(definitions), ...Object.keys(values)])).sort();
  if (!names.length) return <div className="mapping-section"><strong>{title}</strong><p className="field-help">The selected workflow does not declare any fields here.</p></div>;
  return <div className="mapping-section"><strong>{title}</strong>{names.map((name) => <label key={name}><span>{name}{definitions[name]?.required ? " *" : ""}</span><input value={values[name] ?? ""} placeholder={valuePlaceholder} onChange={(event) => { const next = { ...values }; const value = event.target.value; if (value) next[name] = value; else delete next[name]; onChange(next); }} />{definitions[name]?.description && <span className="field-help">{definitions[name].description}</span>}</label>)}</div>;
}

export function CompositeNodeConfig({ node, workflows, onChange }: Props) {
  const config = node.config;
  const set = (key: string, value: unknown) => onChange({ ...config, [key]: value });
  const workflowFor = (key: string) => workflows.find((workflow) => workflow.id === config[key]);

  if (node.type === "subworkflow") {
    const child = workflowFor("workflow_id");
    return <div className="structured-config">
      <WorkflowPicker id={`${node.id}-child`} label="Child workflow" value={String(config.workflow_id ?? "")} workflows={workflows} onChange={(value) => set("workflow_id", value)} />
      <MappingFields title="Input mappings" definitions={child?.inputs ?? {}} values={record(config.inputs)} valuePlaceholder="${PARENT_VARIABLE}" onChange={(value) => set("inputs", value)} />
      <MappingFields title="Output mappings" definitions={child?.outputs ?? {}} values={record(config.output_mapping)} valuePlaceholder="PARENT_VARIABLE" onChange={(value) => set("output_mapping", value)} />
      <label className="check-field"><input type="checkbox" checked={Boolean(config.allow_failure)} onChange={(event) => set("allow_failure", event.target.checked)} />Allow failure</label>
    </div>;
  }

  if (node.type !== "review_loop") return null;
  const initial = workflowFor("initial_workflow_id");
  const revision = workflowFor("revision_workflow_id");
  const outputDefinitions = initial?.outputs ?? revision?.outputs ?? {};
  return <div className="structured-config">
    <WorkflowPicker id={`${node.id}-initial`} label="Initial workflow" value={String(config.initial_workflow_id ?? "")} workflows={workflows} onChange={(value) => set("initial_workflow_id", value)} />
    <MappingFields title="Initial input mappings" definitions={initial?.inputs ?? {}} values={record(config.inputs)} valuePlaceholder="${PARENT_VARIABLE}" onChange={(value) => set("inputs", value)} />
    <WorkflowPicker id={`${node.id}-revision`} label="Revision workflow" optional value={String(config.revision_workflow_id ?? "")} workflows={workflows} onChange={(value) => set("revision_workflow_id", value || null)} />
    <MappingFields title="Revision input mappings" definitions={revision?.inputs ?? initial?.inputs ?? {}} values={record(config.revision_inputs)} valuePlaceholder="${FEEDBACK}" onChange={(value) => set("revision_inputs", value)} />
    <MappingFields title="Output mappings" definitions={outputDefinitions} values={record(config.output_mapping)} valuePlaceholder="PARENT_VARIABLE" onChange={(value) => set("output_mapping", value)} />
    <label>Maximum iterations<input type="number" min={1} value={Number(config.max_iterations ?? 5)} onChange={(event) => set("max_iterations", Number(event.target.value))} /></label>
    <label>Checkpoint commit message<input value={String(config.commit_message ?? "")} onChange={(event) => set("commit_message", event.target.value)} /></label>
    <label>Merge request title<input value={String(config.mr_title ?? "")} placeholder="Use workflow default" onChange={(event) => set("mr_title", event.target.value || null)} /></label>
    <label>Merge request description<textarea value={String(config.mr_description ?? "")} placeholder="Use workflow default" onChange={(event) => set("mr_description", event.target.value || null)} /></label>
  </div>;
}
