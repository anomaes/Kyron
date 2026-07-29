export const PREVIEW_NODE_WIDTH = 180;
export const PREVIEW_NODE_HEIGHT = 82;
export const EDITABLE_NODE_WIDTH = 205;
export const EDITABLE_NODE_HEIGHT = 140;
export const COMPOSITE_HEADER_HEIGHT = 104;
export const COMPOSITE_PADDING = 32;
export const COMPOSITE_MIN_WIDTH = 360;
export const COMPOSITE_MIN_HEIGHT = 220;
export const MAX_COMPOSITE_WIDTH = 2400;
export const MAX_COMPOSITE_HEIGHT = 1800;
export const SIBLING_CLEARANCE = 48;
export const MAX_COLLISION_PASSES = 1000;

export type Point = { x: number; y: number };
export type SizedItem = {
  id: string;
  position: Point;
  width: number;
  height: number;
};

export type NormalizedLayout = {
  positions: ReadonlyMap<string, Point>;
  width: number;
  height: number;
  clamped: boolean;
};

export function normalizeChildLayout(items: readonly SizedItem[]): NormalizedLayout {
  if (items.length === 0) {
    return {
      positions: new Map(),
      width: COMPOSITE_MIN_WIDTH,
      height: COMPOSITE_MIN_HEIGHT,
      clamped: false,
    };
  }

  const minimumX = Math.min(...items.map((item) => item.position.x));
  const minimumY = Math.min(...items.map((item) => item.position.y));
  const positions = new Map<string, Point>();
  let maximumRight = 0;
  let maximumBottom = 0;

  for (const item of items) {
    const position = {
      x: item.position.x - minimumX + COMPOSITE_PADDING,
      y: item.position.y - minimumY + COMPOSITE_HEADER_HEIGHT + COMPOSITE_PADDING,
    };
    positions.set(item.id, position);
    maximumRight = Math.max(maximumRight, position.x + item.width);
    maximumBottom = Math.max(maximumBottom, position.y + item.height);
  }

  const naturalWidth = Math.max(COMPOSITE_MIN_WIDTH, maximumRight + COMPOSITE_PADDING);
  const naturalHeight = Math.max(COMPOSITE_MIN_HEIGHT, maximumBottom + COMPOSITE_PADDING);
  return {
    positions,
    width: Math.min(MAX_COMPOSITE_WIDTH, naturalWidth),
    height: Math.min(MAX_COMPOSITE_HEIGHT, naturalHeight),
    clamped: naturalWidth > MAX_COMPOSITE_WIDTH || naturalHeight > MAX_COMPOSITE_HEIGHT,
  };
}

export type CollisionItem = SizedItem;
export type CollisionResult = {
  positions: ReadonlyMap<string, Point>;
  warning?: string;
  passes: number;
};

function overlapsWithClearance(a: SizedItem, b: SizedItem): boolean {
  return !(
    a.position.x + a.width + SIBLING_CLEARANCE <= b.position.x
    || b.position.x + b.width + SIBLING_CLEARANCE <= a.position.x
    || a.position.y + a.height + SIBLING_CLEARANCE <= b.position.y
    || b.position.y + b.height + SIBLING_CLEARANCE <= a.position.y
  );
}

function stableCollisionOrder(a: CollisionItem, b: CollisionItem): number {
  return a.position.y - b.position.y
    || a.position.x - b.position.x
    || a.id.localeCompare(b.id);
}

export function avoidTopLevelCollisions(
  items: readonly CollisionItem[],
  anchorId: string,
  maximumPasses = MAX_COLLISION_PASSES,
): CollisionResult {
  const anchor = items.find((item) => item.id === anchorId);
  if (!anchor) {
    return {
      positions: new Map(items.map((item) => [item.id, { ...item.position }])),
      warning: "Expanded preview anchor was not found",
      passes: 0,
    };
  }

  const placed: CollisionItem[] = [{ ...anchor, position: { ...anchor.position } }];
  const positions = new Map<string, Point>([[anchor.id, { ...anchor.position }]]);
  let passes = 0;

  for (const source of items.filter((item) => item.id !== anchorId).sort(stableCollisionOrder)) {
    const item: CollisionItem = { ...source, position: { ...source.position } };
    let collision = placed.find((candidate) => overlapsWithClearance(item, candidate));
    while (collision) {
      if (passes >= maximumPasses) {
        for (const remainder of items) {
          if (!positions.has(remainder.id)) positions.set(remainder.id, { ...remainder.position });
        }
        return {
          positions,
          warning: "Preview layout reached its collision safety limit",
          passes,
        };
      }
      passes += 1;
      const pushRight = collision.position.x + collision.width + SIBLING_CLEARANCE - item.position.x;
      const pushDown = collision.position.y + collision.height + SIBLING_CLEARANCE - item.position.y;
      if (pushRight <= pushDown) item.position.x += Math.max(0, pushRight);
      else item.position.y += Math.max(0, pushDown);
      collision = placed.find((candidate) => overlapsWithClearance(item, candidate));
    }
    positions.set(item.id, { ...item.position });
    placed.push(item);
  }

  return { positions, passes };
}
