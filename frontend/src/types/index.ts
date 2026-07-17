export type User = {
  id: string;
  email: string;
  display_name: string;
  avatar_url: string | null;
  gitlab_user_id: number;
  gitlab_username: string;
};

export type Project = {
  id: string;
  name: string;
  git_url: string;
  gitlab_project_id: number;
  local_path: string;
  default_branch: string;
  added_by: string;
  created_at: string;
  updated_at: string;
  token_configured: boolean;
};

export type Credential = {
  id: string;
  key_name: string;
  description: string | null;
  created_at: string;
  updated_at: string;
  configured: boolean;
};

export type NodeType =
  | "bash"
  | "script"
  | "prompt"
  | "human_feedback"
  | "subworkflow"
  | "review_loop";

export type WorkflowNode = {
  id: string;
  type: NodeType;
  label: string;
  join?: "and" | "or";
  config: Record<string, unknown>;
  position: { x: number; y: number };
};

export type WorkflowEdge = {
  id: string;
  source: string;
  target: string;
  condition: Record<string, unknown> | null;
};

export type Workflow = {
  id: string;
  name: string;
  description: string;
  version: 2;
  created_by: string;
  tags: string[];
  inputs: Record<string, { type: string; required?: boolean; default?: unknown; description?: string }>;
  outputs: Record<string, { type: string; source: string; description?: string }>;
  variables: Record<string, string | number | boolean>;
  nodes: WorkflowNode[];
  edges: WorkflowEdge[];
  settings: Record<string, unknown>;
};

export type WorkflowListItem = Workflow & { node_count: number };

export type Run = {
  id: string;
  root_workflow_id: string;
  project_id: string;
  triggered_by: string;
  status: string;
  status_version: number;
  base_ref: string;
  base_commit_sha: string;
  branch_name: string | null;
  current_head_sha: string | null;
  final_commit_sha: string | null;
  mr_iid: number | null;
  mr_url: string | null;
  reviewer_gitlab_user_id: number;
  current_invocation_id: string | null;
  current_node_execution_id: string | null;
  current_wave_id: string | null;
  error_type: string | null;
  error_message: string | null;
  created_at: string;
  queued_at: string;
  started_at: string | null;
  finished_at: string | null;
};

export type RunGraph = {
  snapshot: { root_workflow_id: string; workflows: Record<string, Workflow> };
  invocations: Array<{
    id: string;
    workflow_id: string;
    invocation_path: string;
    parent_invocation_id: string | null;
    parent_node_execution_id: string | null;
    loop_iteration: number;
    status: string;
  }>;
  waves: Array<Record<string, unknown>>;
  nodes: Array<{
    id: string;
    invocation_id: string;
    node_id: string;
    status: string;
  }>;
  attempts: Array<Record<string, unknown>>;
  edge_evaluations: Array<Record<string, unknown>>;
  feedback: Array<{ node_execution_id: string; iteration: number; message: string; event_type: string }>;
};

export type LogEvent = {
  type: string;
  sequence?: number;
  timestamp?: string;
  level?: string;
  event_type?: string;
  node_path?: string | null;
  source?: string;
  line?: string;
  message?: string;
};
