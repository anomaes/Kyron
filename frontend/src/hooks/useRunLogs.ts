import { useEffect, useRef, useState } from "react";
import type { LogEvent } from "../types";

export function useRunLogs(runId: string, terminal: boolean) {
  const [events, setEvents] = useState<LogEvent[]>([]);
  const lastSequence = useRef(0);
  useEffect(() => {
    let socket: WebSocket | null = null; let cancelled = false; let retry = 500;
    function connect() {
      if (cancelled || terminal) return;
      const protocol = location.protocol === "https:" ? "wss" : "ws";
      socket = new WebSocket(`${protocol}://${location.host}/api/ws/runs/${runId}/logs?after_id=${lastSequence.current}`);
      socket.onmessage = (message) => {
        const event = JSON.parse(message.data) as LogEvent;
        if (event.sequence) lastSequence.current = Math.max(lastSequence.current, event.sequence);
        if (event.type !== "heartbeat") setEvents((current) => [...current.slice(-1999), event]);
      };
      socket.onopen = () => { retry = 500; };
      socket.onclose = () => { if (!cancelled && !terminal) { setTimeout(connect, retry); retry = Math.min(retry * 2, 10000); } };
    }
    connect(); return () => { cancelled = true; socket?.close(); };
  }, [runId, terminal]);
  return events;
}
