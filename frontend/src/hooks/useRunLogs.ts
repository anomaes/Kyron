import { useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import type { LogEvent } from "../types";

export type RunLogConnectionState = "connecting" | "live" | "retrying" | "complete";

export function useRunLogs(runId: string, terminal: boolean) {
  const [events, setEvents] = useState<LogEvent[]>([]);
  const [connectionState, setConnectionState] = useState<RunLogConnectionState>("connecting");
  const lastSequence = useRef(0);
  const activeRun = useRef("");
  useEffect(() => {
    let socket: WebSocket | null = null;
    let cancelled = false;
    let retry = 500;
    let reconnectTimer: number | undefined;
    let pollTimer: number | undefined;
    if (activeRun.current !== runId) {
      activeRun.current = runId;
      lastSequence.current = 0;
      setEvents([]);
    }

    function append(incoming: LogEvent[]) {
      for (const event of incoming) {
        if (event.sequence) lastSequence.current = Math.max(lastSequence.current, event.sequence);
      }
      setEvents((current) => {
        const eventKey = (event: LogEvent) => {
          if (event.sequence) return `log:${event.sequence}`;
          if (event.type === "pi_event" && event.attempt_id && event.event) {
            return `pi:${event.attempt_id}:${event.event.event_index}`;
          }
          return null;
        };
        const knownKeys = new Set(current.flatMap((event) => {
          const key = eventKey(event);
          return key ? [key] : [];
        }));
        const fresh = incoming.filter((event) => {
          const key = eventKey(event);
          if (!key || !knownKeys.has(key)) {
            if (key) knownKeys.add(key);
            return true;
          }
          return false;
        });
        return fresh.length ? [...current, ...fresh].slice(-2000) : current;
      });
    }

    async function backfill() {
      try {
        const historical = await api<LogEvent[]>(`/runs/${runId}/logs?after_id=${lastSequence.current}&limit=5000`);
        if (!cancelled) append(historical);
      } catch {
        // The WebSocket remains the primary live path. A later poll retries the backfill.
      }
    }

    function connect() {
      if (cancelled || terminal) return;
      setConnectionState("connecting");
      const protocol = location.protocol === "https:" ? "wss" : "ws";
      socket = new WebSocket(`${protocol}://${location.host}/api/ws/runs/${runId}/logs?after_id=${lastSequence.current}`);
      socket.onmessage = (message) => {
        const event = JSON.parse(message.data) as LogEvent;
        if (event.type !== "heartbeat") append([event]);
      };
      socket.onopen = () => { retry = 500; setConnectionState("live"); };
      socket.onclose = () => {
        if (!cancelled && !terminal) {
          setConnectionState("retrying");
          reconnectTimer = window.setTimeout(connect, retry);
          retry = Math.min(retry * 2, 10000);
        }
      };
    }

    void backfill();
    if (terminal) {
      setConnectionState("complete");
    } else {
      connect();
      pollTimer = window.setInterval(() => { void backfill(); }, 3000);
    }
    return () => {
      cancelled = true;
      if (reconnectTimer !== undefined) window.clearTimeout(reconnectTimer);
      if (pollTimer !== undefined) window.clearInterval(pollTimer);
      socket?.close();
    };
  }, [runId, terminal]);
  return { events, connectionState };
}
