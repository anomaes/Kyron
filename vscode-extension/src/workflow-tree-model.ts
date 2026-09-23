import type { Workflow } from "./types";

export type WorkflowFolder = {
  name: string;
  path: string;
  workflows: Workflow[];
  children: WorkflowFolder[];
  workflowCount: number;
};

type MutableWorkflowFolder = Omit<WorkflowFolder, "children" | "workflowCount"> & {
  children: Map<string, MutableWorkflowFolder>;
};

export function buildWorkflowFolderTree(workflows: Workflow[]): WorkflowFolder {
  const root: MutableWorkflowFolder = {
    name: ".workflowEngine",
    path: "",
    workflows: [],
    children: new Map(),
  };

  for (const workflow of workflows) {
    let folder = root;
    for (const name of workflow.folder_path.split("/").filter(Boolean)) {
      const path = folder.path ? `${folder.path}/${name}` : name;
      let child = folder.children.get(name);
      if (!child) {
        child = { name, path, workflows: [], children: new Map() };
        folder.children.set(name, child);
      }
      folder = child;
    }
    folder.workflows.push(workflow);
  }

  return finalizeFolder(root);
}

function finalizeFolder(folder: MutableWorkflowFolder): WorkflowFolder {
  const children = [...folder.children.values()]
    .sort((left, right) => left.name.localeCompare(right.name))
    .map(finalizeFolder);
  const workflows = [...folder.workflows].sort(
    (left, right) => left.name.localeCompare(right.name) || left.id.localeCompare(right.id),
  );
  return {
    name: folder.name,
    path: folder.path,
    workflows,
    children,
    workflowCount:
      workflows.length + children.reduce((total, child) => total + child.workflowCount, 0),
  };
}
