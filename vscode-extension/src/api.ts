import { DeviceAuthentication } from "./auth";
import type {
  LogEvent,
  Project,
  ProjectAccess,
  Run,
  RunGraph,
  RunsResponse,
  User,
  WorkflowCatalog,
} from "./types";

type ErrorPayload = {
  detail?: string | Array<{ msg?: string }>;
  error?: string;
  error_description?: string;
};

export type RunSubject =
  | { type: "branch"; ref: string }
  | { type: "change_request"; number: number };

export type TriggerResponse = {
  run_id: string;
  status: string;
  base_commit_sha: string;
  delivery_mode: string;
};

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
  }
}

export class KyronApi {
  constructor(
    readonly serverUrl: string,
    private readonly authentication: DeviceAuthentication,
  ) {}

  me(): Promise<User> {
    return this.request<User>("/auth/me");
  }

  projects(): Promise<Project[]> {
    return this.request<Project[]>("/projects");
  }

  projectAccess(projectId: string): Promise<ProjectAccess> {
    return this.request<ProjectAccess>(`/projects/${encodeURIComponent(projectId)}/access`);
  }

  workflows(projectId: string): Promise<WorkflowCatalog> {
    return this.request<WorkflowCatalog>(`/projects/${encodeURIComponent(projectId)}/workflows`);
  }

  runs(projectId: string): Promise<RunsResponse> {
    const query = new URLSearchParams({ project_id: projectId, page_size: "50" });
    return this.request<RunsResponse>(`/runs?${query.toString()}`);
  }

  run(runId: string): Promise<Run> {
    return this.request<Run>(`/runs/${encodeURIComponent(runId)}`);
  }

  runGraph(runId: string): Promise<RunGraph> {
    return this.request<RunGraph>(`/runs/${encodeURIComponent(runId)}/graph`);
  }

  logs(runId: string): Promise<LogEvent[]> {
    return this.request<LogEvent[]>(`/runs/${encodeURIComponent(runId)}/logs?limit=1000`);
  }

  trigger(
    projectId: string,
    workflowId: string,
    subject: RunSubject,
    inputs: Record<string, string | number | boolean>,
  ): Promise<TriggerResponse> {
    return this.request<TriggerResponse>(
      `/projects/${encodeURIComponent(projectId)}/workflows/${encodeURIComponent(workflowId)}/runs`,
      {
        method: "POST",
        body: JSON.stringify({ subject, inputs, use_local_definitions: false }),
      },
    );
  }

  cancel(runId: string): Promise<Run> {
    return this.request<Run>(`/runs/${encodeURIComponent(runId)}/cancel`, { method: "POST" });
  }

  resume(runId: string): Promise<Run> {
    return this.request<Run>(`/runs/${encodeURIComponent(runId)}/resume`, { method: "POST" });
  }

  private async request<T>(path: string, init: RequestInit = {}, retried = false): Promise<T> {
    const token = retried
      ? await this.authentication.refresh(this.serverUrl)
      : await this.authentication.accessToken(this.serverUrl);
    if (!token) {
      throw new ApiError("Connect VS Code to Kyron first", 401);
    }
    let response: Response;
    try {
      response = await fetch(`${this.serverUrl}/api${path}`, {
        ...init,
        headers: {
          ...(init.body ? { "Content-Type": "application/json" } : {}),
          Authorization: `Bearer ${token}`,
          ...init.headers,
        },
      });
    } catch {
      throw new ApiError("Could not reach the Kyron deployment", 0);
    }
    if (response.status === 401 && !retried) {
      return this.request<T>(path, init, true);
    }
    if (!response.ok) {
      throw new ApiError(await errorMessage(response), response.status);
    }
    if (response.status === 204) {
      return undefined as T;
    }
    return (await response.json()) as T;
  }
}

async function errorMessage(response: Response): Promise<string> {
  try {
    const payload = (await response.json()) as ErrorPayload;
    if (typeof payload.detail === "string") {
      return payload.detail;
    }
    if (Array.isArray(payload.detail)) {
      return payload.detail.map((item) => item.msg).filter(Boolean).join("; ");
    }
    return payload.error_description ?? payload.error ?? `Kyron returned HTTP ${response.status}`;
  } catch {
    return `Kyron returned HTTP ${response.status}`;
  }
}

export function normalizeServerUrl(value: string): string {
  const url = new URL(value.trim());
  if (url.protocol !== "https:" && !(url.protocol === "http:" && isLocalHost(url.hostname))) {
    throw new Error("Use HTTPS for Kyron deployments; HTTP is allowed only for local development");
  }
  url.pathname = url.pathname.replace(/\/+$/, "");
  url.search = "";
  url.hash = "";
  return url.toString().replace(/\/$/, "");
}

function isLocalHost(hostname: string): boolean {
  return hostname === "localhost" || hostname === "127.0.0.1" || hostname === "::1";
}
