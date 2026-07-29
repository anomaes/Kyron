import "@testing-library/jest-dom/vitest";

Object.defineProperty(window, "matchMedia", {
  writable: true,
  value: (query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: () => undefined,
    removeListener: () => undefined,
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
    dispatchEvent: () => false,
  }),
});

if (!globalThis.CSS) Object.defineProperty(globalThis, "CSS", { value: {} });
if (!globalThis.CSS.escape) {
  Object.defineProperty(globalThis.CSS, "escape", {
    value: (value: string) => value.replace(/["\\]/g, "\\$&"),
  });
}
