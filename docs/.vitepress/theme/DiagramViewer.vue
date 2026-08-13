<template>
  <dialog
    ref="dialog"
    class="diagram-viewer"
    aria-labelledby="diagram-viewer-title"
    @click.self="close"
    @close="reset"
  >
    <header class="diagram-viewer__header">
      <div>
        <span class="diagram-viewer__eyebrow">Architecture diagram</span>
        <strong id="diagram-viewer-title">{{ title }}</strong>
      </div>
      <div class="diagram-viewer__controls" aria-label="Diagram zoom controls">
        <button type="button" title="Zoom out" aria-label="Zoom out" @click="zoomOut">
          −
        </button>
        <output aria-live="polite">{{ zoomPercent }}%</output>
        <button type="button" title="Zoom in" aria-label="Zoom in" @click="zoomIn">
          +
        </button>
        <button type="button" @click="fit">Fit</button>
        <button type="button" @click="actualSize">100%</button>
        <button type="button" class="diagram-viewer__close" @click="close">
          Close
        </button>
      </div>
    </header>

    <div
      ref="viewport"
      class="diagram-viewer__viewport"
      :class="{ 'is-dragging': dragging }"
      tabindex="0"
      aria-label="Scrollable diagram canvas"
      @pointerdown="startPan"
      @pointermove="pan"
      @pointerup="stopPan"
      @pointercancel="stopPan"
      @wheel.ctrl.prevent="zoomFromWheel"
    >
      <div class="diagram-viewer__stage">
        <div
          ref="canvas"
          class="diagram-viewer__canvas"
          :style="canvasStyle"
        />
      </div>
    </div>

    <footer class="diagram-viewer__hint">
      Use the zoom controls, then drag or scroll to inspect the diagram. Hold Ctrl and
      scroll to zoom.
    </footer>
  </dialog>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref } from "vue";

const dialog = ref<HTMLDialogElement>();
const viewport = ref<HTMLDivElement>();
const canvas = ref<HTMLDivElement>();
const title = ref("Diagram");
const sourceWidth = ref(1);
const sourceHeight = ref(1);
const zoom = ref(1);
const dragging = ref(false);

let observer: MutationObserver | undefined;
let enhancementFrame: number | undefined;
let dragStartX = 0;
let dragStartY = 0;
let dragScrollLeft = 0;
let dragScrollTop = 0;
let activeSvg: SVGSVGElement | undefined;
let sourceAnchor: Comment | undefined;

const zoomPercent = computed(() => Math.round(zoom.value * 100));
const canvasStyle = computed(() => ({
  width: `${Math.ceil(sourceWidth.value * zoom.value)}px`,
  height: `${Math.ceil(sourceHeight.value * zoom.value)}px`,
}));

function diagramTitle(container: HTMLElement): string {
  let sibling: Element | null = container.previousElementSibling;
  while (sibling) {
    if (/^H[1-3]$/.test(sibling.tagName)) {
      return sibling.textContent?.replace(/​/g, "").trim() || "Diagram";
    }
    sibling = sibling.previousElementSibling;
  }
  return document.querySelector(".vp-doc h1")?.textContent?.replace(/​/g, "").trim() || "Diagram";
}

async function openDiagram(container: HTMLElement): Promise<void> {
  const source = container.querySelector<SVGSVGElement>("svg");
  if (!source || !dialog.value || !canvas.value) return;

  const viewBox = source.viewBox.baseVal;
  sourceWidth.value = viewBox.width || source.getBoundingClientRect().width;
  sourceHeight.value = viewBox.height || source.getBoundingClientRect().height;
  title.value = diagramTitle(container);
  activeSvg = source;
  sourceAnchor = document.createComment("diagram-viewer-source");
  source.before(sourceAnchor);
  canvas.value.append(source);
  dialog.value.showModal();
  document.body.classList.add("diagram-viewer-open");
  await nextTick();
  fit();
  viewport.value?.focus();
}

function enhanceDiagrams(): void {
  document.querySelectorAll<HTMLElement>(".vp-doc .mermaid").forEach((container) => {
    if (!container.querySelector("svg") || container.querySelector(":scope > .diagram-expand")) {
      return;
    }
    const button = document.createElement("button");
    button.type = "button";
    button.className = "diagram-expand";
    button.textContent = "Expand diagram";
    button.setAttribute("aria-label", `Expand ${diagramTitle(container)}`);
    button.addEventListener("click", () => void openDiagram(container));
    container.prepend(button);
  });
}

function scheduleEnhancement(): void {
  if (enhancementFrame !== undefined) cancelAnimationFrame(enhancementFrame);
  enhancementFrame = requestAnimationFrame(() => {
    enhancementFrame = undefined;
    enhanceDiagrams();
  });
}

function fit(): void {
  if (!viewport.value) return;
  const horizontalRoom = Math.max(1, viewport.value.clientWidth - 48);
  const verticalRoom = Math.max(1, viewport.value.clientHeight - 48);
  zoom.value = Math.min(horizontalRoom / sourceWidth.value, verticalRoom / sourceHeight.value, 1);
  nextTick(() => {
    if (!viewport.value) return;
    viewport.value.scrollLeft = 0;
    viewport.value.scrollTop = 0;
  });
}

function setZoom(nextZoom: number): void {
  zoom.value = Math.min(4, Math.max(0.1, nextZoom));
}

function zoomIn(): void {
  setZoom(zoom.value * 1.25);
}

function zoomOut(): void {
  setZoom(zoom.value / 1.25);
}

function actualSize(): void {
  setZoom(1);
}

function zoomFromWheel(event: WheelEvent): void {
  setZoom(event.deltaY < 0 ? zoom.value * 1.1 : zoom.value / 1.1);
}

function startPan(event: PointerEvent): void {
  if (event.button !== 0 || !viewport.value) return;
  dragging.value = true;
  dragStartX = event.clientX;
  dragStartY = event.clientY;
  dragScrollLeft = viewport.value.scrollLeft;
  dragScrollTop = viewport.value.scrollTop;
  viewport.value.setPointerCapture(event.pointerId);
}

function pan(event: PointerEvent): void {
  if (!dragging.value || !viewport.value) return;
  viewport.value.scrollLeft = dragScrollLeft - (event.clientX - dragStartX);
  viewport.value.scrollTop = dragScrollTop - (event.clientY - dragStartY);
}

function stopPan(event: PointerEvent): void {
  dragging.value = false;
  if (viewport.value?.hasPointerCapture(event.pointerId)) {
    viewport.value.releasePointerCapture(event.pointerId);
  }
}

function close(): void {
  dialog.value?.close();
}

function reset(): void {
  document.body.classList.remove("diagram-viewer-open");
  if (activeSvg && sourceAnchor?.parentNode) {
    sourceAnchor.replaceWith(activeSvg);
  }
  activeSvg = undefined;
  sourceAnchor = undefined;
  dragging.value = false;
}

onMounted(() => {
  observer = new MutationObserver(scheduleEnhancement);
  observer.observe(document.body, { childList: true, subtree: true });
  scheduleEnhancement();
});

onUnmounted(() => {
  observer?.disconnect();
  if (enhancementFrame !== undefined) cancelAnimationFrame(enhancementFrame);
  document.body.classList.remove("diagram-viewer-open");
  if (activeSvg && sourceAnchor?.parentNode) {
    sourceAnchor.replaceWith(activeSvg);
  }
});
</script>
