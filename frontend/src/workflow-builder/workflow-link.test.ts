import { describe, expect, it } from "vitest";
import {
  newTabWorkflowRoute,
  workflowEditorNewTabHref,
  workflowEditorPath,
} from "./workflow-link";

describe("workflow editor links", () => {
  it("builds the canonical editor route", () => {
    expect(workflowEditorPath("project id", "child workflow")).toBe(
      "/projects/project%20id/workflows/child%20workflow/edit",
    );
  });

  it("routes a new tab through the SPA root and restores the editor path", () => {
    const href = workflowEditorNewTabHref("project", "child");
    expect(href).toBe("/?kyron_route=%2Fprojects%2Fproject%2Fworkflows%2Fchild%2Fedit");
    expect(newTabWorkflowRoute(href.slice(1))).toBe(
      "/projects/project/workflows/child/edit",
    );
  });

  it("rejects arbitrary route bridge targets", () => {
    expect(newTabWorkflowRoute("?kyron_route=https%3A%2F%2Fexample.test")).toBeUndefined();
    expect(newTabWorkflowRoute("?kyron_route=%2Fadmin")).toBeUndefined();
  });
});
