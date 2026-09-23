const NEW_TAB_ROUTE_PARAMETER = "kyron_route";
const WORKFLOW_EDITOR_ROUTE = /^\/projects\/[^/?#]+\/workflows\/[^/?#]+\/edit$/;

export function workflowEditorPath(projectId: string, workflowId: string): string {
  return `/projects/${encodeURIComponent(projectId)}/workflows/${encodeURIComponent(workflowId)}/edit`;
}

export function workflowEditorNewTabHref(projectId: string, workflowId: string): string {
  // A new tab cannot use client-side navigation. Request the always-served SPA
  // root, then restore the validated editor route before React Router starts.
  const query = new URLSearchParams({
    [NEW_TAB_ROUTE_PARAMETER]: workflowEditorPath(projectId, workflowId),
  });
  return `/?${query.toString()}`;
}

export function newTabWorkflowRoute(search: string): string | undefined {
  const route = new URLSearchParams(search).get(NEW_TAB_ROUTE_PARAMETER);
  return route && WORKFLOW_EDITOR_ROUTE.test(route) ? route : undefined;
}
