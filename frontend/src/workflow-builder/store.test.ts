import { beforeEach, describe, expect, it } from "vitest";
import type { Workflow, WorkflowNode } from "../types";
import { applyTransientPositionChanges, applyTransientPositions } from "./preview-interactions";
import { projectBuilderGraph, topLevelInstanceKey } from "./projection";
import { useBuilderStore, wouldCreateCycle } from "./store";

function node(id: string, type: WorkflowNode["type"], x: number, config: Record<string, unknown>): WorkflowNode {
  return { id, type, label: id, join: "and", config, position: { x, y: 20 } };
}

const parent: Workflow = {
  id: "parent",
  name: "Parent",
  description: "",
  version: 2,
  created_by: "test",
  tags: [],
  inputs: {},
  outputs: {},
  variables: {},
  nodes: [
    node("start", "bash", 0, { command: "echo start" }),
    node("child_call", "subworkflow", 220, { workflow_id: "child", execution_mode: "shared" }),
    node("finish", "bash", 440, { command: "echo finish" }),
  ],
  edges: [
    { id: "first", source: "start", target: "child_call", condition: null },
    { id: "second", source: "child_call", target: "finish", condition: null },
  ],
  settings: {},
};

const child: Workflow = {
  ...parent,
  id: "child",
  name: "Child",
  nodes: [node("task", "script", -400, { script: "scripts/task.py" })],
  edges: [],
};

describe("builder store serialization isolation", () => {
  beforeEach(() => {
    useBuilderStore.getState().setWorkflow(structuredClone(parent));
  });

  it("is byte-for-byte unchanged by expansion, collision projection, and collapse", () => {
    const store = useBuilderStore.getState();
    const before = store.serialize();
    const key = topLevelInstanceKey("child_call");
    const projection = projectBuilderGraph({
      rootWorkflow: store.workflow,
      editableNodes: store.nodes,
      editableEdges: store.edges,
      catalogById: new Map([[child.id, child]]),
      catalogStatus: "ready",
      expansion: {
        activeTopLevelKey: key,
        expandedKeys: new Set([key]),
        reviewTabs: new Map(),
        referenceByKey: new Map([[key, "child"]]),
      },
    });
    const transientPositions = applyTransientPositionChanges(
      new Map(),
      [{ id: "finish", type: "position", position: { x: 900, y: 600 }, dragging: false }],
      projection.realNodeIds,
    );
    const temporarilyMoved = applyTransientPositions(projection.nodes, transientPositions);
    const afterExpansion = useBuilderStore.getState().serialize();
    const afterCollapse = projectBuilderGraph({
      rootWorkflow: store.workflow,
      editableNodes: store.nodes,
      editableEdges: store.edges,
      catalogById: new Map([[child.id, child]]),
      catalogStatus: "ready",
      expansion: {
        activeTopLevelKey: null,
        expandedKeys: new Set(),
        reviewTabs: new Map(),
        referenceByKey: new Map(),
      },
    });

    expect(projection.nodes.some((item) => item.id.startsWith("preview/"))).toBe(true);
    expect(temporarilyMoved.find((item) => item.id === "finish")?.position).toEqual({ x: 900, y: 600 });
    expect(afterExpansion).toEqual(before);
    expect(afterCollapse.nodes.map((item) => item.position)).toEqual(store.nodes.map((item) => item.position));
    expect(JSON.stringify(afterExpansion)).toBe(JSON.stringify(before));
    expect(JSON.stringify(afterExpansion)).not.toContain("preview/");
  });

  it("retains collapsed add, update, delete, and connect behavior", () => {
    const store = useBuilderStore.getState();
    store.addNode("prompt");
    const addedId = useBuilderStore.getState().selectedNodeId;
    expect(addedId).toBeTruthy();
    useBuilderStore.getState().updateNode(addedId!, { label: "Updated prompt" });
    expect(useBuilderStore.getState().nodes.find((item) => item.id === addedId)?.data.label).toBe("Updated prompt");
    useBuilderStore.getState().connect({ source: "finish", target: addedId!, sourceHandle: null, targetHandle: null });
    expect(useBuilderStore.getState().edges.some((item) => item.source === "finish" && item.target === addedId)).toBe(true);
    useBuilderStore.getState().removeSelected();
    expect(useBuilderStore.getState().nodes.some((item) => item.id === addedId)).toBe(false);
    expect(useBuilderStore.getState().edges.some((item) => item.target === addedId)).toBe(false);
  });

  it("continues to reject root DAG cycles", () => {
    const store = useBuilderStore.getState();

    expect(wouldCreateCycle(
      { source: "finish", target: "start", sourceHandle: null, targetHandle: null },
      store.nodes,
      store.edges,
    )).toBe(true);
    expect(wouldCreateCycle(
      { source: "start", target: "finish", sourceHandle: null, targetHandle: null },
      store.nodes,
      store.edges,
    )).toBe(false);
  });
});
