import { useCallback, useEffect, useState } from "react";
import type { WSEvent } from "../api/types";
import { type ConnectionState, wsManager } from "../api/websocket";
import { getAccessToken } from "./useAuth";

const MAX_EVENTS = 100;

export function useWebSocket({ enabled = true }: { enabled?: boolean } = {}) {
  const [connectionState, setConnectionState] = useState<ConnectionState>(wsManager.state);
  const [events, setEvents] = useState<WSEvent[]>([]);

  useEffect(() => {
    if (!enabled) return;

    (async () => {
      const envWsUrl =
        process.env.NEXT_PUBLIC_WS_URL || process.env.VITE_WS_URL;
      const url = envWsUrl
        ? envWsUrl
        : `${window.location.protocol === "https:" ? "wss:" : "ws:"}//${window.location.host}/ws`;
      const token = (await getAccessToken()) ?? undefined;
      wsManager.connect(url, token);
    })();

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
  }, [enabled]);

  const clearEvents = useCallback(() => setEvents([]), []);

  return { connectionState, events, clearEvents };
}
