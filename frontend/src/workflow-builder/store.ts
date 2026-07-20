import { addEdge, applyEdgeChanges, applyNodeChanges, type Connection, type Edge, type EdgeChange, type Node, type NodeChange } from "@xyflow/react";
import { create } from "zustand";
import type { NodeType, Workflow, WorkflowNode } from "../types";

export type BuilderData = { workflowNode: WorkflowNode; label: string; type: NodeType };
export type BuilderNode = Node<BuilderData>;

const defaults: Record<NodeType, Record<string, unknown>> = {
  bash: { command: "echo 'Hello from Kyron'", timeout: 1800, allow_failure: false, shell: "/bin/bash" },
  script: { script: "scripts/task.py", python: "python3", args: [], timeout: 1800, allow_failure: false },
  prompt: { prompt: "Implement: ${TASK}", provider: "anthropic", model: "", timeout: 1800, allow_failure: false, project_trust: "never" },
  human_feedback: { commit_message: "Checkpoint: awaiting review", mr_title: "Workflow: ${WORKFLOW_NAME}", mr_description: "Approve or comment with @kyron feedback.", allow_comment_feedback: true, allow_approval: true },
  subworkflow: { workflow_id: "child_workflow", inputs: {}, output_mapping: {}, allow_failure: false },
  review_loop: { initial_workflow_id: "implement_changes", revision_workflow_id: "revise_from_feedback", inputs: {}, revision_inputs: { FEEDBACK: "${FEEDBACK}" }, commit_message: "Checkpoint: review iteration ${REVIEW_ITERATION}", max_iterations: 5, output_mapping: {} },
};

type BuilderStore = {
  workflow: Workflow;
  nodes: BuilderNode[];
  edges: Edge[];
  selectedNodeId: string | null;
  setWorkflow: (workflow: Workflow) => void;
  patchWorkflow: (patch: Partial<Workflow>) => void;
  onNodesChange: (changes: NodeChange<BuilderNode>[]) => void;
  onEdgesChange: (changes: EdgeChange[]) => void;
  connect: (connection: Connection) => void;
  addNode: (type: NodeType) => void;
  addTemplate: (node: WorkflowNode) => void;
  selectNode: (id: string | null) => void;
  updateNode: (id: string, patch: Partial<WorkflowNode>) => void;
  removeSelected: () => void;
  serialize: () => Workflow;
};

const initial: Workflow = { id: "new_workflow", name: "New workflow", description: "", version: 2, created_by: "", tags: [], inputs: {}, outputs: {}, variables: {}, nodes: [], edges: [], settings: {} };

function flowNode(node: WorkflowNode): BuilderNode {
  return { id: node.id, position: node.position, type: "workflow", data: { workflowNode: node, label: node.label, type: node.type } };
}

function uniqueNodeId(seed: string, nodes: BuilderNode[]): string {
  const base = seed.replace(/[^A-Za-z0-9_]/g, "_").replace(/^[^A-Za-z]+/, "") || "node";
  const ids = new Set(nodes.map((node) => node.id));
  if (!ids.has(base)) return base;
  let suffix = 2;
  while (ids.has(`${base}_${suffix}`)) suffix += 1;
  return `${base}_${suffix}`;
}

export const useBuilderStore = create<BuilderStore>((set, get) => ({
  workflow: initial, nodes: [], edges: [], selectedNodeId: null,
  setWorkflow: (workflow) => set({ workflow, nodes: workflow.nodes.map(flowNode), edges: workflow.edges.map((edge) => ({ ...edge, type: "smoothstep", data: { condition: edge.condition } })), selectedNodeId: null }),
  patchWorkflow: (patch) => set((state) => ({ workflow: { ...state.workflow, ...patch } })),
  onNodesChange: (changes) => set((state) => ({ nodes: applyNodeChanges(changes, state.nodes) })),
  onEdgesChange: (changes) => set((state) => ({ edges: applyEdgeChanges(changes, state.edges) })),
  connect: (connection) => set((state) => ({ edges: addEdge({ ...connection, id: `edge_${crypto.randomUUID().slice(0, 8)}`, type: "smoothstep", data: { condition: null } }, state.edges) })),
  addNode: (type) => set((state) => {
    const seed = `${type}_${state.nodes.length + 1}`.replaceAll("human_feedback", "feedback").replaceAll("review_loop", "review");
    const id = uniqueNodeId(seed, state.nodes);
    const workflowNode: WorkflowNode = { id, type, label: type.split("_").map((word) => word[0]?.toUpperCase() + word.slice(1)).join(" "), join: "and", config: structuredClone(defaults[type]), position: { x: 100 + (state.nodes.length % 3) * 260, y: 100 + Math.floor(state.nodes.length / 3) * 170 } };
    return { nodes: [...state.nodes, flowNode(workflowNode)], selectedNodeId: id };
  }),
  addTemplate: (templateNode) => set((state) => {
    const id = uniqueNodeId(templateNode.id, state.nodes);
    const index = state.nodes.length;
    const workflowNode: WorkflowNode = {
      ...structuredClone(templateNode),
      id,
      position: {
        x: 100 + (index % 3) * 260,
        y: 100 + Math.floor(index / 3) * 170,
      },
    };
    return { nodes: [...state.nodes, flowNode(workflowNode)], selectedNodeId: id };
  }),
  selectNode: (id) => set({ selectedNodeId: id }),
  updateNode: (id, patch) => set((state) => ({ nodes: state.nodes.map((node) => { if (node.id !== id) return node; const workflowNode = { ...node.data.workflowNode, ...patch }; return { ...node, data: { ...node.data, workflowNode, label: workflowNode.label, type: workflowNode.type } }; }) })),
  removeSelected: () => set((state) => state.selectedNodeId ? ({ nodes: state.nodes.filter((node) => node.id !== state.selectedNodeId), edges: state.edges.filter((edge) => edge.source !== state.selectedNodeId && edge.target !== state.selectedNodeId), selectedNodeId: null }) : state),
  serialize: () => { const state = get(); return { ...state.workflow, nodes: state.nodes.map((node) => ({ ...node.data.workflowNode, position: node.position })), edges: state.edges.map((edge) => ({ id: edge.id, source: edge.source, target: edge.target, condition: (edge.data?.condition as Record<string, unknown> | null) ?? null })) }; },
}));

export function wouldCreateCycle(connection: Connection | Edge, nodes: BuilderNode[], edges: Edge[]): boolean {
  if (!connection.source || !connection.target || connection.source === connection.target) return true;
  const adjacency = new Map<string, string[]>();
  for (const node of nodes) adjacency.set(node.id, []);
  for (const edge of edges) adjacency.get(edge.source)?.push(edge.target);
  adjacency.get(connection.source)?.push(connection.target);
  const stack = [connection.target]; const visited = new Set<string>();
  while (stack.length) { const current = stack.pop()!; if (current === connection.source) return true; if (visited.has(current)) continue; visited.add(current); stack.push(...(adjacency.get(current) ?? [])); }
  return false;
}
