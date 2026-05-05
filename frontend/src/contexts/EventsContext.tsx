import { createContext, useContext, type ReactNode } from "react";
import type { WSEvent } from "../api/types";

/** Live WebSocket event stream, shared across the app.
 *
 * App.tsx owns the EventBus → WebSocket subscription via ``useWebSocket`` and
 * publishes the events array here. EventPanel still renders the flat list;
 * other consumers (ImportProgressBar, future progress surfaces) derive
 * state from the same source without re-opening another WS connection.
 */
const EventsContext = createContext<WSEvent[] | null>(null);

export interface EventsProviderProps {
  events: WSEvent[];
  children: ReactNode;
}

export function EventsProvider({ events, children }: EventsProviderProps) {
  return <EventsContext.Provider value={events}>{children}</EventsContext.Provider>;
}

/** Subscribe to the live WSEvent stream. Returns ``[]`` outside a provider so
 * components don't have to special-case storybook / test rendering. */
export function useEvents(): WSEvent[] {
  return useContext(EventsContext) ?? [];
}
