import { defineComponent, h, onMounted, onUnmounted } from "vue";
import type { Theme } from "vitepress";
import DefaultTheme from "vitepress/theme";
import "./custom.css";

function sizeMermaidDiagrams(root: ParentNode): void {
  root.querySelectorAll<SVGSVGElement>(".vp-doc .mermaid svg").forEach((svg) => {
    const width = svg.viewBox.baseVal.width;
    if (Number.isFinite(width) && width > 0) {
      // Mermaid emits width="100%", which scales a large viewBox down until its
      // nominal 16px labels become unreadable. A one-user-unit-to-one-CSS-pixel
      // canvas preserves the intended text size; the parent owns horizontal scroll.
      svg.style.setProperty("width", `${Math.ceil(width)}px`, "important");
    }
  });
}

const MermaidAwareLayout = defineComponent({
  name: "MermaidAwareLayout",
  setup() {
    let observer: MutationObserver | undefined;
    let frame: number | undefined;

    const scheduleSizing = (): void => {
      if (frame !== undefined) {
        cancelAnimationFrame(frame);
      }
      frame = requestAnimationFrame(() => {
        frame = undefined;
        sizeMermaidDiagrams(document);
      });
    };

    onMounted(() => {
      observer = new MutationObserver(scheduleSizing);
      observer.observe(document.body, { childList: true, subtree: true });
      scheduleSizing();
    });

    onUnmounted(() => {
      observer?.disconnect();
      if (frame !== undefined) {
        cancelAnimationFrame(frame);
      }
    });

    return () => h(DefaultTheme.Layout);
  },
});

export default {
  extends: DefaultTheme,
  Layout: MermaidAwareLayout,
} satisfies Theme;
