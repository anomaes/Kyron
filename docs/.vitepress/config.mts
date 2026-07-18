import { defineConfig } from "vitepress";

const base = process.env.DOCS_BASE || "/";
const hostname = process.env.DOCS_HOSTNAME || "https://anomaes.github.io/Kyron/";

export default defineConfig({
  base,
  lang: "en-US",
  title: "Kyron",
  description:
    "Documentation for Kyron, the deterministic workflow engine for AI-assisted software delivery.",
  cleanUrls: true,
  lastUpdated: true,
  sitemap: {
    hostname,
  },
  head: [
    ["meta", { name: "theme-color", content: "#11120f" }],
    ["meta", { property: "og:type", content: "website" }],
    ["meta", { property: "og:site_name", content: "Kyron documentation" }],
    [
      "meta",
      {
        property: "og:image",
        content: "https://raw.githubusercontent.com/anomaes/Kyron/main/docs/public/og.png",
      },
    ],
    ["meta", { name: "twitter:card", content: "summary_large_image" }],
    [
      "meta",
      {
        name: "twitter:image",
        content: "https://raw.githubusercontent.com/anomaes/Kyron/main/docs/public/og.png",
      },
    ],
  ],
  markdown: {
    lineNumbers: true,
  },
  themeConfig: {
    siteTitle: "Kyron docs",
    search: {
      provider: "local",
      options: {
        detailedView: true,
      },
    },
    nav: [
      { text: "Start", link: "/getting-started/" },
      { text: "Workflows", link: "/workflows/" },
      { text: "Deploy", link: "/deployment/" },
      { text: "Reference", link: "/reference/" },
      {
        text: "v0.1",
        items: [
          { text: "Implementation status", link: "/IMPLEMENTATION_PLAN" },
          { text: "Acceptance record", link: "/acceptance" },
        ],
      },
    ],
    sidebar: {
      "/getting-started/": [
        {
          text: "Start here",
          items: [
            { text: "Welcome to Kyron", link: "/getting-started/" },
            { text: "Quick start", link: "/getting-started/quick-start" },
            { text: "Core concepts", link: "/getting-started/concepts" },
            { text: "Your first workflow", link: "/getting-started/first-workflow" },
          ],
        },
      ],
      "/guides/": [
        {
          text: "Use Kyron",
          items: [
            { text: "Projects and credentials", link: "/guides/projects-and-credentials" },
            { text: "Visual workflow builder", link: "/guides/workflow-builder" },
            { text: "Run workflows", link: "/guides/running-workflows" },
            { text: "Reviews and feedback", link: "/guides/review-and-feedback" },
            { text: "Failure and recovery", link: "/guides/recovery" },
          ],
        },
      ],
      "/workflows/": [
        {
          text: "Workflow authoring",
          items: [
            { text: "Overview", link: "/workflows/" },
            { text: "Node types", link: "/workflows/node-types" },
            { text: "Edges, conditions, and joins", link: "/workflows/edges-and-joins" },
            { text: "Composition", link: "/workflows/composition" },
            { text: "Review loops", link: "/workflows/review-loops" },
            { text: "Example library", link: "/workflows/examples" },
          ],
        },
        {
          text: "Complete contract",
          items: [
            { text: "Workflow JSON specification", link: "/workflow-json-authoring-spec" },
          ],
        },
      ],
      "/deployment/": [
        {
          text: "Deploy and operate",
          items: [
            { text: "Production deployment", link: "/deployment/" },
            { text: "Configuration", link: "/deployment/configuration" },
            { text: "GitLab and GitHub", link: "/deployment/providers" },
            { text: "Security model", link: "/deployment/security" },
            { text: "Troubleshooting", link: "/deployment/troubleshooting" },
            { text: "Operations runbook", link: "/operations" },
          ],
        },
      ],
      "/reference/": [
        {
          text: "Reference",
          items: [
            { text: "Reference index", link: "/reference/" },
            { text: "Variables and outputs", link: "/reference/variables" },
            { text: "Run states", link: "/reference/states" },
            { text: "HTTP and WebSocket API", link: "/api" },
            { text: "Architecture", link: "/architecture" },
            { text: "Provider contract", link: "/code-host-provider-spec" },
            { text: "Decision log", link: "/decisions" },
          ],
        },
      ],
      "/contributing/": [
        {
          text: "Contribute",
          items: [
            { text: "Developer guide", link: "/contributing/" },
            { text: "Implementation plan", link: "/IMPLEMENTATION_PLAN" },
            { text: "Acceptance verification", link: "/acceptance" },
          ],
        },
      ],
    },
    socialLinks: [
      { icon: "github", link: "https://github.com/anomaes/Kyron" },
    ],
    editLink: {
      pattern: "https://github.com/anomaes/Kyron/edit/main/docs/:path",
      text: "Edit this page on GitHub",
    },
    outline: {
      level: [2, 3],
      label: "On this page",
    },
    docFooter: {
      prev: "Previous",
      next: "Next",
    },
    footer: {
      message: "Source available under the PolyForm Noncommercial License 1.0.0.",
      copyright: "Copyright © 2026 Noah Mäschli",
    },
  },
});
