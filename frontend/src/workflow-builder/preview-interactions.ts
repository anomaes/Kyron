import type { NodeChange } from "@xyflow/react";
import type { BuilderDisplayNode } from "./projection";
import type { Point } from "./preview-layout";

export type TransientPositions = ReadonlyMap<string, Point>;

export function applyTransientPositionChanges(
  current: TransientPositions,
  changes: readonly NodeChange<BuilderDisplayNode>[],
  movableNodeIds: ReadonlySet<string>,
): TransientPositions {
  let next: Map<string, Point> | null = null;
  for (const change of changes) {
    if (
      change.type !== "position"
      || !change.position
      || !movableNodeIds.has(change.id)
    ) continue;
    next ??= new Map(current);
    next.set(change.id, { ...change.position });
  }
  return next ?? current;
}

export function applyTransientPositions(
  nodes: readonly BuilderDisplayNode[],
  positions: TransientPositions,
): BuilderDisplayNode[] {
  if (positions.size === 0) return [...nodes];
  return nodes.map((node) => {
    const position = positions.get(node.id);
    return position ? { ...node, position: { ...position } } : node;
  });
}

