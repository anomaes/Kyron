import { ReactFlowProvider, type Node, type NodeProps } from "@xyflow/react";
import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { Workflow, WorkflowNode } from "../types";
import { CompositePreviewNode } from "./CompositePreviewNode";
import { WorkflowExpansionProvider, useWorkflowExpansion } from "./expansion-context";
import type { CompositeContainerData } from "./projection";
import type { BuilderNode } from "./store";
import { WorkflowCard } from "./WorkflowCard";

function workflow(id: string, nodes: WorkflowNode[] = []): Workflow {
  return {
    id,
    name: id === "child" ? "Quality checks" : `${id} workflow`,
    description: "",
    version: 2,
    created_by: "test",
    tags: [],
    inputs: {},
    outputs: {},
    variables: {},
    nodes,
    edges: [],
    settings: {},
  };
}

function callNode(type: "subworkflow" | "review_loop", config: Record<string, unknown>): WorkflowNode {
  return { id: "call", type, label: "Quality gate", position: { x: 0, y: 0 }, config };
}

function builderProps(node: BuilderNode): NodeProps<BuilderNode> {
  return {
  id: node.id,
  data: node.data,
  type: "workflow",
  selected: false,
  dragging: false,
  draggable: false,
  selectable: true,
  deletable: false,
  isConnectable: false,
  zIndex: 0,
  positionAbsoluteX: 0,
  positionAbsoluteY: 0,
  } as NodeProps<BuilderNode>;
}

type CompositeFlowNode = Node<CompositeContainerData>;

function compositeProps(id: string, data: CompositeContainerData): NodeProps<CompositeFlowNode> {
  return {
    id,
    data,
    type: "compositePreview",
    selected: false,
    dragging: false,
    draggable: false,
    selectable: true,
    deletable: false,
    isConnectable: false,
    zIndex: 0,
    positionAbsoluteX: 0,
    positionAbsoluteY: 0,
  } as NodeProps<CompositeFlowNode>;
}

function Providers({ catalog, children }: { catalog: Workflow[]; children: React.ReactNode }) {
  return <ReactFlowProvider><WorkflowExpansionProvider
    projectId="project"
    catalogById={new Map(catalog.map((item) => [item.id, item]))}
    catalogStatus="ready"
    resetKey="project:parent"
  >{children}</WorkflowExpansionProvider></ReactFlowProvider>;
}

describe("collapsed workflow cards", () => {
  it("offers a semantic expansion control without bubbling selection", async () => {
    const user = userEvent.setup();
    const child = workflow("child", [{ id: "task", type: "bash", label: "Task", position: { x: 0, y: 0 }, config: { command: "true" } }]);
    const workflowNode = callNode("subworkflow", { workflow_id: "child" });
    const card: BuilderNode = {
      id: "call",
      type: "workflow",
      position: { x: 0, y: 0 },
      data: { kind: "editable", workflowNode, label: workflowNode.label, type: workflowNode.type },
    };
    const parentClick = vi.fn();
    render(<Providers catalog={[child]}><div onClick={parentClick}><WorkflowCard {...builderProps(card)} /></div></Providers>);

    const button = screen.getByRole("button", { name: "Expand Quality checks" });
    expect(button).toHaveAttribute("aria-expanded", "false");
    expect(button).toHaveClass("nodrag", "nopan");
    await user.click(button);
    expect(parentClick).not.toHaveBeenCalled();
  });

  it("communicates a missing reference and disables expansion", () => {
    const workflowNode = callNode("subworkflow", { workflow_id: "missing" });
    const card: BuilderNode = {
      id: "call",
      type: "workflow",
      position: { x: 0, y: 0 },
      data: { kind: "editable", workflowNode, label: workflowNode.label, type: workflowNode.type },
    };
    render(<Providers catalog={[]}><WorkflowCard {...builderProps(card)} /></Providers>);

    expect(screen.getByText("Referenced workflow not found")).toBeVisible();
    expect(screen.getByRole("button", { name: "Expand missing" })).toBeDisabled();
  });
});

function ReviewHarness({ initial, revision }: { initial: Workflow; revision: Workflow }) {
  const expansion = useWorkflowExpansion();
  const instanceKey = "root::review";
  const branch = expansion.snapshot.reviewTabs.get(instanceKey) ?? "initial";
  const workflowNode = callNode("review_loop", {
    initial_workflow_id: initial.id,
    revision_workflow_id: revision.id,
    approval_policy: "release",
    max_iterations: 4,
  });
  const data: CompositeContainerData = {
    kind: "composite",
    instanceKey,
    topLevelKey: instanceKey,
    callNode: workflowNode,
    childWorkflow: branch === "initial" ? initial : revision,
    branch,
    depth: 0,
    breadcrumb: ["Parent"],
    empty: false,
    truncated: false,
    clamped: false,
  };
  return <>
    <CompositePreviewNode {...compositeProps("review", data)} />
    <div aria-live="polite">{expansion.liveMessage}</div>
  </>;
}

describe("expanded composite controls", () => {
  it("uses accessible review tabs with keyboard navigation", () => {
    const initial = workflow("initial", [{ id: "implement", type: "bash", label: "Implement", position: { x: 0, y: 0 }, config: {} }]);
    const revision = workflow("revision", [{ id: "revise", type: "prompt", label: "Revise", position: { x: 0, y: 0 }, config: {} }]);
    render(<Providers catalog={[initial, revision]}><ReviewHarness initial={initial} revision={revision} /></Providers>);

    const initialTab = screen.getByRole("tab", { name: "Initial" });
    expect(initialTab).toHaveAttribute("aria-selected", "true");
    fireEvent.keyDown(initialTab, { key: "ArrowRight" });
    expect(screen.getByRole("tab", { name: "Revision" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tabpanel")).toHaveAttribute("aria-labelledby", expect.stringContaining("tab-revision"));
    expect(screen.getByText("Showing revision workflow revision workflow")).toBeVisible();
  });

  it("provides collapse and open-in-new-tab controls", () => {
    const child = workflow("child");
    const workflowNode = callNode("subworkflow", { workflow_id: "child", execution_mode: "shared" });
    const data: CompositeContainerData = {
      kind: "composite",
      instanceKey: "root::call",
      topLevelKey: "root::call",
      callNode: workflowNode,
      childWorkflow: child,
      branch: "subworkflow",
      depth: 0,
      breadcrumb: ["Parent"],
      empty: true,
      truncated: false,
      clamped: false,
    };
    render(<Providers catalog={[child]}><CompositePreviewNode {...compositeProps("call", data)} /></Providers>);

    expect(screen.getByRole("button", { name: "Collapse Quality checks" })).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("link", { name: "Open Quality checks workflow in a new tab" })).toHaveAttribute("target", "_blank");
    expect(screen.getByText("This workflow has no nodes.")).toBeVisible();
  });
});
