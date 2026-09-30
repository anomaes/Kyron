import { afterEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { PiActivityEvent, PiEventsResponse } from "../types";
import { buildPiTranscript, PiActivityPanel } from "./PiActivityPanel";

const node = { executionId: "node-1", label: "Prompt", nodePath: "root/prompt", status: "SUCCESS", currentAttempt: 1 };
const delta = (event_index: number, text: string): PiActivityEvent => ({ event_index, pi_event_type: "message_update", kind: "assistant_delta", stream: "text", delta: text });
const page = (events: PiActivityEvent[], next_cursor: string, has_more: boolean, status = "SUCCESS"): PiEventsResponse => ({ attempt: 1, status, models: [], events, next_cursor, has_more });

function mockPages(...pages: PiEventsResponse[]) {
  const fetchMock = vi.fn().mockImplementation(async () => ({
    ok: true,
    status: 200,
    json: async () => pages.shift(),
  }));
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function panel(overrides: Partial<Parameters<typeof PiActivityPanel>[0]> = {}) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}><PiActivityPanel runId="run-1" node={node} attempts={[]} liveEvents={[]} connectionState="complete" fullscreen={false} onShowRunLog={() => {}} onToggleFullscreen={() => {}} {...overrides} /></QueryClientProvider>);
}

afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); });

describe("Pi activity transcript", () => {
  it("keeps usage visible for a tool-only assistant turn", () => {
    const usage = {
      input: 100,
      output: 20,
      cacheRead: 50,
      cacheWrite: 0,
      totalTokens: 170,
    };
    const events: PiActivityEvent[] = [{
      event_index: 4,
      pi_event_type: "message_end",
      kind: "assistant_end",
      text: "",
      thinking: "",
      stop_reason: "toolUse",
      usage,
    }];

    const transcript = buildPiTranscript(events);

    expect(transcript).toHaveLength(1);
    const item = transcript[0];
    expect(item?.kind).toBe("assistant");
    if (!item || item.kind !== "assistant") throw new Error("Expected assistant usage");
    expect(item.usage).toEqual(usage);
    expect(item.open).toBe(false);
  });
});

describe("Pi activity paging", () => {
  it("loads one page initially and exposes older persisted history", async () => {
    const fetchMock = mockPages(
      page([delta(1, "first")], "cursor-1", true),
      page([delta(2, "second")], "cursor-2", false),
      page([delta(1, "first")], "cursor-1", true),
    );
    panel();
    expect(await screen.findByText("first")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole("button", { name: "Next page" }));
    expect(await screen.findByText("second")).toBeInTheDocument();
    expect(screen.queryByText("first")).not.toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(String(fetchMock.mock.calls[1]?.[0])).toContain("cursor=cursor-1");
    fireEvent.click(screen.getByRole("button", { name: "Previous page" }));
    expect(await screen.findByText("first")).toBeInTheDocument();
    expect(screen.queryByText("second")).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Download complete Pi history" })).toBeInTheDocument();
  });

  it("prefers the live event for an already loaded event index", async () => {
    mockPages(page([delta(1, "history")], "cursor", false));
    panel({ liveEvents: [{ type: "pi_event", node_execution_id: "node-1", attempt_number: 1, event: delta(1, "live") }] });
    expect(await screen.findByText("live")).toBeInTheDocument();
    expect(screen.queryByText("history")).not.toBeInTheDocument();
  });

  it("polls only the continuation cursor when the live stream is unavailable", async () => {
    const fetchMock = mockPages(page([delta(1, "first")], "cursor-1", false, "RUNNING"), page([delta(2, "second")], "cursor-2", false, "RUNNING"));
    const timeoutSpy = vi.spyOn(window, "setTimeout");
    panel({ node: { ...node, status: "RUNNING" }, connectionState: "retrying" });
    expect(await screen.findByText("first")).toBeInTheDocument();
    await act(async () => { await Promise.resolve(); });
    const poll = timeoutSpy.mock.calls.find(([, delay]) => delay === 3000)?.[0];
    expect(poll).toBeDefined();
    await act(async () => { if (typeof poll === "function") poll(); });
    expect(await screen.findByText("second")).toBeInTheDocument();
    expect(String(fetchMock.mock.calls[1]?.[0])).toContain("cursor=cursor-1");
  });
});
