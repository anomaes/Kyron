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

  it("validates the visible provider form without a separate apply step", async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<QueryClientProvider client={client}><PiModelsAdminPanel /></QueryClientProvider>);

    await userEvent.click(await screen.findByRole("button", { name: "Configure providers" }));
    await userEvent.type(screen.getByLabelText("Provider ID"), "external-gateway");
    await userEvent.type(screen.getByLabelText("Endpoint URL"), "https://llm.example.com/v1");
    await userEvent.type(screen.getByLabelText(/^Bearer credential/), "BEARER_TOKEN");
    await userEvent.type(screen.getByLabelText(/^x-api-key credential/), "GATEWAY_API_KEY");
    await userEvent.type(screen.getByLabelText(/^Model IDs/), "example-chat-model");
    await userEvent.click(screen.getByRole("button", { name: "Validate" }));

    const editor = screen.getByLabelText("Pi models configuration JSON") as HTMLTextAreaElement;
    await waitFor(() => expect(editor.value).toContain("external-gateway"));
    const document = JSON.parse(editor.value);
    expect(document.providers["external-gateway"]).toMatchObject({
      apiKey: "$BEARER_TOKEN",
      authHeader: true,
      headers: { "x-api-key": "$GATEWAY_API_KEY" },
      models: [{ id: "example-chat-model" }],
    });
    const validationCall = vi.mocked(api).mock.calls.find(([path]) => path === "/admin/pi-models/validate");
    expect(JSON.parse(String(validationCall?.[1]?.body))).toEqual({ document });
  });

  it("saves the visible provider form without replacing the active document", async () => {
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
    await userEvent.click(screen.getByRole("button", { name: "Save & activate" }));

    await waitFor(() => expect(vi.mocked(api).mock.calls.some(([path, init]) => path === "/admin/pi-models" && init?.method === "PUT")).toBe(true));
    const saveCall = vi.mocked(api).mock.calls.find(([path, init]) => path === "/admin/pi-models" && init?.method === "PUT");
    const savedDocument = JSON.parse(String(saveCall?.[1]?.body)).document;
    expect(Object.keys(savedDocument.providers)).toEqual(["existing", "second"]);
    expect(savedDocument.providers.second.models).toEqual([{ id: "second-model" }]);
  });

  it("describes a database-backed configuration in product language", async () => {
    vi.mocked(api).mockResolvedValue({
      ...emptyState,
      source: "database",
      active_revision_id: "revision-1",
      active_version: 1,
      document: { providers: {} },
    });
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<QueryClientProvider client={client}><PiModelsAdminPanel /></QueryClientProvider>);

    expect(await screen.findByRole("heading", { name: "Built-in providers only" })).toBeInTheDocument();
    expect(screen.getByText("Managed in Administration · Version 1")).toBeInTheDocument();
    expect(screen.queryByText("Database revision 1")).not.toBeInTheDocument();
  });
});
