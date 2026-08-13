import { Fragment, h } from "vue";
import type { Theme } from "vitepress";
import DefaultTheme from "vitepress/theme";
import DiagramViewer from "./DiagramViewer.vue";
import "./custom.css";

export default {
  extends: DefaultTheme,
  Layout: () => h(Fragment, [h(DefaultTheme.Layout), h(DiagramViewer)]),
} satisfies Theme;
