import { describe, expect, it } from "vitest";
import type { BuilderDisplayNode } from "./projection";
import {
  applyTransientPositionChanges,
  applyTransientPositions,
} from "./preview-interactions";

const editable = {
  id: "parent",
  position: { x: 10, y: 20 },
  data: {
    kind: "editable",
    workflowNode: {
      id: "parent",
      type: "bash",
      label: "Parent",
      config: { command: "true" },
      position: { x: 10, y: 20 },
    },
    label: "Parent",
    type: "bash",
  },
} satisfies BuilderDisplayNode;

const preview = {
  id: "preview/root::call/node::child",
  position: { x: 32, y: 136 },
  data: {
    kind: "preview",
    instanceKey: "root::call::child::child",
    topLevelKey: "root::call",
    workflowNode: {
      id: "child",
      type: "bash",
      label: "Child",
      config: { command: "true" },
      position: { x: 0, y: 0 },
    },
    workflowId: "child_workflow",
    workflowName: "Child workflow",
    depth: 1,
    breadcrumb: ["Parent"],
  },
} satisfies BuilderDisplayNode;

describe("transient preview dragging", () => {
  it("moves only real parent nodes in the display projection", () => {
    const positions = applyTransientPositionChanges(
      new Map(),
      [
        { id: editable.id, type: "position", position: { x: 300, y: 240 }, dragging: true },
        { id: preview.id, type: "position", position: { x: 500, y: 500 }, dragging: true },
      ],
      new Set([editable.id]),
    );
    const displayed = applyTransientPositions([editable, preview], positions);

    expect(displayed[0]?.position).toEqual({ x: 300, y: 240 });
    expect(displayed[1]?.position).toEqual(preview.position);
    expect(editable.position).toEqual({ x: 10, y: 20 });
    expect(editable.data.workflowNode.position).toEqual({ x: 10, y: 20 });
  });

  it("returns the existing map when changes contain no movable position", () => {
    const current = new Map([["parent", { x: 100, y: 100 }]]);
    const result = applyTransientPositionChanges(
      current,
      [{ id: preview.id, type: "position", position: { x: 500, y: 500 }, dragging: false }],
      new Set(["parent"]),
    );

    expect(result).toBe(current);
  });
});

