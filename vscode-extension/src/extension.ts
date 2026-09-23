import * as vscode from "vscode";

import { ApiError, KyronApi, normalizeServerUrl, type RunSubject } from "./api";
import { AuthenticationError, DeviceAuthentication } from "./auth";
import { currentBranch, matchWorkspaceProject } from "./git";
import { positiveIntegerValidation, validateWorkflowInput } from "./input";
import { currentReviewForUser } from "./review";
import {
  RunTreeItem,
  RunTreeProvider,
  WorkflowTreeItem,
  WorkflowTreeProvider,
  type WorkflowTreeElement,
} from "./tree";
import type {
  ChangeRequest,
  Project,
  User,
  ValidationIssue,
  Workflow,
  WorkflowInput,
} from "./types";

const PROJECT_SELECTION_KEY = "kyron.selectedProject";
const ACTIVE_STATUSES = new Set(["QUEUED", "RUNNING", "AWAITING_FEEDBACK", "RESUMING"]);
const RESUMABLE_STATUSES = new Set(["FAILED", "INTERRUPTED", "CANCELLED"]);

type StoredProjectSelection = {
  serverUrl: string;
  projectId: string;
};

type SubjectPick = vscode.QuickPickItem & {
  subject?: RunSubject;
  customBranch?: boolean;
  changeRequest?: boolean;
};

type InputResult =
  | { cancelled: true }
  | { cancelled: false; include: false }
  | { cancelled: false; include: true; value: string | number | boolean };

export function activate(context: vscode.ExtensionContext): void {
  const controller = new KyronController(context);
  context.subscriptions.push(controller);
  void controller.initialize();
}

export function deactivate(): void {}

class KyronController implements vscode.Disposable {
  private readonly authentication: DeviceAuthentication;
  private readonly workflowProvider = new WorkflowTreeProvider();
  private readonly runProvider = new RunTreeProvider();
  private readonly output = vscode.window.createOutputChannel("Kyron");
  private readonly status = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, 30);
  private readonly workflowView: vscode.TreeView<WorkflowTreeElement>;
  private readonly runView: vscode.TreeView<RunTreeItem>;
  private readonly disposables: vscode.Disposable[] = [];
  private readonly knownRunStatuses = new Map<string, string>();

  private api?: KyronApi;
  private user?: User;
  private projects: Project[] = [];
  private project?: Project;
  private workflows: Workflow[] = [];
  private hasDefinitionChanges = false;
  private outgoingDefinitionChanges = 0;
  private inReviewDefinitionChanges = 0;
  private catalogWarnings: ValidationIssue[] = [];
  private workflowLoading = false;
  private workflowError?: string;
  private canTrigger = false;
  private runItems: RunTreeItem[] = [];
  private pollTimer?: ReturnType<typeof setInterval>;
  private refreshing?: Promise<void>;
  private runRefreshing?: { project: Project; api: KyronApi; operation: Promise<void> };

  constructor(private readonly context: vscode.ExtensionContext) {
    this.authentication = new DeviceAuthentication(context);
    this.workflowView = vscode.window.createTreeView("kyron.workflows", {
      treeDataProvider: this.workflowProvider,
      showCollapseAll: true,
    });
    this.runView = vscode.window.createTreeView("kyron.runs", {
      treeDataProvider: this.runProvider,
      showCollapseAll: false,
    });
    this.status.command = "kyron.selectProject";
    this.status.show();

    this.disposables.push(
      this.workflowView,
      this.runView,
      this.workflowProvider,
      this.runProvider,
      this.output,
      this.status,
      this.command("kyron.connect", () => this.connect()),
      this.command("kyron.disconnect", () => this.disconnect()),
      this.command("kyron.selectProject", () => this.selectProject()),
      this.command("kyron.runWorkflow", (item?: WorkflowTreeItem) => this.runWorkflow(item)),
      this.command("kyron.openWorkflowInBrowser", (item?: WorkflowTreeItem) =>
        this.openWorkflowInBrowser(item),
      ),
      this.command("kyron.showCatalogWarnings", () => this.showCatalogWarnings()),
      this.command("kyron.refresh", () => this.refresh(false)),
      this.command("kyron.showRun", (item?: RunTreeItem) => this.showRun(item)),
      this.command("kyron.showRunLogs", (item?: RunTreeItem) => this.showRunLogs(item)),
      this.command("kyron.reviewGate", (item?: RunTreeItem) => this.reviewGate(item)),
      this.command("kyron.openRunInBrowser", (item?: RunTreeItem) => this.openRunInBrowser(item)),
      this.command("kyron.cancelRun", (item?: RunTreeItem) => this.cancelRun(item)),
      this.command("kyron.resumeRun", (item?: RunTreeItem) => this.resumeRun(item)),
      vscode.workspace.onDidChangeConfiguration((event) => {
        if (event.affectsConfiguration("kyron.pollIntervalSeconds")) {
          this.startPolling();
        }
        if (event.affectsConfiguration("kyron.serverUrl")) {
          void this.initialize();
        }
      }),
    );
    this.updatePresentation();
  }

  async initialize(): Promise<void> {
    this.stopPolling();
    const serverUrl = this.configuredServerUrl(true);
    if (!serverUrl || !(await this.authentication.hasSession(serverUrl))) {
      await this.setDisconnected();
      return;
    }
    this.api = new KyronApi(serverUrl, this.authentication);
    try {
      this.user = await this.api.me();
      await this.setConnected(true);
      await this.refresh(true);
      this.startPolling();
    } catch (error) {
      await this.setDisconnected();
      if (!(error instanceof ApiError && error.status === 401)) {
        this.showError(error);
      }
    }
  }

  dispose(): void {
    this.stopPolling();
    for (const disposable of this.disposables) disposable.dispose();
  }

  private command(command: string, callback: (...args: never[]) => Promise<void>): vscode.Disposable {
    return vscode.commands.registerCommand(command, (...args: never[]) => {
      void callback(...args).catch((error: unknown) => this.showError(error));
    });
  }

  private async connect(): Promise<void> {
    const configured = vscode.workspace.getConfiguration("kyron").get<string>("serverUrl", "");
    const rawUrl =
      configured ||
      (await vscode.window.showInputBox({
        title: "Connect to Kyron",
        prompt: "Kyron deployment URL",
        placeHolder: "https://kyron.example.internal",
        ignoreFocusOut: true,
        validateInput: (value) => {
          try {
            normalizeServerUrl(value);
            return undefined;
          } catch (error) {
            return error instanceof Error ? error.message : "Invalid URL";
          }
        },
      }));
    if (!rawUrl) return;
    const serverUrl = normalizeServerUrl(rawUrl);
    const storedServer = this.context.globalState.get<string>("kyron.vscode.serverUrl");
    if (storedServer && storedServer !== serverUrl) {
      await this.authentication.signOut();
    }
    await vscode.workspace
      .getConfiguration("kyron")
      .update("serverUrl", serverUrl, vscode.ConfigurationTarget.Global);
    if (!(await this.authentication.hasSession(serverUrl))) {
      await this.authentication.signIn(serverUrl);
    }
    this.api = new KyronApi(serverUrl, this.authentication);
    this.user = await this.api.me();
    await this.setConnected(true);
    await this.refreshProjects();
    if (!this.project) {
      await this.selectProject();
    } else {
      await this.refreshProjectContent(false);
    }
    this.startPolling();
    vscode.window.showInformationMessage(`Connected to Kyron as ${this.user.display_name}.`);
  }

  private async disconnect(): Promise<void> {
    await this.authentication.signOut();
    await this.setDisconnected();
    vscode.window.showInformationMessage("VS Code is disconnected from Kyron.");
  }

  private async setConnected(connected: boolean): Promise<void> {
    await vscode.commands.executeCommand("setContext", "kyron.connected", connected);
    if (!connected) {
      await vscode.commands.executeCommand("setContext", "kyron.projectSelected", false);
    }
    this.updatePresentation();
  }

  private async setDisconnected(): Promise<void> {
    this.stopPolling();
    this.api = undefined;
    this.user = undefined;
    this.projects = [];
    this.project = undefined;
    this.workflows = [];
    this.hasDefinitionChanges = false;
    this.outgoingDefinitionChanges = 0;
    this.inReviewDefinitionChanges = 0;
    this.catalogWarnings = [];
    this.workflowLoading = false;
    this.workflowError = undefined;
    this.canTrigger = false;
    this.runItems = [];
    this.knownRunStatuses.clear();
    this.workflowProvider.set([]);
    this.runProvider.set([]);
    await Promise.all([
      vscode.commands.executeCommand("setContext", "kyron.canTrigger", false),
      vscode.commands.executeCommand("setContext", "kyron.hasCatalogWarnings", false),
    ]);
    await this.setConnected(false);
  }

  private configuredServerUrl(showWarning: boolean): string | undefined {
    const value = vscode.workspace.getConfiguration("kyron").get<string>("serverUrl", "");
    if (!value) return undefined;
    try {
      return normalizeServerUrl(value);
    } catch (error) {
      if (showWarning) this.showError(error);
      return undefined;
    }
  }

  private requireApi(): KyronApi {
    if (!this.api) throw new ApiError("Connect VS Code to Kyron first", 401);
    return this.api;
  }

  private async refresh(silent: boolean): Promise<void> {
    if (this.refreshing) return this.refreshing;
    this.refreshing = (async () => {
      await this.refreshProjects();
      await this.refreshProjectContent(silent);
    })();
    try {
      await this.refreshing;
    } finally {
      this.refreshing = undefined;
    }
  }

  private async refreshProjects(): Promise<void> {
    const api = this.requireApi();
    this.projects = await api.projects();
    const selected = this.context.workspaceState.get<StoredProjectSelection>(PROJECT_SELECTION_KEY);
    const storedProject =
      selected?.serverUrl === api.serverUrl
        ? this.projects.find((project) => project.id === selected.projectId)
        : undefined;
    const matchedProject = storedProject ?? (await matchWorkspaceProject(this.projects));
    const nextProject = matchedProject ?? (this.projects.length === 1 ? this.projects[0] : undefined);
    if (nextProject?.id !== this.project?.id) {
      this.project = nextProject;
      this.canTrigger = false;
      this.knownRunStatuses.clear();
      if (nextProject) await this.storeProjectSelection(nextProject);
    }
    await vscode.commands.executeCommand("setContext", "kyron.projectSelected", Boolean(this.project));
    this.updatePresentation();
  }

  private async selectProject(): Promise<void> {
    if (!this.api) {
      await this.connect();
      return;
    }
    if (this.projects.length === 0) this.projects = await this.api.projects();
    if (this.projects.length === 0) {
      vscode.window.showWarningMessage("No accessible projects were found in this Kyron deployment.");
      return;
    }
    const choice = await vscode.window.showQuickPick(
      this.projects.map((project) => ({
        label: project.name,
        description: `${project.provider} · ${project.provider_project_path}`,
        detail: project.id === this.project?.id ? "Currently selected" : undefined,
        project,
      })),
      { title: "Select a Kyron project for this workspace", matchOnDescription: true },
    );
    if (!choice) return;
    const changed = choice.project.id !== this.project?.id;
    this.project = choice.project;
    if (changed) this.knownRunStatuses.clear();
    await this.storeProjectSelection(choice.project);
    await vscode.commands.executeCommand("setContext", "kyron.projectSelected", true);
    await this.refreshProjectContent(false);
    this.updatePresentation();
  }

  private async storeProjectSelection(project: Project): Promise<void> {
    await this.context.workspaceState.update(PROJECT_SELECTION_KEY, {
      serverUrl: this.requireApi().serverUrl,
      projectId: project.id,
    } satisfies StoredProjectSelection);
  }

  private async refreshProjectContent(silent: boolean): Promise<void> {
    if (!this.project) {
      this.workflows = [];
      this.hasDefinitionChanges = false;
      this.outgoingDefinitionChanges = 0;
      this.inReviewDefinitionChanges = 0;
      this.catalogWarnings = [];
      this.workflowLoading = false;
      this.workflowError = undefined;
      this.canTrigger = false;
      this.runItems = [];
      this.workflowProvider.set([]);
      this.runProvider.set([]);
      await Promise.all([
        vscode.commands.executeCommand("setContext", "kyron.canTrigger", false),
        vscode.commands.executeCommand("setContext", "kyron.hasCatalogWarnings", false),
      ]);
      this.updatePresentation();
      return;
    }
    const project = this.project;
    const api = this.requireApi();
    this.workflowLoading = true;
    this.workflowError = undefined;
    this.updatePresentation();
    try {
      const [catalog, access] = await Promise.all([
        api.workflows(project.id),
        api.projectAccess(project.id),
        this.refreshRuns(silent),
      ]);
      if (this.project !== project || this.api !== api) return;
      this.workflows = catalog.items;
      this.outgoingDefinitionChanges = catalog.outgoing_changes;
      this.inReviewDefinitionChanges = catalog.in_review_changes;
      this.hasDefinitionChanges =
        this.outgoingDefinitionChanges > 0 || this.inReviewDefinitionChanges > 0;
      this.catalogWarnings = catalog.warnings ?? [];
      this.canTrigger =
        access.permissions.includes("run.trigger") && this.user?.provider === project.provider;
      await Promise.all([
        vscode.commands.executeCommand(
          "setContext",
          "kyron.canTrigger",
          this.canTrigger && !this.hasDefinitionChanges,
        ),
        vscode.commands.executeCommand(
          "setContext",
          "kyron.hasCatalogWarnings",
          this.catalogWarnings.length > 0,
        ),
      ]);
      this.workflowProvider.set(this.workflows);
    } catch (error) {
      if (this.project === project && this.api === api) {
        this.workflowError = error instanceof Error ? error.message : "The workflow catalog could not be loaded";
      }
      throw error;
    } finally {
      if (this.project === project && this.api === api) {
        this.workflowLoading = false;
        this.updatePresentation();
      }
    }
  }

  private async refreshRuns(silent: boolean): Promise<void> {
    const project = this.project;
    if (!project) return;
    const api = this.requireApi();
    const existing = this.runRefreshing;
    if (existing?.project === project && existing.api === api) return existing.operation;
    const operation = (async () => {
      const response = await api.runs(project.id);
      const items = await Promise.all(
        response.items.map(async (run) => {
          if (run.status !== "AWAITING_FEEDBACK") return new RunTreeItem(run);
          try {
            const graph = await api.runGraph(run.id);
            const { gate, changeRequest, reviewRequested } = currentReviewForUser(graph, this.user);
            return new RunTreeItem(run, gate, changeRequest, reviewRequested);
          } catch {
            return new RunTreeItem(run);
          }
        }),
      );
      if (this.project !== project || this.api !== api) return;
      if (!silent) await this.notifyRunTransitions(items);
      else this.rememberRunStatuses(items);
      this.runItems = items;
      this.runProvider.set(items);
      this.updatePresentation();
    })();
    this.runRefreshing = { project, api, operation };
    try {
      await operation;
    } finally {
      if (this.runRefreshing?.operation === operation) this.runRefreshing = undefined;
    }
  }

  private rememberRunStatuses(items: RunTreeItem[]): void {
    for (const item of items) this.knownRunStatuses.set(item.run.id, item.run.status);
  }

  private async notifyRunTransitions(items: RunTreeItem[]): Promise<void> {
    for (const item of items) {
      const previous = this.knownRunStatuses.get(item.run.id);
      this.knownRunStatuses.set(item.run.id, item.run.status);
      if (!previous || previous === item.run.status) continue;
      if (item.run.status === "AWAITING_FEEDBACK" && item.reviewRequested) {
        const choice = await vscode.window.showWarningMessage(
          `Kyron run ${item.run.id.slice(0, 8)} is awaiting review.`,
          "Review gate",
        );
        if (choice === "Review gate") await this.reviewGate(item);
      } else if (item.run.status === "COMPLETED") {
        vscode.window.showInformationMessage(`Kyron run ${item.run.id.slice(0, 8)} completed.`);
      } else if (item.run.status === "FAILED" || item.run.status === "INTERRUPTED") {
        vscode.window.showErrorMessage(
          `Kyron run ${item.run.id.slice(0, 8)} ${item.run.status.toLowerCase()}: ${item.run.error_message ?? "open the run for details"}`,
        );
      }
    }
  }

  private async runWorkflow(item?: WorkflowTreeItem): Promise<void> {
    if (!this.project) {
      await this.selectProject();
      if (!this.project) return;
    }
    const workflow = item?.workflow ?? (await this.pickWorkflow("Run a Kyron workflow"));
    if (!workflow) return;
    if (!this.canTrigger) {
      vscode.window.showWarningMessage(
        `Your current ${this.user?.provider ?? "provider"} identity and project role cannot trigger workflows for this project.`,
      );
      return;
    }
    if (this.hasDefinitionChanges) {
      vscode.window.showWarningMessage(
        "This project has unmerged workflow-definition changes. Publish and merge them, then refresh before triggering from VS Code so the displayed definition matches the trusted definition Kyron executes.",
      );
      return;
    }
    const subject = await this.pickSubject(this.project);
    if (!subject) return;
    const inputs = await promptWorkflowInputs(workflow);
    if (!inputs) return;
    const confirmation = await vscode.window.showInformationMessage(
      `Run “${workflow.name}” against ${subjectLabel(subject)}?`,
      {
        modal: true,
        detail: `${Object.keys(inputs).length} explicit input${Object.keys(inputs).length === 1 ? "" : "s"}; workflow definitions will be loaded from the run's exact base commit.`,
      },
      "Run Workflow",
    );
    if (confirmation !== "Run Workflow") return;
    const result = await this.requireApi().trigger(this.project.id, workflow.id, subject, inputs);
    await this.refreshRuns(true);
    const choice = await vscode.window.showInformationMessage(
      `Kyron run ${result.run_id.slice(0, 8)} was queued.`,
      "Show run",
    );
    if (choice === "Show run") {
      const runItem = this.runItems.find((candidate) => candidate.run.id === result.run_id);
      await this.showRun(runItem, result.run_id);
    }
  }

  private async pickWorkflow(title: string): Promise<Workflow | undefined> {
    return (
      await vscode.window.showQuickPick(
        [...this.workflows]
          .sort(
            (left, right) =>
              left.folder_path.localeCompare(right.folder_path) ||
              left.name.localeCompare(right.name) ||
              left.id.localeCompare(right.id),
          )
          .map((workflow) => ({
            label: workflow.name,
            description: workflow.folder_path
              ? `.workflowEngine/${workflow.folder_path} · ${workflow.id}`
              : `.workflowEngine/ · ${workflow.id}`,
            detail: workflow.description || "No description",
            workflow,
          })),
        { title, matchOnDescription: true, matchOnDetail: true },
      )
    )?.workflow;
  }

  private async openWorkflowInBrowser(item?: WorkflowTreeItem): Promise<void> {
    if (!this.project) {
      await this.selectProject();
      if (!this.project) return;
    }
    const workflow = item?.workflow ?? (await this.pickWorkflow("Open a Kyron workflow"));
    if (!workflow) return;
    const path = `/projects/${encodeURIComponent(this.project.id)}/workflows/${encodeURIComponent(workflow.id)}/edit`;
    await vscode.env.openExternal(vscode.Uri.parse(`${this.requireApi().serverUrl}${path}`));
  }

  private async showCatalogWarnings(): Promise<void> {
    if (this.catalogWarnings.length === 0) {
      vscode.window.showInformationMessage("Kyron found no workflow catalog warnings.");
      return;
    }
    this.output.clear();
    this.output.appendLine(
      `Kyron workflow catalog — ${this.catalogWarnings.length} skipped or invalid definition${this.catalogWarnings.length === 1 ? "" : "s"}`,
    );
    for (const warning of this.catalogWarnings) {
      this.output.appendLine(`${warning.path} [${warning.code}]: ${warning.message}`);
    }
    this.output.show(true);
  }

  private async pickSubject(project: Project): Promise<RunSubject | undefined> {
    const branch = await currentBranch();
    const choices: SubjectPick[] = [];
    if (branch) {
      choices.push({
        label: `Current branch: ${branch}`,
        description: "Workspace Git branch",
        subject: { type: "branch", ref: branch },
      });
    }
    if (project.default_branch !== branch) {
      choices.push({
        label: `Default branch: ${project.default_branch}`,
        subject: { type: "branch", ref: project.default_branch },
      });
    }
    choices.push(
      { label: "Another branch…", customBranch: true },
      {
        label: project.provider === "gitlab" ? "Merge request…" : "Pull request…",
        changeRequest: true,
      },
    );
    const choice = await vscode.window.showQuickPick(choices, {
      title: "Choose the workflow subject",
      placeHolder: "Kyron resolves this subject on the code host",
    });
    if (!choice) return undefined;
    if (choice.subject) return choice.subject;
    if (choice.customBranch) {
      const ref = await vscode.window.showInputBox({
        title: "Branch to run against",
        prompt: "Remote branch name",
        validateInput: (value) => (value.trim() ? undefined : "Enter a branch name"),
      });
      return ref ? { type: "branch", ref: ref.trim() } : undefined;
    }
    const number = await vscode.window.showInputBox({
      title: project.provider === "gitlab" ? "Merge request number" : "Pull request number",
      prompt: "Enter the numeric request number",
      validateInput: positiveIntegerValidation,
    });
    return number ? { type: "change_request", number: Number(number) } : undefined;
  }

  private async showRun(item?: RunTreeItem, runId?: string): Promise<void> {
    const selected = item ?? (await this.pickRun());
    const id = selected?.run.id ?? runId;
    if (!id) return;
    const run = await this.requireApi().run(id);
    this.output.clear();
    this.output.appendLine(`Kyron run ${run.id}`);
    this.output.appendLine(`Workflow: ${run.root_workflow_id}`);
    this.output.appendLine(`Status: ${run.status}`);
    this.output.appendLine(`Subject: ${run.subject_type.toLowerCase()} ${run.subject_ref}`);
    this.output.appendLine(`Base commit: ${run.base_commit_sha}`);
    if (run.branch_name) this.output.appendLine(`Managed branch: ${run.branch_name}`);
    if (run.change_request_url) this.output.appendLine(`Change request: ${run.change_request_url}`);
    if (run.error_message) this.output.appendLine(`Error: ${run.error_message}`);
    this.output.show(true);
    const actions = ["Show logs", "Open in Kyron"];
    if (run.status === "AWAITING_FEEDBACK") actions.unshift("Review gate");
    if (ACTIVE_STATUSES.has(run.status)) actions.push("Cancel run");
    if (RESUMABLE_STATUSES.has(run.status)) actions.push("Resume run");
    const action = await vscode.window.showInformationMessage(
      `${run.root_workflow_id} is ${run.status.toLowerCase().replaceAll("_", " ")}.`,
      ...actions,
    );
    const current = this.runItems.find((candidate) => candidate.run.id === run.id) ?? new RunTreeItem(run);
    if (action === "Show logs") await this.showRunLogs(current);
    if (action === "Open in Kyron") await this.openRunInBrowser(current);
    if (action === "Review gate") await this.reviewGate(current);
    if (action === "Cancel run") await this.cancelRun(current);
    if (action === "Resume run") await this.resumeRun(current);
  }

  private async showRunLogs(item?: RunTreeItem): Promise<void> {
    const selected = item ?? (await this.pickRun());
    if (!selected) return;
    const events = await this.requireApi().logs(selected.run.id);
    this.output.clear();
    this.output.appendLine(`Kyron run ${selected.run.id} — latest ${events.length} log events`);
    for (const event of events) {
      const scope = event.node_path ?? event.invocation_path ?? "run";
      this.output.appendLine(`${event.timestamp} ${event.level.padEnd(7)} [${scope}] ${event.message}`);
    }
    this.output.show(false);
  }

  private async reviewGate(item?: RunTreeItem): Promise<void> {
    const selected = item ?? (await this.pickRun("AWAITING_FEEDBACK"));
    if (!selected) return;
    let gate = selected.gate;
    let changeRequest = selected.changeRequest;
    if (!gate || !changeRequest) {
      const graph = await this.requireApi().runGraph(selected.run.id);
      ({ gate, changeRequest } = currentReviewForUser(graph, this.user));
    }
    if (!gate) {
      vscode.window.showWarningMessage("This run has no open review gate.");
      return;
    }
    if (!changeRequest) {
      vscode.window.showWarningMessage("The gate does not have a published change request yet.");
      return;
    }
    if (changeRequest.provider === "gitlab") {
      await this.focusCodeHostReview(
        "GitLab.gitlab-workflow",
        ["workbench.view.extension.gitlab", "gl.showIssuesAndMergeRequests"],
        `Open !${changeRequest.provider_number} under merge requests assigned to @${this.user?.provider_username ?? "you"}. Approve it, or leave an @kyron comment requesting changes.`,
        changeRequest,
      );
    } else {
      await this.focusCodeHostReview(
        "GitHub.vscode-pull-request-github",
        ["workbench.view.extension.github-pull-request"],
        `Open #${changeRequest.provider_number} in GitHub Pull Requests. Approve it, or leave an @kyron comment requesting changes.`,
        changeRequest,
      );
    }
  }

  private async focusCodeHostReview(
    extensionId: string,
    focusCommands: string[],
    instruction: string,
    changeRequest: ChangeRequest,
  ): Promise<void> {
    const extension = vscode.extensions.getExtension(extensionId);
    if (extension) {
      if (!extension.isActive) await extension.activate();
      const available = new Set(await vscode.commands.getCommands(true));
      const focus = focusCommands.find((command) => available.has(command));
      if (focus) await vscode.commands.executeCommand(focus);
      const choice = await vscode.window.showInformationMessage(instruction, "Open in browser");
      if (choice === "Open in browser") await openExternalHttps(changeRequest.url);
      return;
    }
    const label = changeRequest.provider === "gitlab" ? "GitLab Workflow" : "GitHub Pull Requests";
    const choice = await vscode.window.showInformationMessage(
      `${label} is not installed. Install it to review without leaving VS Code.`,
      `Find ${label}`,
      "Open in browser",
    );
    if (choice === `Find ${label}`) {
      await vscode.commands.executeCommand("workbench.extensions.search", `@id:${extensionId}`);
    } else if (choice === "Open in browser") {
      await openExternalHttps(changeRequest.url);
    }
  }

  private async openRunInBrowser(item?: RunTreeItem): Promise<void> {
    const selected = item ?? (await this.pickRun());
    if (!selected) return;
    await vscode.env.openExternal(vscode.Uri.parse(`${this.requireApi().serverUrl}/runs/${selected.run.id}`));
  }

  private async cancelRun(item?: RunTreeItem): Promise<void> {
    const selected = item ?? (await this.pickRun());
    if (!selected) return;
    const confirmation = await vscode.window.showWarningMessage(
      `Cancel Kyron run ${selected.run.id.slice(0, 8)}?`,
      { modal: true },
      "Cancel Run",
    );
    if (confirmation !== "Cancel Run") return;
    await this.requireApi().cancel(selected.run.id);
    await this.refreshRuns(true);
  }

  private async resumeRun(item?: RunTreeItem): Promise<void> {
    const selected = item ?? (await this.pickRun());
    if (!selected) return;
    const confirmation = await vscode.window.showInformationMessage(
      `Resume Kyron run ${selected.run.id.slice(0, 8)}?`,
      { modal: true },
      "Resume Run",
    );
    if (confirmation !== "Resume Run") return;
    await this.requireApi().resume(selected.run.id);
    await this.refreshRuns(true);
  }

  private async pickRun(status?: string): Promise<RunTreeItem | undefined> {
    const items = status
      ? this.runItems.filter((candidate) => candidate.run.status === status)
      : this.runItems;
    return (
      await vscode.window.showQuickPick(
        items.map((item) => ({
          label: item.run.root_workflow_id,
          description: `${item.run.id.slice(0, 8)} · ${item.run.status.toLowerCase().replaceAll("_", " ")}`,
          item,
        })),
        { title: "Select a Kyron run" },
      )
    )?.item;
  }

  private startPolling(): void {
    this.stopPolling();
    if (!this.api) return;
    const seconds = vscode.workspace
      .getConfiguration("kyron")
      .get<number>("pollIntervalSeconds", 10);
    this.pollTimer = setInterval(() => {
      void this.refreshRuns(false).catch((error: unknown) => {
        if (isAuthenticationFailure(error)) this.showError(error);
        // Other transient polling failures are retried on the next interval.
      });
    }, Math.max(seconds, 3) * 1_000);
  }

  private stopPolling(): void {
    if (this.pollTimer) clearInterval(this.pollTimer);
    this.pollTimer = undefined;
  }

  private updatePresentation(): void {
    this.workflowView.description = this.project?.name;
    this.runView.description = this.project?.name;
    const workflowMessages: string[] = [];
    if (this.api && this.project) {
      if (this.workflowLoading) {
        workflowMessages.push("Loading workflows…");
      } else if (this.workflowError) {
        workflowMessages.push(`Could not load workflows: ${this.workflowError}`);
      } else if (this.workflows.length === 0) {
        workflowMessages.push("No workflows in this project.");
      }
      if (this.catalogWarnings.length > 0) {
        workflowMessages.push(
          `${this.catalogWarnings.length} workflow definition${this.catalogWarnings.length === 1 ? " was" : "s were"} skipped; open catalog warnings for details.`,
        );
      }
      if (this.hasDefinitionChanges) {
        const changes = [
          this.outgoingDefinitionChanges
            ? `${this.outgoingDefinitionChanges} outgoing change${this.outgoingDefinitionChanges === 1 ? "" : "s"}`
            : undefined,
          this.inReviewDefinitionChanges
            ? `${this.inReviewDefinitionChanges} change${this.inReviewDefinitionChanges === 1 ? "" : "s"} in review`
            : undefined,
        ].filter(Boolean);
        workflowMessages.push(`Running is disabled while workflow definitions have ${changes.join(" and ")}.`);
      } else if (!this.canTrigger) {
        workflowMessages.push("Your current identity cannot trigger workflows for this project.");
      }
    }
    this.workflowView.message = workflowMessages.length > 0 ? workflowMessages.join(" ") : undefined;
    if (!this.api) {
      this.status.text = "$(plug) Kyron";
      this.status.tooltip = "Connect VS Code to Kyron";
      this.status.command = "kyron.connect";
      return;
    }
    const active = this.runItems.filter((item) => ACTIVE_STATUSES.has(item.run.status)).length;
    this.status.text = this.project
      ? `$(rocket) ${this.project.name}${active ? ` · ${active} active` : ""}`
      : "$(rocket) Select Kyron project";
    this.status.tooltip = this.user
      ? `Connected to ${this.api.serverUrl} as ${this.user.display_name}`
      : `Connected to ${this.api.serverUrl}`;
    this.status.command = "kyron.selectProject";
  }

  private showError(error: unknown): void {
    if (error instanceof AuthenticationError && error.message === "Kyron connection was cancelled") {
      return;
    }
    if (isAuthenticationFailure(error)) {
      void this.setDisconnected();
    }
    const message = error instanceof Error ? error.message : "An unexpected Kyron error occurred";
    vscode.window.showErrorMessage(`Kyron: ${message}`);
  }
}

async function promptWorkflowInputs(
  workflow: Workflow,
): Promise<Record<string, string | number | boolean> | undefined> {
  const values: Record<string, string | number | boolean> = {};
  for (const [name, input] of Object.entries(workflow.inputs)) {
    const result = await promptWorkflowInput(name, input);
    if (result.cancelled) return undefined;
    if (result.include) values[name] = result.value;
  }
  return values;
}

async function promptWorkflowInput(name: string, input: WorkflowInput): Promise<InputResult> {
  const defaultDescription = input.default == null ? undefined : `Default: ${String(input.default)}`;
  if (input.type === "boolean") {
    const choices: Array<vscode.QuickPickItem & { include: boolean; value?: boolean }> = [
      { label: "True", value: true, include: true },
      { label: "False", value: false, include: true },
    ];
    if (!input.required || input.default != null) {
      choices.unshift({ label: "Use workflow default", description: defaultDescription, include: false });
    }
    const choice = await vscode.window.showQuickPick(choices, {
      title: `Input: ${name}`,
      placeHolder: input.description,
    });
    if (!choice) return { cancelled: true };
    return choice.include
      ? { cancelled: false, include: true, value: choice.value === true }
      : { cancelled: false, include: false };
  }

  const result = await vscode.window.showInputBox({
    title: `Input: ${name}`,
    prompt: input.description,
    value: input.default == null ? undefined : String(input.default),
    placeHolder: defaultDescription,
    validateInput: (value) => validateWorkflowInput(value, input),
  });
  if (result === undefined) return { cancelled: true };
  if (!result.trim() && (!input.required || input.default != null)) {
    return { cancelled: false, include: false };
  }
  if (input.type === "integer" || input.type === "number") {
    return { cancelled: false, include: true, value: Number(result) };
  }
  return { cancelled: false, include: true, value: result };
}

function subjectLabel(subject: RunSubject): string {
  return subject.type === "branch" ? `branch ${subject.ref}` : `change request #${subject.number}`;
}

async function openExternalHttps(rawUrl: string): Promise<void> {
  const url = new URL(rawUrl);
  if (url.protocol !== "https:") throw new Error("Refusing to open a non-HTTPS change request URL");
  await vscode.env.openExternal(vscode.Uri.parse(url.toString()));
}

function isAuthenticationFailure(error: unknown): boolean {
  return (
    (error instanceof ApiError && error.status === 401) ||
    (error instanceof AuthenticationError && error.code === "invalid_grant")
  );
}
