import * as vscode from "vscode";
import type { ChangeRequest, Gate, Run, Workflow } from "./types";

export class WorkflowTreeItem extends vscode.TreeItem {
  readonly contextValue = "kyronWorkflow";

  constructor(readonly workflow: Workflow) {
    super(workflow.name, vscode.TreeItemCollapsibleState.None);
    this.id = workflow.id;
    this.description = workflow.tags.length > 0 ? workflow.tags.join(", ") : workflow.id;
    this.tooltip = [
      workflow.name,
      workflow.description || "No description",
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
    if (run.status === "AWAITING_FEEDBACK") {
      this.contextValue = "kyronRunAwaitingFeedback";
    } else if (["QUEUED", "RUNNING", "RESUMING"].includes(run.status)) {
      this.contextValue = "kyronRunActive";
    } else if (["FAILED", "INTERRUPTED", "CANCELLED"].includes(run.status)) {
      this.contextValue = "kyronRunResumable";
    } else {
      this.contextValue = "kyronRun";
    }
    this.command = { command: "kyron.showRun", title: "Show Run Details", arguments: [this] };
  }
}

export class WorkflowTreeProvider implements vscode.TreeDataProvider<WorkflowTreeItem> {
  private readonly changed = new vscode.EventEmitter<WorkflowTreeItem | undefined>();
  readonly onDidChangeTreeData = this.changed.event;
  private items: WorkflowTreeItem[] = [];

  set(workflows: Workflow[]): void {
    this.items = workflows.map((workflow) => new WorkflowTreeItem(workflow));
    this.changed.fire(undefined);
  }

  getTreeItem(element: WorkflowTreeItem): vscode.TreeItem {
    return element;
  }

  getChildren(): WorkflowTreeItem[] {
    return this.items;
  }
}

export class RunTreeProvider implements vscode.TreeDataProvider<RunTreeItem> {
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
}

function prettyStatus(status: string): string {
  return status.toLowerCase().replaceAll("_", " ");
}

function statusIcon(status: string): vscode.ThemeIcon {
  switch (status) {
    case "COMPLETED":
      return new vscode.ThemeIcon("pass", new vscode.ThemeColor("testing.iconPassed"));
    case "FAILED":
      return new vscode.ThemeIcon("error", new vscode.ThemeColor("testing.iconFailed"));
    case "CANCELLED":
    case "INTERRUPTED":
      return new vscode.ThemeIcon("circle-slash");
    case "AWAITING_FEEDBACK":
      return new vscode.ThemeIcon("comment-discussion", new vscode.ThemeColor("notificationsWarningIcon.foreground"));
    case "QUEUED":
      return new vscode.ThemeIcon("watch");
    default:
      return new vscode.ThemeIcon("sync~spin");
  }
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
