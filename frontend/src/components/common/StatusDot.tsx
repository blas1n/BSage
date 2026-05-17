import { useT } from "@bsvibe/i18n";
import type { ConnectionState } from "../../api/websocket";

const COLORS: Record<ConnectionState, string> = {
  connected: "bg-accent-light shadow-[0_0_8px_rgba(78,222,163,0.5)]",
  disconnected: "bg-gray-500",
  reconnecting: "bg-tertiary animate-pulse",
};

/** Maps connection state to its `status.*` i18n key. The label is
 * translated at the render site (module-level maps cannot call hooks). */
const LABEL_KEYS: Record<ConnectionState, string> = {
  connected: "status.connected",
  disconnected: "status.offline",
  reconnecting: "status.reconnecting",
};

interface StatusDotProps {
  state: ConnectionState;
}

export function StatusDot({ state }: StatusDotProps) {
  const t = useT("sage");
  return (
    <div className="flex items-center gap-1.5">
      <div className={`w-1.5 h-1.5 rounded-full ${COLORS[state]}`} />
      <span className="text-[10px] font-mono text-gray-400 uppercase">{t(LABEL_KEYS[state])}</span>
    </div>
  );
}
