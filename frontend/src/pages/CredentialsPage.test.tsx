import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../api/client";
import { CredentialsPage } from "./CredentialsPage";

vi.mock("../api/client", () => ({
  api: vi.fn(),
  json: (method: string, body: unknown) => ({ method, body: JSON.stringify(body) }),
}));

describe("CredentialsPage", () => {
  afterEach(cleanup);

  beforeEach(() => {
    vi.mocked(api).mockReset();
    vi.mocked(api).mockImplementation(async (_path, init) => {
      if (init?.method === "POST") {
        throw new Error('A credential named "SDC_LLM_GATEWAY_TOKEN" already exists');
      }
      return [];
    });
  });

  it("keeps the editor open and surfaces duplicate credential errors", async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<QueryClientProvider client={client}><CredentialsPage /></QueryClientProvider>);

    await userEvent.click(screen.getByRole("button", { name: "Add credential" }));
    await userEvent.type(screen.getByLabelText("Environment key"), "SDC_LLM_GATEWAY_TOKEN");
    await userEvent.type(screen.getByLabelText("Secret value"), "secret-value");
    await userEvent.click(screen.getByRole("button", { name: "Encrypt & save" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      'A credential named "SDC_LLM_GATEWAY_TOKEN" already exists',
    );
    expect(screen.getByRole("heading", { name: "Add credential" })).toBeInTheDocument();
  });

  it("edits credential metadata without retrieving or replacing its stored value", async () => {
    const credential = {
      id: "credential-id",
      key_name: "ANTHROPIC_API_KEY",
      description: "Old description",
      created_at: "2026-08-12T10:00:00Z",
      updated_at: "2026-08-12T10:00:00Z",
      configured: true,
    };
    vi.mocked(api).mockImplementation(async (_path, init) => {
      if (init?.method === "PUT") return credential;
      return [credential];
    });
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<QueryClientProvider client={client}><CredentialsPage /></QueryClientProvider>);

    await userEvent.click(await screen.findByRole("button", { name: "Edit" }));

    expect(screen.getByRole("heading", { name: "Edit credential" })).toBeInTheDocument();
    expect(screen.getByLabelText("Environment key")).toHaveValue("ANTHROPIC_API_KEY");
    expect(screen.getByLabelText("New secret value (optional)")).toHaveValue("");
    expect(screen.getByLabelText("New secret value (optional)")).toHaveAttribute("placeholder", "••••••••");
    expect(screen.getByLabelText("Description")).toHaveValue("Old description");

    await userEvent.clear(screen.getByLabelText("Environment key"));
    await userEvent.type(screen.getByLabelText("Environment key"), "CLAUDE_API_KEY");
    await userEvent.clear(screen.getByLabelText("Description"));
    await userEvent.type(screen.getByLabelText("Description"), "Rotated provider key");
    await userEvent.click(screen.getByRole("button", { name: "Save changes" }));

    await waitFor(() => expect(api).toHaveBeenCalledWith("/credentials/credential-id", {
      method: "PUT",
      body: JSON.stringify({ key_name: "CLAUDE_API_KEY", description: "Rotated provider key" }),
    }));
    await waitFor(() => expect(screen.queryByRole("heading", { name: "Edit credential" })).not.toBeInTheDocument());
  });

  it("replaces the secret when a new value is entered while editing", async () => {
    const credential = {
      id: "credential-id",
      key_name: "ANTHROPIC_API_KEY",
      description: null,
      created_at: "2026-08-12T10:00:00Z",
      updated_at: "2026-08-12T10:00:00Z",
      configured: true,
    };
    vi.mocked(api).mockImplementation(async (_path, init) => init?.method === "PUT" ? credential : [credential]);
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<QueryClientProvider client={client}><CredentialsPage /></QueryClientProvider>);

    await userEvent.click(await screen.findByRole("button", { name: "Edit" }));
    await userEvent.type(screen.getByLabelText("New secret value (optional)"), "replacement-secret");
    await userEvent.click(screen.getByRole("button", { name: "Save changes" }));

    await waitFor(() => expect(api).toHaveBeenCalledWith("/credentials/credential-id", {
      method: "PUT",
      body: JSON.stringify({
        key_name: "ANTHROPIC_API_KEY",
        description: null,
        value: "replacement-secret",
      }),
    }));
  });
});
