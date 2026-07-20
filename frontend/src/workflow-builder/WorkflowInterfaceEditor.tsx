import { useState } from "react";
import type { Workflow } from "../types";

type InputDefinition = Workflow["inputs"][string];
type OutputDefinition = Workflow["outputs"][string];
type ValueType = "string" | "integer" | "number" | "boolean";

type Props = {
  workflow: Workflow;
  onChange: (patch: Pick<Workflow, "inputs" | "outputs">) => void;
};

const identifier = /^[A-Za-z][A-Za-z0-9_]*$/;

export function WorkflowInterfaceEditor({ workflow, onChange }: Props) {
  const [inputName, setInputName] = useState("");
  const [outputName, setOutputName] = useState("");
  const patchInput = (name: string, patch: Partial<InputDefinition>) => { const current = workflow.inputs[name] ?? { type: "string" }; onChange({ inputs: { ...workflow.inputs, [name]: { ...current, ...patch } }, outputs: workflow.outputs }); };
  const patchOutput = (name: string, patch: Partial<OutputDefinition>) => { const current = workflow.outputs[name] ?? { type: "string", source: "" }; onChange({ inputs: workflow.inputs, outputs: { ...workflow.outputs, [name]: { ...current, ...patch } } }); };
  const removeInput = (name: string) => { const inputs = { ...workflow.inputs }; delete inputs[name]; onChange({ inputs, outputs: workflow.outputs }); };
  const removeOutput = (name: string) => { const outputs = { ...workflow.outputs }; delete outputs[name]; onChange({ inputs: workflow.inputs, outputs }); };
  const addInput = () => { if (!identifier.test(inputName) || workflow.inputs[inputName]) return; onChange({ inputs: { ...workflow.inputs, [inputName]: { type: "string", required: false } }, outputs: workflow.outputs }); setInputName(""); };
  const addOutput = () => { if (!identifier.test(outputName) || workflow.outputs[outputName]) return; onChange({ inputs: workflow.inputs, outputs: { ...workflow.outputs, [outputName]: { type: "string", source: `\${${outputName}}` } } }); setOutputName(""); };
  return <div className="interface-editor">
    <section><h3>Inputs</h3><p>Inputs are values supplied by a trigger or mapped from a parent workflow.</p>{Object.entries(workflow.inputs).map(([name, definition]) => <div className="interface-row" key={name}><div className="interface-row-title"><code>{name}</code><button type="button" className="danger-link" onClick={() => removeInput(name)}>Remove</button></div><div className="form-row"><label>Type<select value={definition.type} onChange={(event) => patchInput(name, { type: event.target.value as ValueType })}><option>string</option><option>integer</option><option>number</option><option>boolean</option></select></label><label className="check-field"><input type="checkbox" checked={Boolean(definition.required)} onChange={(event) => patchInput(name, { required: event.target.checked })} />Required</label></div><label>Description<input value={definition.description ?? ""} onChange={(event) => patchInput(name, { description: event.target.value || undefined })} /></label></div>)}<div className="interface-add"><input value={inputName} placeholder="NEW_INPUT" onChange={(event) => setInputName(event.target.value)} /><button type="button" disabled={!identifier.test(inputName) || Boolean(workflow.inputs[inputName])} onClick={addInput}>Add input</button></div></section>
    <section><h3>Outputs</h3><p>Outputs expose a public-context expression to parent workflows.</p>{Object.entries(workflow.outputs).map(([name, definition]) => <div className="interface-row" key={name}><div className="interface-row-title"><code>{name}</code><button type="button" className="danger-link" onClick={() => removeOutput(name)}>Remove</button></div><div className="form-row"><label>Type<select value={definition.type} onChange={(event) => patchOutput(name, { type: event.target.value as ValueType })}><option>string</option><option>integer</option><option>number</option><option>boolean</option></select></label><label>Source<input value={definition.source} placeholder="${NODE_STDOUT}" onChange={(event) => patchOutput(name, { source: event.target.value })} /></label></div><label>Description<input value={definition.description ?? ""} onChange={(event) => patchOutput(name, { description: event.target.value || undefined })} /></label></div>)}<div className="interface-add"><input value={outputName} placeholder="RESULT" onChange={(event) => setOutputName(event.target.value)} /><button type="button" disabled={!identifier.test(outputName) || Boolean(workflow.outputs[outputName])} onClick={addOutput}>Add output</button></div></section>
  </div>;
}
