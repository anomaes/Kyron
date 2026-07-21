export type User = {
  id: string;
  email: string;
  display_name: string;
  avatar_url: string | null;
  provider: "gitlab" | "github";
  provider_user_id: string;
  provider_username: string;
  is_system_admin: boolean;
};

export type PiSettings = {
  provider?: string | null;
  model?: string | null;
  skill?: string | null;
};

export type Project = {
  id: string;
  name: string;
  git_url: string;
  provider: "gitlab" | "github";
  provider_project_id: string;
  provider_project_path: string;
  local_path: string;
  default_branch: string;
  pi: PiSettings;
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

export type NodeTemplate = {
  id: string;
  name: string;
  description: string;
  node: WorkflowNode;
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
  settings: Record<string, unknown> & { pi?: PiSettings };
};

export type WorkflowListItem = Workflow & { node_count: number };

export type DefinitionChangeStatus = {
  outgoing_changes: number;
  in_review_changes: number;
  change_request_url: string | null;
};

export type Run = {
  id: string;
  root_workflow_id: string;
  project_id: string;
  triggered_by: string;
  status: string;
  status_version: number;
  base_ref: string;
  base_commit_sha: string;
  local_definition_test: boolean;
  branch_name: string | null;
  current_head_sha: string | null;
  final_commit_sha: string | null;
  change_request_number: number | null;
  change_request_url: string | null;
  reviewer_provider: "gitlab" | "github";
  reviewer_provider_user_id: string;
  reviewer_provider_username: string;
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
  gates: GateInstance[];
  gate_decisions: GateDecision[];
};

export type ProjectAccess = { permissions: string[]; is_system_admin: boolean };

export type ProjectRole = {
  id: string; project_id: string; key: string; name: string; description: string;
  is_builtin: boolean; permissions: string[];
};

export type ProjectMembership = {
  id: string; project_id: string; user_id: string; display_name: string; email: string;
  is_active: boolean; role_keys: string[];
};

export type ApprovalRequirement = {
  key: string; name: string; quorum: number; role_keys: string[]; user_ids: string[];
  include_triggering_user: boolean;
};

export type ApprovalPolicy = {
  id: string; project_id: string; key: string; name: string; description: string; enabled: boolean;
  initiator_may_approve: boolean; distinct_approvers_across_requirements: boolean;
  eligible_approvers_may_give_feedback: boolean; requirements: ApprovalRequirement[];
};

export type GateInstance = {
  id: string; run_id: string; invocation_id: string; node_execution_id: string; iteration: number;
  checkpoint_commit_sha: string; policy_key: string; status: string; opened_at: string;
  resolved_at: string | null;
  policy_snapshot: {
    name: string; distinct_approvers_across_requirements: boolean;
    requirements: Array<{ key: string; name: string; quorum: number }>;
  };
  eligible_snapshot: {
    requirements: Array<{ key: string; name: string; quorum: number; users: Array<{
      user_id: string; provider: string; provider_user_id: string; provider_username: string;
      display_name: string; email: string;
    }> }>;
  };
};

export type GateDecision = {
  id: string; gate_instance_id: string; event_type: string; source: string;
  actor_user_id: string | null; actor_snapshot: Record<string, string>;
  requirement_keys: string[]; message: string; superseded: boolean; created_at: string;
};

export type RunReport = {
  schema_version: number; frozen: boolean; generated_at: string;
  run: Record<string, unknown> & { id: string; status: string; root_workflow_id: string; project_name: string };
  invocations: Array<Record<string, unknown>>;
  gates: Array<GateInstance & { workflow_id: string; invocation_path: string; node_id: string; node_path: string; decisions: GateDecision[] }>;
  audit_events: Array<Record<string, unknown>>;
  post_run_lifecycle: Array<Record<string, unknown>>;
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
