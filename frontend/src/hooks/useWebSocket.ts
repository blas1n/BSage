import { useCallback, useEffect, useState } from "react";
import type { WSEvent } from "../api/types";
import { type ConnectionState, wsManager } from "../api/websocket";
import { getAccessToken } from "../lib/supabase";

const MAX_EVENTS = 100;

export function useWebSocket() {
  const [connectionState, setConnectionState] = useState<ConnectionState>(wsManager.state);
  const [events, setEvents] = useState<WSEvent[]>([]);

  useEffect(() => {
    const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
    const host = window.location.host;
    const url = `${proto}//${host}/ws`;
    const token = getAccessToken() ?? undefined;
    wsManager.connect(url, token);

    const unsubState = wsManager.onStateChange(setConnectionState);
    const unsubMsg = wsManager.subscribe((msg) => {
      if (msg.type === "event") {
        setEvents((prev) => [msg as WSEvent, ...prev].slice(0, MAX_EVENTS));
      }
    });

    return () => {
      unsubState();
      unsubMsg();
    };
  }, []);

  const clearEvents = useCallback(() => setEvents([]), []);

  return { connectionState, events, clearEvents };
}
