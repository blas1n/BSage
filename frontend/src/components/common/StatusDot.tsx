import type { ConnectionState } from "../../api/websocket";

const COLORS: Record<ConnectionState, string> = {
  connected: "bg-accent-light shadow-[0_0_8px_rgba(78,222,163,0.5)]",
  disconnected: "bg-gray-500",
  reconnecting: "bg-tertiary animate-pulse",
};

const LABELS: Record<ConnectionState, string> = {
  connected: "Connected",
  disconnected: "Offline",
  reconnecting: "Reconnecting...",
};

interface StatusDotProps {
  state: ConnectionState;
}

export function StatusDot({ state }: StatusDotProps) {
  return (
    <div className="flex items-center gap-1.5">
      <div className={`w-1.5 h-1.5 rounded-full ${COLORS[state]}`} />
      <span className="text-[10px] font-mono text-gray-400 uppercase">{LABELS[state]}</span>
    </div>
  );
}
