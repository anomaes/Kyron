import { MarkerType, type Edge, type Node } from "@xyflow/react";
import type { Workflow, WorkflowNode } from "../types";
import type { BuilderData, BuilderNode } from "./store";
import {
  COMPOSITE_PADDING,
  EDITABLE_NODE_HEIGHT,
  EDITABLE_NODE_WIDTH,
  MAX_COMPOSITE_HEIGHT,
  MAX_COMPOSITE_WIDTH,
  PREVIEW_NODE_HEIGHT,
  PREVIEW_NODE_WIDTH,
  avoidTopLevelCollisions,
  normalizeChildLayout,
  type Point,
  type SizedItem,
} from "./preview-layout";

export const MAX_VISIBLE_PREVIEW_DEPTH = 8;
export const MAX_VISIBLE_PREVIEW_NODES = 250;
export const PREVIEW_ID_PREFIX = "preview/";

export type CatalogStatus = "loading" | "ready" | "error";
export type ReviewBranch = "initial" | "revision";
export type CompositeBranch = "subworkflow" | ReviewBranch;

export type CompositeContainerData = {
  kind: "composite";
  instanceKey: string;
  topLevelKey: string;
  callNode: WorkflowNode;
  childWorkflow: Workflow | null;
  branch: CompositeBranch;
  depth: number;
  breadcrumb: string[];
  warning?: string;
  empty: boolean;
  truncated: boolean;
  clamped: boolean;
};

export type PreviewNodeData = {
  kind: "preview";
  instanceKey: string;
  topLevelKey: string;
  workflowNode: WorkflowNode;
  workflowId: string;
  workflowName: string;
  depth: number;
  breadcrumb: string[];
};

export type BuilderDisplayData = BuilderData | CompositeContainerData | PreviewNodeData;
export type BuilderDisplayNode = Node<BuilderDisplayData>;

export type ExpansionSnapshot = {
  activeTopLevelKey: string | null;
  expandedKeys: ReadonlySet<string>;
  reviewTabs: ReadonlyMap<string, ReviewBranch>;
  referenceByKey: ReadonlyMap<string, string>;
};

export type ProjectionWarning = {
  instanceKey?: string;
  message: string;
};

export type BuilderProjectionInput = {
  rootWorkflow: Workflow;
  editableNodes: readonly BuilderNode[];
  editableEdges: readonly Edge[];
  catalogById: ReadonlyMap<string, Workflow>;
  catalogStatus: CatalogStatus;
  expansion: ExpansionSnapshot;
};

export type BuilderProjection = {
  nodes: BuilderDisplayNode[];
  edges: Edge[];
  realNodeIds: ReadonlySet<string>;
  previewNodeIds: ReadonlySet<string>;
  hasExpandedPreview: boolean;
  activeTopLevelNodeId: string | null;
  warnings: ProjectionWarning[];
};

type CompositeBuild = {
  root: BuilderDisplayNode;
  descendants: BuilderDisplayNode[];
  edges: Edge[];
  width: number;
  height: number;
};

type ProjectionContext = {
  input: BuilderProjectionInput;
  warnings: ProjectionWarning[];
  previewNodeIds: Set<string>;
  admittedNodes: number;
};

function compositeReference(node: WorkflowNode, expansion: ExpansionSnapshot, instanceKey: string): {
  branch: CompositeBranch;
  workflowId: string;
} {
  if (node.type === "subworkflow") {
    return { branch: "subworkflow", workflowId: String(node.config.workflow_id ?? "") };
  }
  const branch = expansion.reviewTabs.get(instanceKey) ?? "initial";
  return {
    branch,
    workflowId: String(node.config[branch === "initial" ? "initial_workflow_id" : "revision_workflow_id"] ?? ""),
  };
}

export function topLevelInstanceKey(nodeId: string): string {
  return `root::${nodeId}`;
}

export function nestedInstanceKey(parentInstanceKey: string, workflowId: string, nodeId: string): string {
  return `${parentInstanceKey}::${workflowId}::${nodeId}`;
}

export function previewNodeId(instanceKey: string, nodeId: string): string {
  return `${PREVIEW_ID_PREFIX}${instanceKey}/node::${nodeId}`;
}

export function previewEdgeId(instanceKey: string, edgeId: string): string {
  return `${PREVIEW_ID_PREFIX}${instanceKey}/edge::${edgeId}`;
}

function warningForReference(
  status: CatalogStatus,
  workflowId: string,
  child: Workflow | undefined,
): string | undefined {
  if (!workflowId) return "Referenced workflow is not configured";
  if (status === "loading") return child ? undefined : "Loading preview";
  if (status === "error") return child ? undefined : "Preview unavailable";
  if (!child) return "Referenced workflow not found";
  return undefined;
}

function displayIdForComposite(instanceKey: string, rootId?: string): string {
  return rootId ?? `${PREVIEW_ID_PREFIX}${instanceKey}/composite`;
}

function expansionMatchesReference(
  expansion: ExpansionSnapshot,
  instanceKey: string,
  node: WorkflowNode,
): boolean {
  const storedReference = expansion.referenceByKey.get(instanceKey);
  if (storedReference === undefined) return true;
  return storedReference === compositeReference(node, expansion, instanceKey).workflowId;
}

function buildComposite(
  context: ProjectionContext,
  callNode: WorkflowNode,
  instanceKey: string,
  topLevelKey: string,
  position: Point,
  depth: number,
  ancestorWorkflowIds: readonly string[],
  breadcrumb: readonly string[],
  parentId?: string,
  rootId?: string,
): CompositeBuild {
  const { branch, workflowId } = compositeReference(callNode, context.input.expansion, instanceKey);
  const child = context.input.catalogById.get(workflowId);
  let warning = warningForReference(context.input.catalogStatus, workflowId, child);
  if (!warning && workflowId && ancestorWorkflowIds.includes(workflowId)) {
    warning = "Recursive reference cannot be previewed";
  }
  if (!warning && depth >= MAX_VISIBLE_PREVIEW_DEPTH) {
    warning = "Preview depth limit reached";
  }

  const displayId = displayIdForComposite(instanceKey, rootId);
  if (!rootId) context.previewNodeIds.add(displayId);
  const childBuilds: Array<{
    source: WorkflowNode;
    root: BuilderDisplayNode;
    descendants: BuilderDisplayNode[];
    edges: Edge[];
    width: number;
    height: number;
  }> = [];
  const directIds = new Map<string, string>();
  let truncated = false;

  if (!warning && child) {
    for (const source of child.nodes) {
      if (context.admittedNodes >= MAX_VISIBLE_PREVIEW_NODES) {
        truncated = true;
        break;
      }
      context.admittedNodes += 1;
      const childInstanceKey = nestedInstanceKey(instanceKey, child.id, source.id);
      const childDisplayId = previewNodeId(instanceKey, source.id);
      directIds.set(source.id, childDisplayId);
      context.previewNodeIds.add(childDisplayId);

      if (
        (source.type === "subworkflow" || source.type === "review_loop")
        && context.input.expansion.expandedKeys.has(childInstanceKey)
        && expansionMatchesReference(context.input.expansion, childInstanceKey, source)
      ) {
        const nested = buildComposite(
          context,
          source,
          childInstanceKey,
          topLevelKey,
          source.position,
          depth + 1,
          [...ancestorWorkflowIds, child.id],
          [...breadcrumb, child.name],
          displayId,
          childDisplayId,
        );
        childBuilds.push({ source, ...nested });
      } else {
        const data: PreviewNodeData = {
          kind: "preview",
          instanceKey: childInstanceKey,
          topLevelKey,
          workflowNode: source,
          workflowId: child.id,
          workflowName: child.name,
          depth: depth + 1,
          breadcrumb: [...breadcrumb, child.name],
        };
        const root: BuilderDisplayNode = {
          id: childDisplayId,
          type: "workflowPreview",
          parentId: displayId,
          position: { ...source.position },
          draggable: false,
          connectable: false,
          selectable: false,
          style: { width: PREVIEW_NODE_WIDTH, height: PREVIEW_NODE_HEIGHT },
          data,
          ariaLabel: `${child.name}, ${source.type.replaceAll("_", " ")}, ${source.label}, read-only preview`,
        };
        childBuilds.push({
          source,
          root,
          descendants: [],
          edges: [],
          width: PREVIEW_NODE_WIDTH,
          height: PREVIEW_NODE_HEIGHT,
        });
      }
    }
  }

  const sizedChildren: SizedItem[] = childBuilds.map((built) => ({
    id: built.root.id,
    position: built.source.position,
    width: built.width,
    height: built.height,
  }));
  const layout = normalizeChildLayout(sizedChildren);
  const descendants: BuilderDisplayNode[] = [];
  const edges: Edge[] = [];

  for (const built of childBuilds) {
    const childPosition = layout.positions.get(built.root.id) ?? built.root.position;
    if (
      layout.clamped
      && (
        childPosition.x + built.width + COMPOSITE_PADDING > layout.width
        || childPosition.y + built.height + COMPOSITE_PADDING > layout.height
      )
    ) {
      directIds.delete(built.source.id);
      context.previewNodeIds.delete(built.root.id);
      for (const descendant of built.descendants) context.previewNodeIds.delete(descendant.id);
      truncated = true;
      continue;
    }
    descendants.push({ ...built.root, position: childPosition });
    descendants.push(...built.descendants);
    edges.push(...built.edges);
  }

  if (child) {
    for (const edge of child.edges) {
      const source = directIds.get(edge.source);
      const target = directIds.get(edge.target);
      if (!source || !target) continue;
      edges.push({
        id: previewEdgeId(instanceKey, edge.id),
        source,
        target,
        type: "smoothstep",
        className: "preview-edge",
        markerEnd: { type: MarkerType.ArrowClosed },
        selectable: false,
        data: { condition: edge.condition, preview: true },
      });
    }
  }

  if (truncated) {
    warning = "Preview truncated";
    context.warnings.push({ instanceKey, message: warning });
  }
  if (layout.clamped) {
    context.warnings.push({ instanceKey, message: "Preview dimensions were limited" });
  }
  if (warning) context.warnings.push({ instanceKey, message: warning });

  const data: CompositeContainerData = {
    kind: "composite",
    instanceKey,
    topLevelKey,
    callNode,
    childWorkflow: child ?? null,
    branch,
    depth,
    breadcrumb: [...breadcrumb],
    warning,
    empty: Boolean(child && child.nodes.length === 0 && !warning),
    truncated,
    clamped: layout.clamped,
  };
  const root: BuilderDisplayNode = {
    id: displayId,
    type: "compositePreview",
    parentId,
    position: { ...position },
    draggable: false,
    connectable: false,
    selectable: parentId === undefined,
    style: { width: layout.width, height: layout.height },
    data,
    ariaLabel: `${callNode.type === "review_loop" ? "Review loop" : "Sub-workflow"} ${callNode.label}, expanded read-only preview`,
  };
  return {
    root,
    descendants,
    edges,
    width: layout.width,
    height: layout.height,
  };
}

function collapsedProjection(input: BuilderProjectionInput, warning?: ProjectionWarning): BuilderProjection {
  return {
    nodes: input.editableNodes.map((node) => ({ ...node, position: { ...node.position } })),
    edges: input.editableEdges.map((edge) => ({ ...edge })),
    realNodeIds: new Set(input.editableNodes.map((node) => node.id)),
    previewNodeIds: new Set(),
    hasExpandedPreview: false,
    activeTopLevelNodeId: null,
    warnings: warning ? [warning] : [],
  };
}

export function projectBuilderGraph(input: BuilderProjectionInput): BuilderProjection {
  const activeKey = input.expansion.activeTopLevelKey;
  if (!activeKey || !input.expansion.expandedKeys.has(activeKey)) return collapsedProjection(input);

  const activeNodeId = activeKey.startsWith("root::") ? activeKey.slice("root::".length) : "";
  const activeNode = input.editableNodes.find((node) => node.id === activeNodeId);
  if (!activeNode || !["subworkflow", "review_loop"].includes(activeNode.data.type)) {
    return collapsedProjection(input);
  }
  if (!expansionMatchesReference(input.expansion, activeKey, activeNode.data.workflowNode)) {
    return collapsedProjection(input);
  }

  const context: ProjectionContext = {
    input,
    warnings: [],
    previewNodeIds: new Set(),
    admittedNodes: 0,
  };
  const composite = buildComposite(
    context,
    activeNode.data.workflowNode,
    activeKey,
    activeKey,
    activeNode.position,
    0,
    [input.rootWorkflow.id],
    [input.rootWorkflow.name],
    undefined,
    activeNode.id,
  );

  const collisionItems: SizedItem[] = input.editableNodes.map((node) => ({
    id: node.id,
    position: node.position,
    width: node.id === activeNode.id ? composite.width : EDITABLE_NODE_WIDTH,
    height: node.id === activeNode.id ? composite.height : EDITABLE_NODE_HEIGHT,
  }));
  const collisions = avoidTopLevelCollisions(collisionItems, activeNode.id);
  if (collisions.warning) context.warnings.push({ message: collisions.warning });

  const roots: BuilderDisplayNode[] = input.editableNodes.map((node) => {
    const position = collisions.positions.get(node.id) ?? node.position;
    if (node.id === activeNode.id) return { ...composite.root, position, selected: node.selected };
    return { ...node, position: { ...position }, draggable: false, connectable: false };
  });

  return {
    nodes: [...roots, ...composite.descendants],
    edges: [...input.editableEdges.map((edge) => ({ ...edge })), ...composite.edges],
    realNodeIds: new Set(input.editableNodes.map((node) => node.id)),
    previewNodeIds: context.previewNodeIds,
    hasExpandedPreview: true,
    activeTopLevelNodeId: activeNode.id,
    warnings: context.warnings,
  };
}

export function safeProjectBuilderGraph(input: BuilderProjectionInput): BuilderProjection {
  try {
    return projectBuilderGraph(input);
  } catch (error) {
    if ((import.meta as ImportMeta & { env?: { DEV?: boolean } }).env?.DEV) {
      const details = error instanceof Error ? `${error.name}: ${error.message}` : "Unknown projection error";
      console.error("Workflow child preview projection failed", {
        workflowId: input.rootWorkflow.id,
        rootNodeCount: input.editableNodes.length,
        catalogSize: input.catalogById.size,
        error: details,
      });
    }
    return collapsedProjection(input, { message: "Child preview could not be rendered" });
  }
}

export function editableData(node: WorkflowNode): BuilderData {
  return { kind: "editable", workflowNode: node, label: node.label, type: node.type };
}

export function isEditableDisplayNode(node: BuilderDisplayNode): node is Node<BuilderData> {
  return node.data.kind === "editable";
}

export const projectionLimits = {
  maximumDepth: MAX_VISIBLE_PREVIEW_DEPTH,
  maximumNodes: MAX_VISIBLE_PREVIEW_NODES,
  maximumWidth: MAX_COMPOSITE_WIDTH,
  maximumHeight: MAX_COMPOSITE_HEIGHT,
} as const;
