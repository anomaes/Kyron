import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../api/client";
import { PiModelsAdminPanel } from "./PiModelsAdminPanel";

vi.mock("../api/client", () => ({
  api: vi.fn(),
  json: (method: string, body: unknown) => ({ method, body: JSON.stringify(body) }),
}));

const emptyState = {
  source: "builtin",
  revision_id: null,
  version: null,
  active_revision_id: null,
  active_version: null,
  document: null,
  providers: [],
  required_credentials: [],
  file_bootstrap_configured: false,
  configuration_error: null,
  revisions: [],
};

describe("PiModelsAdminPanel", () => {
  afterEach(cleanup);

  beforeEach(() => {
    vi.mocked(api).mockReset();
    vi.mocked(api).mockResolvedValue(emptyState);
  });

  it("builds a provider with bearer and x-api-key credentials", async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<QueryClientProvider client={client}><PiModelsAdminPanel /></QueryClientProvider>);

    await userEvent.click(await screen.findByRole("button", { name: "Configure providers" }));
    await userEvent.type(screen.getByLabelText("Provider ID"), "external-gateway");
    await userEvent.type(screen.getByLabelText("Endpoint URL"), "https://llm.example.com/v1");
    await userEvent.type(screen.getByLabelText(/^Bearer credential/), "BEARER_TOKEN");
    await userEvent.type(screen.getByLabelText(/^x-api-key credential/), "GATEWAY_API_KEY");
    await userEvent.type(screen.getByLabelText(/^Model IDs/), "example-chat-model");
    await userEvent.click(screen.getByRole("button", { name: "Apply to draft" }));

    const editor = screen.getByLabelText("Pi models configuration JSON") as HTMLTextAreaElement;
    await waitFor(() => expect(editor.value).toContain("external-gateway"));
    const document = JSON.parse(editor.value);
    expect(document.providers["external-gateway"]).toMatchObject({
      apiKey: "$BEARER_TOKEN",
      authHeader: true,
      headers: { "x-api-key": "$GATEWAY_API_KEY" },
      models: [{ id: "example-chat-model" }],
    });
  });

  it("adds another provider without replacing the active document", async () => {
    vi.mocked(api).mockResolvedValue({
      ...emptyState,
      source: "database",
      active_revision_id: "revision-1",
      active_version: 1,
      document: {
        providers: {
          existing: {
            baseUrl: "https://existing.example/v1",
            api: "openai-completions",
            models: [{ id: "existing-model" }],
          },
        },
      },
      providers: [{ id: "existing", models: ["existing-model"], required_credentials: [] }],
    });
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<QueryClientProvider client={client}><PiModelsAdminPanel /></QueryClientProvider>);

    await userEvent.click(await screen.findByRole("button", { name: "Configure providers" }));
    expect((screen.getByLabelText("Pi models configuration JSON") as HTMLTextAreaElement).value).toContain("existing-model");
    await userEvent.type(screen.getByLabelText("Provider ID"), "second");
    await userEvent.type(screen.getByLabelText("Endpoint URL"), "https://second.example/v1");
    await userEvent.type(screen.getByLabelText(/^Model IDs/), "second-model");
    await userEvent.click(screen.getByRole("button", { name: "Apply to draft" }));

    const editor = screen.getByLabelText("Pi models configuration JSON") as HTMLTextAreaElement;
    await waitFor(() => expect(editor.value).toContain("second-model"));
    expect(Object.keys(JSON.parse(editor.value).providers)).toEqual(["existing", "second"]);
  });
});
