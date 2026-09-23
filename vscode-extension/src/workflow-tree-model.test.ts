import assert from "node:assert/strict";
import test from "node:test";

import type { Workflow } from "./types";
import { buildWorkflowFolderTree } from "./workflow-tree-model";

function workflow(id: string, name: string, folderPath = ""): Workflow {
  return {
    id,
    name,
    folder_path: folderPath,
    description: "",
    tags: [],
    inputs: {},
    node_count: 1,
    settings: {},
  };
}

test("buildWorkflowFolderTree creates sorted nested folders and keeps root workflows", () => {
  const tree = buildWorkflowFolderTree([
    workflow("deploy", "Deploy", "teams/platform"),
    workflow("audit", "Audit", "teams/security"),
    workflow("root_z", "Zulu"),
    workflow("build", "Build", "teams/platform"),
    workflow("root_a", "Alpha"),
  ]);

  assert.equal(tree.workflowCount, 5);
  assert.deepEqual(
    tree.workflows.map((item) => item.id),
    ["root_a", "root_z"],
  );
  assert.deepEqual(
    tree.children.map((folder) => folder.path),
    ["teams"],
  );
  assert.deepEqual(
    tree.children[0]?.children.map((folder) => folder.path),
    ["teams/platform", "teams/security"],
  );
  assert.deepEqual(
    tree.children[0]?.children[0]?.workflows.map((item) => item.id),
    ["build", "deploy"],
  );
});

test("buildWorkflowFolderTree merges shared path segments", () => {
  const tree = buildWorkflowFolderTree([
    workflow("one", "One", "product/api"),
    workflow("two", "Two", "product/api"),
  ]);

  assert.equal(tree.children.length, 1);
  assert.equal(tree.children[0]?.children.length, 1);
  assert.equal(tree.children[0]?.children[0]?.workflowCount, 2);
});
