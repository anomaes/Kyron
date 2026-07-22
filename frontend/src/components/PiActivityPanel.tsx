import { useEffect, useLayoutEffect, useMemo, useRef, useState, type UIEvent } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import type { LogEvent, PiActivityEvent, PiEventsResponse, RunGraph } from "../types";
import type { RunLogConnectionState } from "../hooks/useRunLogs";
import { StatusBadge } from "./StatusBadge";

type PiNodeSelection = {
  executionId: string;
  label: string;
  nodePath: string;
  status: string;
  currentAttempt: number;
};

type AssistantItem = {
  kind: "assistant";
  key: string;
  text: string;
  thinking: string;
  error?: string | null;
  usage?: unknown;
  open: boolean;
};

type ToolItem = {
  kind: "tool";
  key: string;
  callId: string;
  name: string;
  args?: unknown;
  partialResult?: unknown;
  result?: unknown;
  state: "running" | "success" | "error";
};

type SystemItem = {
  kind: "system";
  key: string;
  message: string;
  error: boolean;
};

type TranscriptItem = AssistantItem | ToolItem | SystemItem;

function record(value: unknown): Record<string, unknown> | undefined {
  return value && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : undefined;
}

function printable(value: unknown): string {
  if (typeof value === "string") return value;
  if (value === undefined) return "No output was reported.";
  try {
    return JSON.stringify(value, null, 2) ?? String(value);
  } catch {
    return String(value);
  }
}

function abbreviated(value: unknown, maximum = 110): string {
  const text = printable(value).replaceAll("\n", " ").replace(/\s+/g, " ").trim();
  return text.length > maximum ? `${text.slice(0, maximum)}…` : text;
}

function toolSummary(name: string, args: unknown): string {
  const values = record(args);
  if (!values) return abbreviated(args);
  const candidates = name === "bash"
    ? [values.command]
    : [values.path, values.file_path, values.pattern, values.query, values.command];
  const summary = candidates.find((value) => typeof value === "string");
  return summary ? abbreviated(summary) : abbreviated(args);
}

export function buildPiTranscript(events: PiActivityEvent[]): TranscriptItem[] {
  const items: TranscriptItem[] = [];
  const tools = new Map<string, ToolItem>();

  for (const event of events) {
    if (event.kind === "assistant_delta") {
      let assistant = [...items].reverse().find(
        (item): item is AssistantItem => item.kind === "assistant" && item.open,
      );
      if (!assistant) {
        assistant = {
          kind: "assistant",
          key: `assistant-${event.event_index}`,
          text: "",
          thinking: "",
          open: true,
        };
        items.push(assistant);
      }
      if (event.stream === "thinking") assistant.thinking += event.delta ?? "";
      else assistant.text += event.delta ?? "";
      continue;
    }

    if (event.kind === "assistant_end") {
      let assistant = [...items].reverse().find(
        (item): item is AssistantItem => item.kind === "assistant" && item.open,
      );
      if (!assistant && (event.text || event.thinking || event.error)) {
        assistant = {
          kind: "assistant",
          key: `assistant-${event.event_index}`,
          text: "",
          thinking: "",
          open: true,
        };
        items.push(assistant);
      }
      if (assistant) {
        assistant.text = event.text || assistant.text;
        assistant.thinking = event.thinking || assistant.thinking;
        assistant.error = event.error;
        assistant.usage = event.usage;
        assistant.open = false;
      }
      continue;
    }

    if (["tool_start", "tool_update", "tool_end"].includes(event.kind)) {
      const callId = event.tool_call_id || `tool-${event.event_index}`;
      let tool = tools.get(callId);
      if (!tool) {
        tool = {
          kind: "tool",
          key: `tool-${callId}`,
          callId,
          name: event.tool_name || "tool",
          state: "running",
        };
        tools.set(callId, tool);
        items.push(tool);
      }
      if (event.kind === "tool_start") tool.args = event.args;
      if (event.kind === "tool_update") tool.partialResult = event.partial_result;
      if (event.kind === "tool_end") {
        tool.result = event.result;
        tool.state = event.is_error ? "error" : "success";
      }
      continue;
    }

    if ((event.kind === "lifecycle" || event.kind === "error") && event.message) {
      items.push({
        kind: "system",
        key: `system-${event.event_index}`,
        message: event.message,
        error: event.kind === "error",
      });
    }
  }
  return items;
}

function FormattedText({ text }: { text: string }) {
  const sections = text.split("```");
  return <div className="pi-formatted-text">{sections.map((section, index) => {
    if (index % 2 === 0) return section ? <div key={index}>{section}</div> : null;
    const newline = section.indexOf("\n");
    const language = newline >= 0 ? section.slice(0, newline).trim() : "";
    const code = newline >= 0 ? section.slice(newline + 1) : section;
    return <pre key={index} data-language={language || undefined}><code>{code}</code></pre>;
  })}</div>;
}

function ValueBlock({ label, value }: { label: string; value: unknown }) {
  return <section className="pi-tool-section"><strong>{label}</strong><pre>{printable(value)}</pre></section>;
}

function ToolCard({ item }: { item: ToolItem }) {
  const output = item.state === "running" ? item.partialResult : item.result;
  return <details className={`pi-tool-card ${item.state}`}>
    <summary>
      <span className="pi-tool-chevron">›</span>
      <span className="pi-tool-name">{item.name}</span>
      <code>{toolSummary(item.name, item.args)}</code>
      <span className="pi-tool-state">{item.state === "running" ? "running" : item.state === "error" ? "failed" : "done"}</span>
    </summary>
    <div className="pi-tool-detail">
      <ValueBlock label="Input" value={item.args} />
      <ValueBlock label={item.state === "running" ? "Current output" : "Output"} value={output} />
    </div>
  </details>;
}

function Transcript({ events }: { events: PiActivityEvent[] }) {
  const items = useMemo(() => buildPiTranscript(events), [events]);
  return <>{items.map((item) => {
    if (item.kind === "tool") return <ToolCard key={item.key} item={item} />;
    if (item.kind === "system") return <div key={item.key} className={`pi-system-event ${item.error ? "error" : ""}`}><span>{item.error ? "!" : "·"}</span>{item.message}</div>;
    return <article key={item.key} className={`pi-assistant-message ${item.error ? "failed" : ""}`}>
      <header><span className="pi-mark">π</span><strong>Pi</strong>{item.open && <span className="pi-streaming">streaming</span>}</header>
      {item.thinking && <details className="pi-thinking"><summary>Reasoning</summary><FormattedText text={item.thinking} /></details>}
      {item.text && <FormattedText text={item.text} />}
      {item.error && <p className="pi-message-error">{item.error}</p>}
      {item.usage !== undefined && item.usage !== null && <details className="pi-usage"><summary>Usage</summary><pre>{printable(item.usage)}</pre></details>}
    </article>;
  })}</>;
}

export function PiActivityPanel({
  runId,
  node,
  attempts,
  liveEvents,
  connectionState,
  fullscreen,
  onShowRunLog,
  onToggleFullscreen,
}: {
  runId: string;
  node: PiNodeSelection;
  attempts: RunGraph["attempts"];
  liveEvents: LogEvent[];
  connectionState: RunLogConnectionState;
  fullscreen: boolean;
  onShowRunLog: () => void;
  onToggleFullscreen: () => void;
}) {
  const nodeAttempts = useMemo(
    () => attempts.filter((attempt) => attempt.node_execution_id === node.executionId)
      .sort((left, right) => left.attempt_number - right.attempt_number),
    [attempts, node.executionId],
  );
  const [selectedAttempt, setSelectedAttempt] = useState(node.currentAttempt);
  const [following, setFollowing] = useState(true);
  const activityRef = useRef<HTMLDivElement>(null);
  const followRef = useRef(true);

  useEffect(() => {
    setSelectedAttempt(node.currentAttempt);
  }, [node.executionId, node.currentAttempt]);

  const history = useQuery({
    queryKey: ["pi-events", runId, node.executionId, selectedAttempt],
    queryFn: () => api<PiEventsResponse>(`/runs/${runId}/nodes/${node.executionId}/pi-events?attempt=${selectedAttempt}`),
    refetchInterval: (query) => query.state.data?.status === "RUNNING" ? 3000 : false,
  });
  const events = useMemo(() => {
    const merged = new Map<number, PiActivityEvent>();
    for (const event of history.data?.events ?? []) merged.set(event.event_index, event);
    for (const envelope of liveEvents) {
      if (
        envelope.type === "pi_event" &&
        envelope.node_execution_id === node.executionId &&
        envelope.attempt_number === selectedAttempt &&
        envelope.event
      ) merged.set(envelope.event.event_index, envelope.event);
    }
    return [...merged.values()].sort((left, right) => left.event_index - right.event_index);
  }, [history.data?.events, liveEvents, node.executionId, selectedAttempt]);

  useLayoutEffect(() => {
    if (!followRef.current || !activityRef.current) return;
    activityRef.current.scrollTop = activityRef.current.scrollHeight;
  }, [events, fullscreen]);

  function handleScroll(event: UIEvent<HTMLDivElement>) {
    const element = event.currentTarget;
    const atBottom = element.scrollHeight - element.scrollTop - element.clientHeight <= 32;
    followRef.current = atBottom;
    setFollowing(atBottom);
  }

  function jumpToLatest() {
    followRef.current = true;
    setFollowing(true);
    activityRef.current?.scrollTo({ top: activityRef.current.scrollHeight, behavior: "smooth" });
  }

  const attemptStatus = history.data?.status ?? nodeAttempts.find((attempt) => attempt.attempt_number === selectedAttempt)?.status ?? node.status;
  const liveState = attemptStatus === "RUNNING" ? connectionState : "complete";
  return <div className={`panel log-panel pi-activity-panel ${fullscreen ? "panel-fullscreen" : ""}`}>
    <div className="panel-title">
      <div className="activity-tabs">
        <button type="button" onClick={onShowRunLog}>Run log</button>
        <button type="button" className="active">Pi activity</button>
      </div>
      <div className="panel-title-actions">
        {nodeAttempts.length > 1 && <select aria-label="Pi attempt" value={selectedAttempt} onChange={(event) => setSelectedAttempt(Number(event.target.value))}>{nodeAttempts.map((attempt) => <option key={attempt.id} value={attempt.attempt_number}>Attempt {attempt.attempt_number}</option>)}</select>}
        <span className={`live-dot ${liveState}`}>{liveState}</span>
        {!following && events.length > 0 && <button type="button" className="log-latest-button" onClick={jumpToLatest}>Latest ↓</button>}
        <button type="button" className="panel-expand-button" aria-label={fullscreen ? "Exit Pi activity fullscreen" : "Show Pi activity fullscreen"} title={fullscreen ? "Exit fullscreen (Esc)" : "Fullscreen"} onClick={onToggleFullscreen}>{fullscreen ? "Close" : "Fullscreen"}</button>
      </div>
    </div>
    <div className="pi-node-context"><div><span>Prompt node</span><strong>{node.label}</strong><code>{node.nodePath}</code></div><StatusBadge status={attemptStatus} /></div>
    <div className="pi-activity" ref={activityRef} onScroll={handleScroll}>
      {history.isError && events.length === 0 && <div className="pi-activity-empty error">Could not load this Pi attempt.</div>}
      {!history.isError && events.length === 0 && <div className="pi-activity-empty">{attemptStatus === "RUNNING" ? "Waiting for Pi output…" : "No Pi activity was recorded for this attempt."}</div>}
      <Transcript events={events} />
    </div>
  </div>;
}

export type { PiNodeSelection };
