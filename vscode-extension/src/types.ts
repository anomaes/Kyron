export type User = {
  id: string;
  email: string;
  display_name: string;
  provider: "gitlab" | "github";
  provider_user_id: string;
  provider_username: string;
};

export type Project = {
  id: string;
  name: string;
  git_url: string;
  provider: "gitlab" | "github";
  provider_project_path: string;
  default_branch: string;
};

export type ProjectAccess = {
  permissions: string[];
};

export type WorkflowInput = {
  type: "string" | "integer" | "number" | "boolean";
  required: boolean;
  default?: string | number | boolean | null;
  description?: string;
};

export type Workflow = {
  id: string;
  name: string;
  description: string;
  tags: string[];
  inputs: Record<string, WorkflowInput>;
  node_count: number;
  folder_path: string;
  settings: {
    delivery_mode?: "propose_changes" | "report_only";
  };
};

export type WorkflowCatalog = {
  base_commit_sha: string;
  outgoing_changes: number;
  in_review_changes: number;
  change_request_url: string | null;
  warnings: ValidationIssue[];
  items: Workflow[];
};

export type ValidationIssue = {
  path: string;
  code: string;
  message: string;
};

export type Run = {
  id: string;
  root_workflow_id: string;
  project_id: string;
  status: string;
  status_version: number;
  base_ref: string;
  base_commit_sha: string;
  subject_type: "BRANCH" | "CHANGE_REQUEST";
  subject_ref: string;
  delivery_mode: "PROPOSE_CHANGES" | "REPORT_ONLY";
  branch_name: string | null;
  change_request_number: number | null;
  change_request_url: string | null;
  reviewer_provider: "gitlab" | "github";
  current_node_execution_id: string | null;
  error_type: string | null;
  error_message: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
};

export type RunsResponse = {
  items: Run[];
  page: number;
  page_size: number;
  total: number;
};

export type Gate = {
  id: string;
  status: string;
  checkpoint_commit_sha: string;
  change_request_id: string | null;
  policy_snapshot: {
    name?: string;
  };
};

export type ChangeRequest = {
  id: string;
  kind: string;
  provider: "gitlab" | "github";
  provider_number: number;
  url: string;
  status: string;
};

export type RunGraph = {
  gates: Gate[];
  change_requests: ChangeRequest[];
};

export type LogEvent = {
  sequence: number;
  timestamp: string;
  level: string;
  event_type: string;
  invocation_path: string | null;
  node_path: string | null;
  message: string;
};
