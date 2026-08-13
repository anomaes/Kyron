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

  it("edits a credential without retrieving or renaming its stored value", async () => {
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
    expect(screen.getByLabelText("Environment key")).toHaveAttribute("readonly");
    expect(screen.getByLabelText("New secret value")).toHaveValue("");
    expect(screen.getByLabelText("Description")).toHaveValue("Old description");

    await userEvent.type(screen.getByLabelText("New secret value"), "replacement-secret");
    await userEvent.clear(screen.getByLabelText("Description"));
    await userEvent.type(screen.getByLabelText("Description"), "Rotated provider key");
    await userEvent.click(screen.getByRole("button", { name: "Encrypt & update" }));

    await waitFor(() => expect(api).toHaveBeenCalledWith("/credentials/credential-id", {
      method: "PUT",
      body: JSON.stringify({ value: "replacement-secret", description: "Rotated provider key" }),
    }));
    await waitFor(() => expect(screen.queryByRole("heading", { name: "Edit credential" })).not.toBeInTheDocument());
  });
});
