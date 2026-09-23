import * as vscode from "vscode";
import { prettyStatus, runContextValue, statusIconSpec } from "./status";
import type { ChangeRequest, Gate, Run, Workflow } from "./types";
import { buildWorkflowFolderTree, type WorkflowFolder } from "./workflow-tree-model";

export type WorkflowTreeElement = WorkflowFolderTreeItem | WorkflowTreeItem;

export class WorkflowFolderTreeItem extends vscode.TreeItem {
  readonly contextValue = "kyronWorkflowFolder";

  constructor(readonly folder: WorkflowFolder) {
    super(folder.name, vscode.TreeItemCollapsibleState.Collapsed);
    this.id = `folder:${folder.path}`;
    this.description = `${folder.workflowCount}`;
    this.tooltip = `.workflowEngine/${folder.path}\n\n${folder.workflowCount} workflow${folder.workflowCount === 1 ? "" : "s"}`;
    this.iconPath = new vscode.ThemeIcon("folder");
  }
}

export class WorkflowTreeItem extends vscode.TreeItem {
  readonly contextValue = "kyronWorkflow";

  constructor(readonly workflow: Workflow) {
    super(workflow.name, vscode.TreeItemCollapsibleState.None);
    this.id = workflow.id;
    this.description = workflow.tags.length > 0 ? workflow.tags.join(", ") : workflow.id;
    this.tooltip = [
      workflow.name,
      workflow.description || "No description",
      workflow.folder_path ? `Folder: .workflowEngine/${workflow.folder_path}` : "Folder: .workflowEngine/",
      `${workflow.node_count} node${workflow.node_count === 1 ? "" : "s"}`,
    ].join("\n\n");
    this.iconPath = new vscode.ThemeIcon("workflow");
    this.command = { command: "kyron.runWorkflow", title: "Run Workflow", arguments: [this] };
  }
}

export class RunTreeItem extends vscode.TreeItem {
  readonly contextValue: string;

  constructor(
    readonly run: Run,
    readonly gate?: Gate,
    readonly changeRequest?: ChangeRequest,
  ) {
    super(`${run.root_workflow_id} · ${run.id.slice(0, 8)}`, vscode.TreeItemCollapsibleState.None);
    this.id = run.id;
    this.description = prettyStatus(run.status);
    this.tooltip = runTooltip(run, changeRequest);
    this.iconPath = statusIcon(run.status);
    this.contextValue = runContextValue(run.status);
    this.command = { command: "kyron.showRun", title: "Show Run Details", arguments: [this] };
  }
}

export class WorkflowTreeProvider implements vscode.TreeDataProvider<WorkflowTreeElement>, vscode.Disposable {
  private readonly changed = new vscode.EventEmitter<WorkflowTreeElement | undefined>();
  readonly onDidChangeTreeData = this.changed.event;
  private root = buildWorkflowFolderTree([]);

  set(workflows: Workflow[]): void {
    this.root = buildWorkflowFolderTree(workflows);
    this.changed.fire(undefined);
  }

  getTreeItem(element: WorkflowTreeElement): vscode.TreeItem {
    return element;
  }

  getChildren(element?: WorkflowTreeElement): WorkflowTreeElement[] {
    if (element instanceof WorkflowTreeItem) return [];
    const folder = element?.folder ?? this.root;
    return [
      ...folder.children.map((child) => new WorkflowFolderTreeItem(child)),
      ...folder.workflows.map((workflow) => new WorkflowTreeItem(workflow)),
    ];
  }

  dispose(): void {
    this.changed.dispose();
  }
}

export class RunTreeProvider implements vscode.TreeDataProvider<RunTreeItem>, vscode.Disposable {
  private readonly changed = new vscode.EventEmitter<RunTreeItem | undefined>();
  readonly onDidChangeTreeData = this.changed.event;
  private items: RunTreeItem[] = [];

  set(items: RunTreeItem[]): void {
    this.items = items;
    this.changed.fire(undefined);
  }

  getTreeItem(element: RunTreeItem): vscode.TreeItem {
    return element;
  }

  getChildren(): RunTreeItem[] {
    return this.items;
  }

  dispose(): void {
    this.changed.dispose();
  }
}

function statusIcon(status: string): vscode.ThemeIcon {
  const spec = statusIconSpec(status);
  const color =
    spec.color === "passed"
      ? new vscode.ThemeColor("testing.iconPassed")
      : spec.color === "failed"
        ? new vscode.ThemeColor("testing.iconFailed")
        : spec.color === "warning"
          ? new vscode.ThemeColor("notificationsWarningIcon.foreground")
          : undefined;
  return new vscode.ThemeIcon(spec.id, color);
}

function runTooltip(run: Run, changeRequest?: ChangeRequest): string {
  const lines = [
    run.root_workflow_id,
    `Status: ${prettyStatus(run.status)}`,
    `Subject: ${run.subject_ref}`,
    `Base commit: ${run.base_commit_sha.slice(0, 12)}`,
  ];
  if (changeRequest) {
    lines.push(`${changeRequest.provider === "gitlab" ? "Merge" : "Pull"} request: #${changeRequest.provider_number}`);
  }
  if (run.error_message) {
    lines.push(`Error: ${run.error_message}`);
  }
  return lines.join("\n\n");
}
