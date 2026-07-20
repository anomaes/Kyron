import type { WorkflowNode } from "../types";

type Props = {
  node: WorkflowNode;
  onChange: (config: Record<string, unknown>) => void;
};

export function PromptNodeConfig({ node, onChange }: Props) {
  const config = node.config;
  const set = (key: string, value: unknown) => onChange({ ...config, [key]: value });
  return <div className="structured-config">
    <label>Prompt<textarea className="prompt-editor" value={String(config.prompt ?? "")} placeholder="Describe what Pi should implement…" onChange={(event) => set("prompt", event.target.value)} /><span className="field-help">Public workflow values use placeholders such as {"${TASK}"}.</span></label>
    <label>Provider<input value={String(config.provider ?? "")} placeholder="Inherit workflow or project default" onChange={(event) => set("provider", event.target.value || null)} /></label>
    <label>Model<input value={String(config.model ?? "")} placeholder="Inherit workflow or project default" onChange={(event) => set("model", event.target.value || null)} /></label>
    <label>Skill path<input value={String(config.skill ?? "")} placeholder="Optional repository skill" onChange={(event) => set("skill", event.target.value || null)} /></label>
    <label>Timeout in seconds<input type="number" min={1} value={Number(config.timeout ?? 1800)} onChange={(event) => set("timeout", Number(event.target.value))} /></label>
    <label className="check-field"><input type="checkbox" checked={Boolean(config.allow_failure)} onChange={(event) => set("allow_failure", event.target.checked)} />Allow failure</label>
  </div>;
}
