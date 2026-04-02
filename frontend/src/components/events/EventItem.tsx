import type { WSEvent } from "../../api/types";
import { EVENT_COLORS, EVENT_LABELS } from "../../utils/constants";
import { formatTime } from "../../utils/formatters";

interface EventItemProps {
  event: WSEvent;
}

export function EventItem({ event }: EventItemProps) {
  const color = EVENT_COLORS[event.event_type] ?? "bg-gray-600";
  const label = EVENT_LABELS[event.event_type] ?? event.event_type;
  const name = (event.payload.plugin_name ?? event.payload.skill_name ?? event.payload.name ?? "") as string;

  return (
    <div className="flex items-center gap-2 px-3 py-1.5 text-xs hover:bg-gray-800/50">
      <span className={`w-2 h-2 rounded-full shrink-0 ${color}`} />
      <span className="font-medium text-gray-300 w-24 truncate">{label}</span>
      {name && <span className="text-gray-500 truncate">{name}</span>}
      <span className="ml-auto text-gray-600 shrink-0">
        {formatTime(event.timestamp)}
      </span>
    </div>
  );
}
