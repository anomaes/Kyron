import type { Edge } from "@xyflow/react";
import { describe, expect, it } from "vitest";
import type { Workflow, WorkflowEdge, WorkflowNode } from "../types";
import type { BuilderNode } from "./store";
import {
  MAX_VISIBLE_PREVIEW_NODES,
  PREVIEW_ID_PREFIX,
  nestedInstanceKey,
  previewNodeId,
  projectBuilderGraph,
  topLevelInstanceKey,
  type BuilderProjectionInput,
  type ExpansionSnapshot,
} from "./projection";
import { COMPOSITE_HEADER_HEIGHT, COMPOSITE_PADDING } from "./preview-layout";

function node(
  id: string,
  type: WorkflowNode["type"] = "bash",
  position = { x: 0, y: 0 },
  config: Record<string, unknown> = type === "bash" ? { command: `echo ${id}` } : {},
): WorkflowNode {
  return { id, type, label: id, position, config, join: "and" };
}

function workflow(
  id: string,
  nodes: WorkflowNode[],
  edges: WorkflowEdge[] = [],
): Workflow {
  return {
    id,
    name: `${id} name`,
    description: "",
    version: 2,
    created_by: "test",
    tags: [],
    inputs: {},
    outputs: {},
    variables: {},
    nodes,
    edges,
    settings: {},
  };
}

function builderNodes(nodes: WorkflowNode[]): BuilderNode[] {
  return nodes.map((workflowNode) => ({
    id: workflowNode.id,
    type: "workflow",
    position: { ...workflowNode.position },
    data: {
      kind: "editable",
      workflowNode,
      label: workflowNode.label,
      type: workflowNode.type,
    },
  }));
}

function edge(source: string, target: string, id = `${source}_${target}`): WorkflowEdge {
  return { id, source, target, condition: null };
}

function flowEdges(edges: WorkflowEdge[]): Edge[] {
  return edges.map((item) => ({
    ...item,
    type: "smoothstep",
    data: { condition: item.condition },
  }));
}

function expansion(
  activeTopLevelKey: string | null,
  expandedKeys: string[] = activeTopLevelKey ? [activeTopLevelKey] : [],
  reviewTabs: Array<[string, "initial" | "revision"]> = [],
  references: Array<[string, string]> = [],
): ExpansionSnapshot {
  return {
    activeTopLevelKey,
    expandedKeys: new Set(expandedKeys),
    reviewTabs: new Map(reviewTabs),
    referenceByKey: new Map(references),
  };
}

function input(
  root: Workflow,
  catalog: Workflow[],
  state: ExpansionSnapshot,
  status: BuilderProjectionInput["catalogStatus"] = "ready",
): BuilderProjectionInput {
  return {
    rootWorkflow: root,
    editableNodes: builderNodes(root.nodes),
    editableEdges: flowEdges(root.edges),
    catalogById: new Map(catalog.map((item) => [item.id, item])),
    catalogStatus: status,
    expansion: state,
  };
}

describe("projectBuilderGraph", () => {
  it("leaves a collapsed authored graph structurally unchanged", () => {
    const root = workflow("root", [node("a"), node("b", "bash", { x: 240, y: 0 })], [edge("a", "b")]);
    const source = input(root, [], expansion(null));
    const result = projectBuilderGraph(source);

    expect(result.hasExpandedPreview).toBe(false);
    expect(result.nodes).toEqual(source.editableNodes);
    expect(result.edges).toEqual(source.editableEdges);
    expect(result.previewNodeIds.size).toBe(0);
  });

  it("expands the referenced child without changing the real call or external edge IDs", () => {
    const call = node("quality", "subworkflow", { x: 220, y: 0 }, { workflow_id: "checks", execution_mode: "shared" });
    const root = workflow("root", [node("start"), call, node("finish", "bash", { x: 500, y: 0 })], [
      edge("start", "quality", "into_quality"),
      edge("quality", "finish", "out_of_quality"),
    ]);
    const child = workflow("checks", [
      node("lint", "bash", { x: -100, y: -50 }),
      node("test", "script", { x: 120, y: 30 }),
    ], [edge("lint", "test", "lint_to_test")]);
    const key = topLevelInstanceKey("quality");
    const source = input(root, [child], expansion(key, [key], [], [[key, "checks"]]));
    const before = structuredClone({ root, child, nodes: source.editableNodes, edges: source.editableEdges });

    const result = projectBuilderGraph(source);

    expect(result.hasExpandedPreview).toBe(true);
    expect(result.nodes.find((item) => item.id === "quality")?.data.kind).toBe("composite");
    expect(result.edges.filter((item) => !item.id.startsWith(PREVIEW_ID_PREFIX)).map((item) => item.id)).toEqual([
      "into_quality",
      "out_of_quality",
    ]);
    expect(result.edges.find((item) => item.id.includes("lint_to_test"))).toMatchObject({
      source: previewNodeId(key, "lint"),
      target: previewNodeId(key, "test"),
    });
    expect([...result.previewNodeIds].every((id) => id.startsWith(PREVIEW_ID_PREFIX))).toBe(true);
    expect({ root, child, nodes: source.editableNodes, edges: source.editableEdges }).toEqual(before);
  });

  it("normalizes negative child coordinates while preserving relative geometry", () => {
    const call = node("call", "subworkflow", { x: 20, y: 30 }, { workflow_id: "child" });
    const root = workflow("root", [call]);
    const child = workflow("child", [
      node("left", "bash", { x: -500, y: -300 }),
      node("right", "bash", { x: -200, y: -100 }),
    ]);
    const key = topLevelInstanceKey("call");
    const result = projectBuilderGraph(input(root, [child], expansion(key, [key], [], [[key, "child"]])));
    const left = result.nodes.find((item) => item.id === previewNodeId(key, "left"));
    const right = result.nodes.find((item) => item.id === previewNodeId(key, "right"));

    if (!left || !right) throw new Error("Expected both projected child nodes");
    expect(left?.position).toEqual({ x: COMPOSITE_PADDING, y: COMPOSITE_HEADER_HEIGHT + COMPOSITE_PADDING });
    expect(right.position.x - left.position.x).toBe(300);
    expect(right.position.y - left.position.y).toBe(200);
  });

  it("does not mount nodes beyond a clamped composite boundary", () => {
    const call = node("call", "subworkflow", { x: 0, y: 0 }, { workflow_id: "sparse" });
    const root = workflow("root", [call]);
    const child = workflow("sparse", [
      node("near", "bash", { x: 0, y: 0 }),
      node("far", "bash", { x: 20_000, y: 20_000 }),
    ]);
    const key = topLevelInstanceKey("call");
    const result = projectBuilderGraph(input(root, [child], expansion(key, [key], [], [[key, "sparse"]])));

    expect(result.nodes.some((item) => item.id === previewNodeId(key, "near"))).toBe(true);
    expect(result.nodes.some((item) => item.id === previewNodeId(key, "far"))).toBe(false);
    expect(result.warnings).toContainEqual({ instanceKey: key, message: "Preview truncated" });
  });

  it.each([
    ["loading", "Loading preview"],
    ["error", "Preview unavailable"],
    ["ready", "Referenced workflow not found"],
  ] as const)("renders a safe %s catalog state", (status, message) => {
    const call = node("call", "subworkflow", { x: 0, y: 0 }, { workflow_id: "missing" });
    const root = workflow("root", [call]);
    const key = topLevelInstanceKey("call");
    const result = projectBuilderGraph(input(root, [], expansion(key, [key], [], [[key, "missing"]]), status));
    const container = result.nodes.find((item) => item.id === "call");

    expect(container?.data).toMatchObject({ kind: "composite", warning: message });
  });

  it("renders an explicit empty state for an existing child", () => {
    const call = node("call", "subworkflow", { x: 0, y: 0 }, { workflow_id: "empty" });
    const root = workflow("root", [call]);
    const key = topLevelInstanceKey("call");
    const result = projectBuilderGraph(input(root, [workflow("empty", [])], expansion(key, [key], [], [[key, "empty"]])));

    expect(result.nodes[0]?.data).toMatchObject({ kind: "composite", empty: true });
  });

  it("orders nested composite parents before descendants and stops recursion", () => {
    const rootCall = node("call", "subworkflow", { x: 0, y: 0 }, { workflow_id: "child" });
    const nestedCall = node("again", "subworkflow", { x: 0, y: 0 }, { workflow_id: "root" });
    const root = workflow("root", [rootCall]);
    const child = workflow("child", [nestedCall]);
    const rootKey = topLevelInstanceKey("call");
    const nestedKey = nestedInstanceKey(rootKey, "child", "again");
    const result = projectBuilderGraph(input(
      root,
      [child, root],
      expansion(rootKey, [rootKey, nestedKey], [], [[rootKey, "child"], [nestedKey, "root"]]),
    ));
    const nestedId = previewNodeId(rootKey, "again");
    const nestedIndex = result.nodes.findIndex((item) => item.id === nestedId);

    expect(result.nodes.findIndex((item) => item.id === "call")).toBeLessThan(nestedIndex);
    expect(result.nodes[nestedIndex]?.data).toMatchObject({
      kind: "composite",
      warning: "Recursive reference cannot be previewed",
    });
  });

  it("selects the configured review-loop branch and removes the inactive graph", () => {
    const review = node("review", "review_loop", { x: 0, y: 0 }, {
      initial_workflow_id: "initial",
      revision_workflow_id: "revision",
    });
    const root = workflow("root", [review]);
    const initial = workflow("initial", [node("implement")]);
    const revision = workflow("revision", [node("revise")]);
    const key = topLevelInstanceKey("review");
    const result = projectBuilderGraph(input(
      root,
      [initial, revision],
      expansion(key, [key], [[key, "revision"]], [[key, "revision"]]),
    ));

    expect(result.nodes.some((item) => item.id === previewNodeId(key, "revise"))).toBe(true);
    expect(result.nodes.some((item) => item.id === previewNodeId(key, "implement"))).toBe(false);
    expect(result.nodes[0]?.data).toMatchObject({ kind: "composite", branch: "revision" });
  });

  it("invalidates an expanded branch when its configured reference changes", () => {
    const call = node("call", "subworkflow", { x: 0, y: 0 }, { workflow_id: "new_child" });
    const root = workflow("root", [call]);
    const key = topLevelInstanceKey("call");
    const result = projectBuilderGraph(input(
      root,
      [workflow("new_child", [node("task")])],
      expansion(key, [key], [], [[key, "old_child"]]),
    ));

    expect(result.hasExpandedPreview).toBe(false);
    expect(result.previewNodeIds.size).toBe(0);
  });

  it("enforces the visible-node budget deterministically", () => {
    const call = node("call", "subworkflow", { x: 0, y: 0 }, { workflow_id: "large" });
    const root = workflow("root", [call]);
    const child = workflow("large", Array.from({ length: MAX_VISIBLE_PREVIEW_NODES + 10 }, (_, index) => (
      node(`node_${index}`, "bash", { x: (index % 20) * 100, y: Math.floor(index / 20) * 100 })
    )));
    const key = topLevelInstanceKey("call");
    const result = projectBuilderGraph(input(root, [child], expansion(key, [key], [], [[key, "large"]])));
    const previews = result.nodes.filter((item) => item.data.kind === "preview");

    expect(previews).toHaveLength(MAX_VISIBLE_PREVIEW_NODES);
    expect(previews.at(-1)?.data).toMatchObject({ kind: "preview", workflowNode: { id: "node_249" } });
    expect(result.warnings).toContainEqual({ instanceKey: key, message: "Preview truncated" });
  });

  it("bounds nested expansion depth", () => {
    const rootCall = node("call_0", "subworkflow", { x: 0, y: 0 }, { workflow_id: "level_1" });
    const root = workflow("root", [rootCall]);
    const catalog: Workflow[] = [];
    const keys = [topLevelInstanceKey("call_0")];
    const references: Array<[string, string]> = [[keys[0]!, "level_1"]];
    let parentKey = keys[0]!;
    for (let level = 1; level <= 9; level += 1) {
      const nextId = `level_${level + 1}`;
      const callId = `call_${level}`;
      catalog.push(workflow(`level_${level}`, [
        node(callId, "subworkflow", { x: 0, y: 0 }, { workflow_id: nextId }),
      ]));
      const key = nestedInstanceKey(parentKey, `level_${level}`, callId);
      keys.push(key);
      references.push([key, nextId]);
      parentKey = key;
    }
    catalog.push(workflow("level_10", [node("leaf")]));

    const result = projectBuilderGraph(input(root, catalog, expansion(keys[0]!, keys, [], references)));

    expect(result.warnings.some((warning) => warning.message === "Preview depth limit reached")).toBe(true);
    expect(result.nodes.length).toBeLessThan(15);
  });

  it("uses distinct deterministic namespaces for separate call sites", () => {
    const first = topLevelInstanceKey("first");
    const second = topLevelInstanceKey("second");

    expect(previewNodeId(first, "task")).toBe(previewNodeId(first, "task"));
    expect(previewNodeId(first, "task")).not.toBe(previewNodeId(second, "task"));
    expect(previewNodeId(first, "task")).not.toBe("task");
  });
});
