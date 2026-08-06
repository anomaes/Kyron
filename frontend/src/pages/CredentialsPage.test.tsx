import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen } from "@testing-library/react";
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
});
