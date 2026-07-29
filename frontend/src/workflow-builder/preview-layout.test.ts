import { describe, expect, it } from "vitest";
import {
  COMPOSITE_HEADER_HEIGHT,
  COMPOSITE_MIN_HEIGHT,
  COMPOSITE_MIN_WIDTH,
  COMPOSITE_PADDING,
  MAX_COMPOSITE_HEIGHT,
  MAX_COMPOSITE_WIDTH,
  SIBLING_CLEARANCE,
  avoidTopLevelCollisions,
  normalizeChildLayout,
  type SizedItem,
} from "./preview-layout";

function overlaps(a: SizedItem, b: SizedItem): boolean {
  return !(
    a.position.x + a.width + SIBLING_CLEARANCE <= b.position.x
    || b.position.x + b.width + SIBLING_CLEARANCE <= a.position.x
    || a.position.y + a.height + SIBLING_CLEARANCE <= b.position.y
    || b.position.y + b.height + SIBLING_CLEARANCE <= a.position.y
  );
}

describe("normalizeChildLayout", () => {
  it("uses stable minimum dimensions for an empty graph", () => {
    expect(normalizeChildLayout([])).toEqual({
      positions: new Map(),
      width: COMPOSITE_MIN_WIDTH,
      height: COMPOSITE_MIN_HEIGHT,
      clamped: false,
    });
  });

  it("normalizes negative and sparse positions", () => {
    const result = normalizeChildLayout([
      { id: "a", position: { x: -800, y: -500 }, width: 180, height: 82 },
      { id: "b", position: { x: 200, y: 300 }, width: 180, height: 82 },
    ]);

    expect(result.positions.get("a")).toEqual({
      x: COMPOSITE_PADDING,
      y: COMPOSITE_HEADER_HEIGHT + COMPOSITE_PADDING,
    });
    expect(result.positions.get("b")).toEqual({
      x: 1000 + COMPOSITE_PADDING,
      y: 800 + COMPOSITE_HEADER_HEIGHT + COMPOSITE_PADDING,
    });
  });

  it("clamps adversarial bounds", () => {
    const result = normalizeChildLayout([
      { id: "a", position: { x: 0, y: 0 }, width: 180, height: 82 },
      { id: "b", position: { x: 10_000, y: 10_000 }, width: 180, height: 82 },
    ]);

    expect(result.width).toBe(MAX_COMPOSITE_WIDTH);
    expect(result.height).toBe(MAX_COMPOSITE_HEIGHT);
    expect(result.clamped).toBe(true);
  });
});

describe("avoidTopLevelCollisions", () => {
  const source: SizedItem[] = [
    { id: "expanded", position: { x: 100, y: 100 }, width: 500, height: 400 },
    { id: "one", position: { x: 300, y: 150 }, width: 205, height: 140 },
    { id: "two", position: { x: 360, y: 190 }, width: 205, height: 140 },
  ];

  it("preserves the anchor and resolves cascaded collisions without mutation", () => {
    const before = structuredClone(source);
    const result = avoidTopLevelCollisions(source, "expanded");
    const placed = source.map((item) => ({ ...item, position: result.positions.get(item.id) ?? item.position }));

    expect(result.warning).toBeUndefined();
    expect(result.positions.get("expanded")).toEqual({ x: 100, y: 100 });
    expect(placed[1] && placed[0] && overlaps(placed[1], placed[0])).toBe(false);
    expect(placed[2] && placed[0] && overlaps(placed[2], placed[0])).toBe(false);
    expect(placed[2] && placed[1] && overlaps(placed[2], placed[1])).toBe(false);
    expect(source).toEqual(before);
    for (const item of source) {
      const position = result.positions.get(item.id);
      expect(position?.x).toBeGreaterThanOrEqual(item.position.x);
      expect(position?.y).toBeGreaterThanOrEqual(item.position.y);
    }
  });

  it("is deterministic regardless of input order", () => {
    const forward = avoidTopLevelCollisions(source, "expanded");
    const reverse = avoidTopLevelCollisions([...source].reverse(), "expanded");

    expect([...forward.positions]).toEqual([...reverse.positions]);
  });

  it("terminates with a warning at the configured pass bound", () => {
    const result = avoidTopLevelCollisions(source, "expanded", 0);

    expect(result.warning).toBe("Preview layout reached its collision safety limit");
    expect(result.passes).toBe(0);
  });
});

