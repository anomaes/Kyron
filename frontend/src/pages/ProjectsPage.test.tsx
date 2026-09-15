import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../api/client";
import type { Project } from "../types";
import { ProjectsPage } from "./ProjectsPage";

vi.mock("../api/client", () => ({
  api: vi.fn(),
  json: (method: string, body: unknown) => ({ method, body: JSON.stringify(body) }),
}));

const project: Project = {
  id: "project-id",
  name: "Widget",
  git_url: "https://github.example/acme/widget.git",
  provider: "github",
  provider_project_id: "42",
  provider_project_path: "acme/widget",
  local_path: "/var/workflowengine/repos/project-id",
  default_branch: "main",
  pi: {},
  added_by: "user-id",
  created_at: "2026-09-15T08:00:00Z",
  updated_at: "2026-09-15T08:00:00Z",
  token_configured: true,
  webhook_secret_configured: true,
  webhook_signing_secret_configured: false,
  can_manage: true,
};

describe("ProjectsPage", () => {
  afterEach(cleanup);

  beforeEach(() => {
    vi.mocked(api).mockReset();
    vi.mocked(api).mockImplementation(async (path, init) => {
      if (path === "/projects/project-id/token" && init?.method === "PUT") return project;
      if (path === "/projects") return [project];
      if (path === "/auth/me") {
        return {
          id: "user-id",
          email: "admin@example.com",
          display_name: "Admin",
          avatar_url: null,
          provider: "github",
          provider_user_id: "7",
          provider_username: "admin",
          is_system_admin: true,
        };
      }
      if (path === "/pi/models/catalog") {
        return { source: "builtin", revision_id: null, version: null, providers: [], required_credentials: [] };
      }
      throw new Error(`Unexpected API call: ${path}`);
    });
  });

  it("replaces a project access token without retrieving the stored value", async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <MemoryRouter>
        <QueryClientProvider client={client}>
          <ProjectsPage />
        </QueryClientProvider>
      </MemoryRouter>,
    );

    await userEvent.click(await screen.findByRole("button", { name: "Access token" }));
    expect(screen.getByLabelText("New project access token")).toHaveValue("");

    await userEvent.type(screen.getByLabelText("New project access token"), "replacement-token");
    await userEvent.click(screen.getByRole("button", { name: "Validate & replace" }));

    await waitFor(() => expect(api).toHaveBeenCalledWith("/projects/project-id/token", {
      method: "PUT",
      body: JSON.stringify({ access_token: "replacement-token" }),
    }));
  });
});
