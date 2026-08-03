# Workflow builder nested composite expansion

Status: implementation specification  
Target: Kyron workflow builder  
Audience: implementation agent and reviewer  
Last updated: 2026-07-29

## 1. Purpose and authority

This document specifies a safe, polished way to expand `subworkflow` and
`review_loop` nodes inside Kyron's visual workflow builder so an author can inspect
the referenced child graphs without leaving the parent workflow.

This is an implementation specification, not a change to workflow execution
semantics. `workflow_orchestration_engine_spec.md` remains normative. In particular:

- a `subworkflow` or `review_loop` remains one control node in its parent DAG;
- child definitions remain separate workflow definitions;
- ordinary workflow graphs remain acyclic;
- cross-workflow recursion and maximum depth remain server-validated;
- snapshots and runs continue to resolve definitions from their exact revisions; and
- no visualization state is persisted in workflow definitions, snapshots, or run state.

If this document conflicts with `workflow_orchestration_engine_spec.md`, the normative
specification wins. The implementation must not modify backend execution, snapshot,
validation, mapping, Git, gate, or recovery behavior to deliver this feature.

## 2. Executive decision

Implement nested, read-only composite previews in the workflow builder.

An expanded composite is a container whose external edges remain attached to the
original parent control node. The container renders the selected referenced
workflow's nodes and edges inside it. Child nodes are previews only and cannot be
moved, connected, deleted, configured, or serialized from the parent builder.

The initial delivery intentionally makes these safety tradeoffs:

1. Only one top-level composite branch may be expanded at a time.
2. Nested composites along that branch may also be expanded.
3. A `review_loop` renders one child definition at a time using accessible
   **Initial** and **Revision** tabs.
4. While any composite preview is expanded, real top-level parent nodes remain
   draggable through transient display positions, while child preview dragging and
   connection creation are disabled. Node selection, inspector editing of real parent
   nodes, panning, zooming, collapsing, tab selection, and navigation to child
   workflows remain available.
5. Collision avoidance changes display positions only. It never writes temporary
   positions to the builder store or workflow definition.
6. Child definitions are edited only by opening their own workflow builder route.

These constraints preserve the main value of nested visualization while avoiding
multi-definition editing, ambiguous save behavior, and accidental parent graph
mutation.

## 3. Current implementation context

The implementation agent must inspect the current versions of these files before
editing:

- `frontend/src/pages/WorkflowBuilderPage.tsx`
- `frontend/src/workflow-builder/store.ts`
- `frontend/src/workflow-builder/WorkflowCard.tsx`
- `frontend/src/workflow-builder/CompositeNodeConfig.tsx`
- `frontend/src/pages/RunDetailPage.tsx`
- `frontend/src/types/index.ts`
- `frontend/src/styles.css`
- `backend/api/workflow_routes.py`
- `docs/guides/workflow-builder.md`

At the time this specification was written:

- the builder fetches the complete workflow catalog from
  `GET /api/projects/{project_id}/workflows`;
- each catalog item already contains its complete definition, including nodes and
  edges;
- a subworkflow references a child through `config.workflow_id`;
- a review loop references children through `config.initial_workflow_id` and
  `config.revision_workflow_id`;
- React Flow receives the editable Zustand store's nodes and edges directly;
- `store.serialize()` serializes only the store's real workflow nodes and edges; and
- run detail independently builds an expanded execution graph from immutable run
  snapshots and invocation rows.

No new backend endpoint or persisted field is expected. If the catalog response no
longer includes complete definitions, stop and reassess instead of silently adding
partial or revision-ambiguous fetching.

## 4. Goals

The completed feature must:

- let an author expand and collapse a subworkflow from its builder card;
- render the referenced child's nodes and internal edges inside a visually distinct
  container;
- allow nested subworkflow and review-loop previews;
- render review-loop initial and revision definitions without suggesting that they
  execute side by side;
- preserve the parent control node's identity, handles, mappings, join, and external
  edges;
- avoid overlap between the expanded top-level container and other top-level nodes
  using deterministic temporary display layout;
- restore the exact pre-expansion graph positions when collapsed;
- provide keyboard-operable controls, meaningful accessible names, focus behavior,
  and non-color-only state indications;
- handle missing, invalid, recursive, deep, empty, and unusually large child
  definitions gracefully;
- remain responsive for normal project catalogs and graphs;
- add automated tests for projection, nesting, layout, interaction, accessibility,
  and serialization isolation; and
- leave run-detail visualization and backend behavior unchanged.

## 5. Non-goals

Do not implement any of the following as part of this change:

- editing a child workflow's nodes or edges inside its parent;
- saving more than one workflow definition from the parent builder;
- flattening child nodes into the parent workflow definition;
- connecting a parent edge directly to a child entry or exit node;
- deriving new workflow execution semantics from visual entry or exit nodes;
- persisting expansion, active tabs, viewport, generated node IDs, container size,
  or collision offsets;
- changing the workflow YAML/JSON schema;
- changing workflow validation or snapshot resolution;
- changing run-detail expansion, invocation history, or statuses;
- adding arbitrary cycles;
- adding a general-purpose automatic layout command for authored workflow positions;
- rendering all review-loop iterations in the builder (iterations exist only at run
  time); or
- introducing a new frontend end-to-end test platform solely for this feature.

## 6. Product semantics

### 6.1 Collapsed subworkflow

The existing card remains recognizable and retains its current label, join indicator,
workflow ID preview, target handle, and source handle. Add:

- a button named `Expand <child workflow name>` when the reference resolves;
- a disabled or unavailable expansion affordance when the reference is blank or
  missing; and
- a visible warning such as `Referenced workflow not found` for a missing reference.

The button must be an actual `<button type="button">`, not a clickable `<div>`.
It must carry React Flow's `nodrag` and `nopan` classes and stop pointer/click
propagation so toggling expansion does not select or drag the node accidentally.

### 6.2 Expanded subworkflow

The original subworkflow call becomes a composite container:

```text
┌ Sub-workflow · Quality checks        [Open workflow] [Collapse] ┐
│ shared · 3 nodes                                             │
│                                                             │
│    ┌ Lint ┐ ─────▶ ┌ Test ┐ ─────▶ ┌ Analyze ┐               │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

Required behavior:

- the container keeps the original call node's React Flow ID;
- all parent incoming and outgoing edges remain attached to the container;
- the target and source handles remain on the container boundary;
- the header shows control type, call label, resolved child name, child ID,
  execution mode where relevant, and node count;
- internal preview nodes use the child's stored relative positions after
  normalization into the container;
- internal edges use the child's stored topology;
- internal preview nodes are visibly read-only;
- the header provides **Open workflow** and **Collapse** controls;
- **Open workflow** navigates to
  `/projects/{projectId}/workflows/{workflowId}/edit`;
- opening a workflow with unsaved parent changes must use a new browser tab so the
  parent editor state is not discarded; and
- selecting the expanded container still selects the real parent node and opens its
  existing inspector configuration.

The visualization must not draw synthetic edges between the container handle and
the child's start or terminal nodes. Such edges could incorrectly imply data or
scheduling semantics. The container boundary itself represents invocation.

### 6.3 Nested composites

If a previewed child contains a `subworkflow` or `review_loop`, its preview card has
the same expansion affordance. Nested expansion grows the containing composite and
all of its ancestors.

Expansion identity is per call site, not per workflow definition. If workflow
`checks` is invoked from two different nodes, those are distinct visual instances.
Use an instance path assembled from namespaced call-node IDs, for example:

```text
root::quality
root::quality::checks::security_scan
```

Do not key expansion state only by workflow ID.

Only one top-level branch may be expanded. Expanding a second top-level composite
collapses the first branch and all of its descendants. Within the active branch,
multiple nested composites may be open if they do not exceed the safety budgets in
section 12.

### 6.4 Review-loop expansion

A review-loop container represents the control node, not run-time iterations.

Its header shows:

- `Review loop`;
- the call label;
- approval policy;
- maximum iterations; and
- active child identity.

Its body contains an accessible tablist:

- **Initial** renders `config.initial_workflow_id`;
- **Revision** renders `config.revision_workflow_id`.

Rules:

- only the active tab's child graph is mounted into React Flow;
- tabs use the WAI-ARIA tabs pattern (`tablist`, `tab`, `tabpanel`);
- Left/Right Arrow changes focused tab, Home/End selects first/last, and Enter or
  Space activates when activation is not automatic;
- changing tabs collapses nested expansion state below the previously active branch;
- if revision workflow ID is absent, show a disabled **Revision** tab with the
  explanation `No separate revision workflow`; and
- if Kyron's semantics use the initial workflow as the revision fallback, show that
  fact in text, but do not invent a reference not present in configuration. Follow
  the current backend schema and `CompositeNodeConfig` behavior.

Do not render iteration counts, feedback, statuses, or invocation cards in the
builder. Those belong to run detail.

### 6.5 Empty and missing definitions

An existing child with zero nodes renders a stable empty state:

```text
This workflow has no nodes.
```

A blank or missing reference renders a warning state inside the composite card and
does not throw. It offers no **Open workflow** link if no valid target exists.

Catalog loading and query errors must not crash existing workflow editing. Before
the catalog resolves, show the normal collapsed card with a small `Loading preview`
state if the user requests expansion. If loading fails, show `Preview unavailable`
and preserve all existing builder functions.

## 7. State ownership and serialization safety

This section is non-negotiable.

### 7.1 Real authoring state

The existing Zustand builder store remains the only source of serialized parent
workflow nodes, edges, and positions.

Do not insert preview nodes or preview edges into:

- `store.nodes`;
- `store.edges`;
- `store.workflow`;
- node templates;
- validation requests;
- save requests; or
- `store.serialize()` output.

### 7.2 Transient preview state

Keep preview state outside persisted workflow data. A dedicated React context and
hook under `frontend/src/workflow-builder/` is preferred. It should own:

- the active top-level expansion instance key, or `null`;
- the set of expanded nested instance keys;
- active review-loop tab by review-loop instance key;
- transient display positions for real top-level nodes while preview mode is active;
- expand, collapse, collapse-descendants, and tab-selection actions;
- project ID for safe navigation URLs; and
- a catalog map keyed by workflow ID.

Reset preview state when:

- a different parent workflow is loaded;
- the route project or workflow ID changes;
- the referenced workflow ID on an expanded call changes;
- the active review-loop child reference changes;
- the real call node is deleted; or
- a projection safety limit is exceeded and the affected branch must fall back.

Expansion state should not be stored in `localStorage`, `sessionStorage`, a URL query,
or backend state in the first delivery.

### 7.3 Display projection

Build a derived React Flow view from real store state plus transient preview state:

```ts
type BuilderProjectionInput = {
  rootWorkflow: Workflow;
  editableNodes: BuilderNode[];
  editableEdges: Edge[];
  catalogById: ReadonlyMap<string, Workflow>;
  expansion: ExpansionSnapshot;
};

type BuilderProjection = {
  nodes: BuilderDisplayNode[];
  edges: Edge[];
  realNodeIds: ReadonlySet<string>;
  previewNodeIds: ReadonlySet<string>;
  hasExpandedPreview: boolean;
  warnings: ProjectionWarning[];
};
```

Implement the projection as pure functions with no React, Zustand, navigation,
network, randomness, time, or DOM measurement dependencies. This makes the critical
namespacing and safety behavior testable.

Use a discriminated union for display node data. Do not make preview data look like
an editable `BuilderData` object:

```ts
type EditableNodeData = {
  kind: "editable";
  workflowNode: WorkflowNode;
  label: string;
  type: NodeType;
};

type CompositeContainerData = {
  kind: "composite";
  instanceKey: string;
  callNode: WorkflowNode;
  childWorkflow: Workflow | null;
  branch: "subworkflow" | "initial" | "revision";
  depth: number;
  warning?: string;
};

type PreviewNodeData = {
  kind: "preview";
  instanceKey: string;
  workflowNode: WorkflowNode;
  workflowId: string;
  depth: number;
};
```

Equivalent names are acceptable, but the type system must prevent a preview node
from being passed to editable store mutations accidentally.

### 7.4 Generated IDs

Generated display IDs must be:

- deterministic for identical input;
- unique across all visible instances;
- derived from call-site instance paths;
- impossible to collide with real root node IDs; and
- never serialized.

Use a reserved prefix not allowed by the workflow identifier schema, such as:

```text
preview/root::quality/node::lint
preview/root::quality/edge::lint_to_test
```

Do not use `crypto.randomUUID()` for projection IDs.

### 7.5 React Flow change filtering

The `onNodesChange` and `onEdgesChange` handlers must never forward preview changes
to the Zustand store.

When any preview is expanded:

- keep real top-level nodes draggable and child preview nodes non-draggable;
- set `nodesConnectable={false}`;
- reject connection creation defensively even if a handle event occurs;
- ignore all preview node changes;
- capture real-node position changes in transient preview state rather than forwarding
  them to the Zustand store;
- allow selection changes only for real top-level nodes.

When all previews are collapsed, preserve existing drag, connect, cycle prevention,
edge editing, and serialization behavior exactly.

Add a small, non-modal canvas notice while expanded:

```text
Preview mode: child graphs are read-only. Parent node moves are temporary; collapse
to edit saved positions or connections.
```

This makes the temporary interaction mode understandable and is also a non-color
state indicator.

## 8. React Flow hierarchy and rendering

Use React Flow compound nodes rather than nesting a second `<ReactFlow>` instance
inside a card. Nested canvases create conflicting pan, zoom, focus, and pointer
behavior.

For each expanded composite:

- the composite container is the parent node;
- direct child preview nodes use `parentId` pointing to that container;
- child positions are relative to the container;
- nested composite preview nodes may themselves be parents of deeper preview nodes;
- ancestors must appear before descendants in the final nodes array;
- all descendants are read-only;
- internal edge endpoints use generated descendant IDs; and
- external root edges continue using the real top-level call-node ID.

Do not set `expandParent` and depend on user dragging to size containers. Calculate
container sizes bottom-up before producing React Flow nodes.

Suggested node types:

```ts
const nodeTypes = {
  workflow: WorkflowCard,
  compositePreview: CompositePreviewNode,
  workflowPreview: WorkflowPreviewNode,
};
```

It is acceptable for an expanded top-level node to switch from `workflow` to
`compositePreview` while retaining the same real ID.

## 9. Nested layout

### 9.1 Constants

Put layout constants in one module and cover them with tests. Initial values may be
tuned visually:

```ts
const PREVIEW_NODE_WIDTH = 180;
const PREVIEW_NODE_HEIGHT = 82;
const COMPOSITE_HEADER_HEIGHT = 76;
const COMPOSITE_PADDING = 32;
const COMPOSITE_MIN_WIDTH = 560;
const COMPOSITE_MIN_HEIGHT = 220;
const SIBLING_CLEARANCE = 48;
```

Do not read rendered CSS dimensions during the projection. CSS and layout constants
must agree. Prefer explicit `width` and `height` styles on projected nodes.

### 9.2 Child coordinate normalization

Stored workflow node positions may be negative, sparse, or very large. For each
visible child graph:

1. recursively calculate the rendered dimensions of nested expanded nodes;
2. calculate the minimum child X and Y;
3. translate direct child positions so the minimum starts after container header and
   padding;
4. calculate the maximum translated right and bottom edges;
5. size the container to those bounds plus padding; and
6. enforce minimum and maximum dimensions.

Preserve the child's relative geometry. Do not run an authored child through a new
DAG layout algorithm.

### 9.3 Top-level collision avoidance

Expanding a composite must not permanently move authored nodes. Produce temporary
display offsets for top-level nodes.

The collision algorithm must be pure, deterministic, and separately tested. It must:

- treat each top-level node as a rectangle using its projected dimensions;
- preserve the active expanded container's authored top-left position as the anchor;
- keep at least `SIBLING_CLEARANCE` between the expanded rectangle and every other
  top-level rectangle;
- resolve cascaded collisions until no display rectangles overlap;
- use stable ordering based on authored Y, authored X, then node ID;
- avoid moving nodes to the left of or above their authored positions;
- cap iterations and return a warning/fallback rather than loop indefinitely; and
- return display positions without mutating input nodes.

A safe deterministic "push right or down by the smaller positive displacement"
rectangle-packing strategy is sufficient. A new layout dependency such as ELK or
Dagre is not required and should not be added unless the simple algorithm cannot
meet the acceptance fixtures.

For multiple nested expansions, first compute the complete active top-level
container size bottom-up, then run top-level collision avoidance once.

Collapsing all previews must immediately render every real node at its exact current
store position. There must be no "restore positions" mutation because store positions
were never changed.

### 9.4 Viewport behavior

On the transition from collapsed to expanded:

- wait until the projection has committed;
- call React Flow viewport helpers to fit or focus the active composite with padding;
- respect the user's reduced-motion preference;
- avoid repeatedly fitting on query polling or unrelated inspector edits; and
- keep controls available for manual zoom and pan.

On nested expansion and review-tab changes, fit the active top-level composite only
when its new bounds are substantially outside the viewport. Do not cause continuous
viewport jumps.

Collapsing should keep the parent call node visible. It need not restore the exact
previous zoom.

## 10. Accessibility

Accessibility is part of the acceptance gate.

Required behavior:

- every expand/collapse/open control is a semantic button or link;
- accessible names include the call or child workflow name;
- `aria-expanded` is present on expansion controls;
- `aria-controls` points to a stable composite panel ID where practical;
- review-loop tabs implement the WAI-ARIA tabs keyboard pattern;
- focus remains on the toggle after expansion;
- after collapse from a nested toggle, focus moves to the nearest still-mounted
  ancestor toggle;
- **Open workflow** clearly indicates that it opens a new tab, both visually and in
  its accessible name;
- preview mode, read-only state, missing references, depth limits, and truncation are
  communicated in text, not color alone;
- focus indicators meet the existing UI's visible focus treatment;
- controls have at least a 32-by-32 CSS-pixel hit area;
- generated preview nodes have meaningful `aria-label` values containing workflow
  name, node type, and node label;
- decorative icons are hidden from assistive technology;
- container color contrast meets WCAG AA for normal text; and
- motion used for fitting or transitions is disabled under
  `prefers-reduced-motion: reduce`.

Add a visually hidden live region at builder scope. Announce concise state changes:

- `<workflow name> expanded, <n> nodes`;
- `<workflow name> collapsed`;
- `Showing initial workflow <name>`; and
- preview limit or missing-reference warnings.

Do not announce every rendered child node.

## 11. Review-loop and subworkflow visual language

Preserve existing node colors and glyphs where possible:

- subworkflow containers retain the existing blue-grey accent;
- review-loop containers retain the existing pink accent;
- preview nodes retain type accents but use a read-only treatment;
- nesting depth should be visible through borders/backgrounds, not increasingly
  smaller text; and
- internal edge arrows use a quieter color than parent graph edges.

Every composite header must say `Sub-workflow` or `Review loop`. Do not rely on icon
or color to distinguish them.

Add a compact depth breadcrumb when nested, for example:

```text
Parent workflow / Quality checks / Security scan
```

Truncate visually with a title/accessible label containing the complete path.

## 12. Safety and performance budgets

The catalog and workflow validation should normally prevent recursion and excessive
depth, but the renderer must not trust catalog data blindly.

Apply these display-only safeguards:

```ts
const MAX_VISIBLE_PREVIEW_DEPTH = 8;
const MAX_VISIBLE_PREVIEW_NODES = 250;
const MAX_COMPOSITE_WIDTH = 2400;
const MAX_COMPOSITE_HEIGHT = 1800;
const MAX_COLLISION_PASSES = 1000; // or a demonstrably equivalent bounded cap
```

The implementation may tune the exact size/pass numbers, but must keep explicit,
tested limits.

Behavior at limits:

- detect a repeated workflow ID in the active ancestor chain before recursing;
- render a warning card `Recursive reference cannot be previewed`;
- at maximum depth render `Preview depth limit reached` plus **Open workflow**;
- at node budget render the nodes already admitted in deterministic traversal order,
  then a `Preview truncated` warning;
- when a container exceeds maximum dimensions, clamp it and render a clearly labeled
  internal scroll region or truncation state;
- never use unbounded recursive rendering or collision loops; and
- never treat a renderer limit as workflow validation success or failure.

Projection should be wrapped in `useMemo` with stable inputs. Catalog lookup must use
a `Map`, not repeated full-array scans at every nesting level.

The target performance envelope is:

- a 100-node root with a 100-node expanded child projects without a perceptible
  multi-second pause on a normal development machine;
- expansion does not trigger network requests per child;
- React keys remain stable across inspector edits; and
- catalog refetches do not collapse a valid active branch unless its referenced
  definition actually disappears or changes identity.

## 13. Error isolation

An exception in preview projection must not make the workflow definition
uneditable.

Add a narrow error boundary around the expanded preview layer or otherwise provide
equivalent isolation. On failure:

- render the original collapsed real node;
- show `Child preview could not be rendered`;
- log only non-sensitive structural information in development diagnostics;
- provide a collapse/reset action; and
- keep validation, inspector editing, and Store available.

Do not log workflow variable values, prompt bodies, command bodies, mappings, or any
credential-related material as part of preview diagnostics. IDs, node counts, node
types, and error class/message are sufficient.

## 14. Suggested code organization

Exact filenames may change if repository conventions strongly suggest alternatives,
but keep the concerns separated.

```text
frontend/src/workflow-builder/
├── CompositePreviewNode.tsx
├── WorkflowPreviewNode.tsx
├── expansion-context.tsx
├── projection.ts
├── preview-layout.ts
├── WorkflowCard.tsx
└── store.ts
```

Responsibilities:

- `expansion-context.tsx`: ephemeral expansion state, tab state, catalog index,
  reset rules, actions, and live-region message;
- `projection.ts`: pure recursive workflow-to-display-node/edge projection,
  namespacing, budgets, warnings, and discriminated types;
- `preview-layout.ts`: pure bottom-up bounds, coordinate normalization, and
  top-level collision avoidance;
- `CompositePreviewNode.tsx`: expanded container, handles, header, controls,
  warnings, review tabs, and accessibility;
- `WorkflowPreviewNode.tsx`: compact read-only internal card and nested expansion
  toggle;
- `WorkflowCard.tsx`: collapsed composite expansion affordance while preserving
  existing cards; and
- `WorkflowBuilderPage.tsx`: provider wiring, projection memoization, filtered
  React Flow handlers, viewport effects, preview-mode notice, and node types.

Avoid a broad refactor of `RunDetailPage.tsx`. It uses run snapshots and invocation
state, while builder preview uses the editable catalog. Sharing small presentation
components is acceptable only if it does not blur those different data sources.

## 15. Detailed implementation sequence

Implement in reviewable phases. Keep the builder usable after every phase.

### Phase 1: Test foundation and pure projection types

1. Add frontend unit/component test dependencies:
   - `vitest`;
   - `jsdom`;
   - `@testing-library/react`;
   - `@testing-library/user-event`; and
   - `@testing-library/jest-dom`.
2. Add `npm --prefix frontend run test` as a non-watch CI command.
3. Add test configuration and setup without weakening strict TypeScript.
4. Add the discriminated display-node types.
5. Implement catalog indexing, deterministic instance keys, generated IDs, and
   one-level projection as pure functions.
6. Prove through tests that projected nodes never enter serialization.

Do not introduce Playwright in this phase. The repository has no existing browser
test harness, and standing one up would expand the change substantially. Browser
acceptance remains mandatory and is listed below.

### Phase 2: One-level subworkflow expansion

1. Add transient expansion context/state.
2. Add collapsed-card expansion controls.
3. Add the expanded compound container and read-only child nodes.
4. Keep external edges on the real call-node ID.
5. Filter React Flow changes and disable topology changes in preview mode.
6. Add missing, loading, error, and empty states.
7. Add **Open workflow** in a new tab.
8. Add accessibility labels, focus behavior, and live announcements.

At this gate, one-level subworkflow preview must be complete and safe before nesting
is attempted.

### Phase 3: Deterministic sizing and collision avoidance

1. Implement explicit preview dimensions.
2. Normalize negative and sparse child coordinates.
3. Calculate container bounds bottom-up.
4. Implement bounded temporary top-level collision avoidance.
5. Focus the expanded container without mutating authored positions.
6. Verify collapse restores exact display positions from the store.

### Phase 4: Nested subworkflows

1. Make preview composite nodes expandable.
2. Add instance-path state and ID namespacing.
3. Add ancestor-chain recursion detection.
4. Add depth, node, and dimension budgets.
5. Make ancestor containers grow bottom-up.
6. Test identical child definitions at different call sites.

### Phase 5: Review-loop support

1. Add the expanded review-loop container.
2. Add accessible initial/revision tabs.
3. Resolve the active child according to current configuration.
4. Clear descendant expansion state on tab changes.
5. Support nested composites within the active child.
6. Add absent/missing revision states.

### Phase 6: Documentation and polish

1. Update `docs/guides/workflow-builder.md`.
2. Add a screenshot only if the repository's screenshot workflow can produce a
   representative, non-sensitive example.
3. Verify reduced motion, keyboard navigation, zoom/pan, large graphs, and error
   fallbacks manually.
4. Run all frontend and repository verification gates.

## 16. Automated test specification

Tests are required for every behavior below. Prefer table-driven fixtures and small,
readable workflow factories.

### 16.1 Projection unit tests

Cover:

- a graph without expansion is structurally equivalent to the editable graph;
- a subworkflow expansion resolves the correct catalog workflow;
- the container retains the real call-node ID;
- external edges retain their original source and target IDs;
- internal nodes and edges receive deterministic namespaced IDs;
- two calls to the same workflow produce distinct IDs;
- negative child coordinates normalize correctly;
- empty children render an empty projection state;
- missing references render a warning without throwing;
- catalog loading/unavailable state does not throw;
- nested expansion orders every parent before its descendants;
- indirect recursive input is stopped before recursion;
- maximum depth is enforced;
- maximum visible node count is enforced deterministically;
- review initial and revision tabs select the correct definitions;
- changing review tab removes the old branch's descendants;
- absent revision reference is handled;
- generated IDs cannot equal valid real root IDs;
- identical input produces deeply equal projection output; and
- input workflow/node/edge objects are not mutated.

### 16.2 Layout unit tests

Cover:

- collapsed dimensions;
- bounds for one, multiple, and nested children;
- normalization of negative positions;
- sparse positions;
- minimum and maximum container dimensions;
- no overlap after one expanded container displaces several siblings;
- cascaded collisions;
- stable results regardless of input array order where stable sort keys are equal;
- authored expanded-container anchor remains unchanged;
- display offsets never mutate or replace store positions;
- collapse produces exact authored positions;
- bounded termination for adversarial overlapping fixtures; and
- warning/fallback behavior when the collision pass cap is reached.

### 16.3 Store and serialization regression tests

Add tests around the existing builder store:

- `setWorkflow` followed by `serialize` is unchanged by preview projection;
- expanding, nesting, changing review tabs, and collapsing do not change serialized
  workflow JSON;
- temporary collision positions never appear in serialized node positions;
- preview IDs never appear in nodes or edges sent to validation/save;
- existing add/update/delete/connect behavior remains unchanged when collapsed;
- cycle prevention still rejects a new root DAG cycle;
- deleting a real expanded call clears or safely invalidates preview state; and
- changing `workflow_id`, `initial_workflow_id`, or `revision_workflow_id` resets the
  affected branch.

For the strongest isolation test:

1. serialize a representative parent before expansion;
2. perform all expansion, nesting, tab, pan/zoom, and collapse actions;
3. serialize again; and
4. require deep equality.

### 16.4 Component and accessibility tests

Using Testing Library, cover:

- collapsed subworkflow has a discoverable expand button;
- the button exposes correct `aria-expanded`;
- clicking expansion does not invoke parent node selection unexpectedly;
- expanded container exposes collapse and open-in-new-tab controls;
- preview mode notice appears;
- child preview nodes are identified as read-only;
- missing and empty states are rendered in text;
- review tabs have correct roles, selected state, panels, and keyboard behavior;
- focus remains valid after expand, tab change, and nested collapse;
- live-region announcements are concise;
- parent dragging remains available but transient while expanded, child dragging and
  connections remain disabled, and normal authored dragging is restored after collapse; and
- Escape does not unexpectedly discard expansion unless explicitly implemented and
  documented.

Automated accessibility assertions should use semantic queries first. An additional
axe integration is welcome but not mandatory if it would add another dependency.

### 16.5 Existing behavior regression

At minimum, retain or add coverage proving:

- non-composite cards render exactly their existing labels and previews;
- node selection opens the inspector;
- inspector changes update the real selected node;
- validation and Store serialize only the parent definition;
- `wouldCreateCycle` behavior is unchanged;
- MiniMap and Controls remain mounted;
- opening a child does not replace the current tab; and
- run detail's `buildExpandedGraph` behavior and types still compile unchanged.

## 17. Manual browser acceptance matrix

Automated tests do not replace browser verification for React Flow geometry.

Run the following in Chromium and, if available locally, Firefox:

1. Expand a three-node subworkflow between two parent nodes.
2. Confirm the parent incoming/outgoing edges remain on the container.
3. Confirm siblings move temporarily and do not overlap the container.
4. Collapse and confirm exact original sibling positions return.
5. Expand a nested subworkflow three levels deep.
6. Expand a second top-level composite and confirm the first branch collapses.
7. Expand a review loop; switch between initial and revision with mouse and keyboard.
8. Confirm child nodes cannot be dragged, connected, deleted, or edited.
9. Confirm parent nodes can be dragged temporarily, connections remain disabled, and
   collapse restores the authored positions.
10. Edit the expanded real parent call's mappings in the inspector and save.
11. Confirm saved JSON/YAML contains only the original control node, not preview IDs.
12. Open a child workflow and confirm it opens in a new tab.
13. Test a missing child reference.
14. Test an empty child.
15. Test negative and widely spaced child positions.
16. Test two calls to the same child definition.
17. Test a child containing a review loop containing a subworkflow.
18. Test zoom, pan, MiniMap, fit view, and inspector resizing while expanded.
19. Test keyboard-only expand, collapse, review tabs, and open workflow.
20. Test at 200% browser zoom.
21. Test with `prefers-reduced-motion: reduce`.
22. Force a catalog query error and confirm the parent remains editable and savable.
23. Run a workflow before and after the frontend change and confirm run-detail graph,
    execution, and saved definition behavior are unchanged.

Record browser/version and results in the pull request or implementation handoff.

## 18. Acceptance criteria

The feature is complete only when all criteria below are true.

### Functional

- Subworkflow cards expand and collapse.
- Expanded containers show the correct referenced nodes and edges.
- Nested subworkflows work up to the configured visual safety limit.
- Review loops show correct initial/revision tabs.
- The second top-level expansion replaces the first.
- Collision avoidance produces a readable, non-overlapping top-level display.
- Collapse restores exact authored positions.
- Missing/empty/limited previews fail visibly and safely.

### Data safety

- Expansion state is absent from workflow JSON/YAML and API requests.
- Generated preview IDs are absent from validation/save payloads.
- Child node positions are never copied into the parent definition.
- Temporary top-level collision offsets are never persisted.
- Parent control-node identity and external edges remain unchanged.
- Child definitions cannot be modified from the parent preview.

### Non-regression

- Existing node creation, selection, inspector editing, deletion, edge connection,
  cycle prevention, validation, templates, and Store behavior work when collapsed.
- Run detail compiles and behaves as before.
- Backend tests pass without backend feature changes.
- No credential, prompt, command, or mapped variable values are newly logged.

### Accessibility

- All functionality is keyboard-operable.
- Expansion and tab state are exposed semantically.
- Focus never moves to an unmounted element without a defined recovery target.
- Read-only, missing, truncated, and preview-mode states are communicated in text.
- Reduced-motion behavior is respected.

### Quality

- Projection and layout are pure and covered by unit tests.
- Component behavior is covered by Testing Library tests.
- Strict TypeScript succeeds.
- Production build succeeds.
- Documentation is updated.

## 19. Verification commands

The implementation agent must run, at minimum:

```bash
npm --prefix frontend ci
npm --prefix frontend run test
npm --prefix frontend run check
npm --prefix frontend run build
npm --prefix docs run build
pytest
./scripts/verify.sh
```

If `./scripts/verify.sh` skips a dependency tree because it is not installed, run the
corresponding package commands explicitly after installation.

Also run:

```bash
npm --prefix frontend audit --audit-level=high
git diff --check
git status --short
```

Do not hide unrelated existing worktree changes. Preserve them and report any overlap
before editing.

## 20. Rollout and fallback

This feature is entirely derived frontend behavior, so rollback should be a frontend
revert with no data migration.

Recommended review boundaries:

1. test foundation and pure projection/layout;
2. one-level subworkflow UI;
3. nesting and collision handling;
4. review-loop and accessibility polish; and
5. documentation and final verification.

If the complete nested implementation proves unsafe or unstable, the acceptable
fallback is:

- ship one-level read-only subworkflow expansion;
- keep the one-top-level-expansion rule;
- keep preview-mode topology locking;
- show review-loop initial/revision summaries with **Open workflow** links instead of
  nested graphs; and
- retain the same serialization-isolation tests.

Do not fall back to mixing preview nodes into the editable store, editing child
definitions inline, or persisting temporary layout.

## 21. Agent handoff checklist

Before implementation:

- read `AGENTS.md` completely;
- read the normative workflow specification sections on workflow nodes,
  subworkflows, review loops, validation, the visual builder, and run graphs;
- inspect current builder/store/types/catalog code rather than assuming line numbers
  in this document are current;
- inspect `git status` and preserve unrelated changes; and
- make a written implementation plan matching the phases above.

During implementation:

- keep preview state and authored state physically and type-wise separate;
- add tests before or with each state/projection change;
- run targeted frontend tests after each phase;
- do not refactor backend or run execution opportunistically; and
- stop and report if the workflow catalog cannot provide a revision-consistent child
  definition.

Before handoff:

- complete every automated and manual acceptance item that the environment supports;
- report any unexecuted browser/provider checks explicitly;
- include the before/after serialization-isolation evidence;
- summarize added dependencies and audit result;
- list all changed files; and
- confirm no schema, migration, execution, snapshot, or run-detail behavior changed.

## 22. Definition of done

An author can safely open a parent workflow, expand a subworkflow or review loop,
understand its nested child topology, navigate through nested references, and then
collapse the preview without changing a single byte of authored workflow data unless
they deliberately edited the real parent node in the inspector.

The implementation is not done merely because the graph renders. It is done when
serialization isolation, deterministic layout, bounded failure behavior,
accessibility, non-regression tests, browser acceptance, and documentation all pass.
