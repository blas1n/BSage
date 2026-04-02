import { useState } from "react";
import type { WSEvent } from "../../api/types";
import { Icon } from "../common/Icon";
import { EventItem } from "./EventItem";

interface EventPanelProps {
  events: WSEvent[];
  onClear: () => void;
}

export function EventPanel({ events, onClear }: EventPanelProps) {
  const [expanded, setExpanded] = useState(false);

  return (
    <div
      className={`border-t border-white/5 bg-surface transition-all ${
        expanded ? "h-64" : "h-9"
      }`}
    >
      <button
        onClick={() => setExpanded(!expanded)}
        className="flex items-center justify-between w-full px-3 py-1.5 text-xs font-medium text-gray-500 hover:bg-white/5"
      >
        <div className="flex items-center gap-1.5">
          <Icon name="monitor_heart" size={14} />
          Events
          {events.length > 0 && (
            <span className="bg-surface-container-high rounded-full px-1.5 py-0.5 text-[10px]">
              {events.length}
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          {expanded && events.length > 0 && (
            <span
              onClick={(e) => {
                e.stopPropagation();
                onClear();
              }}
              className="hover:text-red-400 cursor-pointer"
            >
              <Icon name="delete" size={14} />
            </span>
          )}
          <Icon name={expanded ? "expand_more" : "expand_less"} size={16} />
        </div>
      </button>
      {expanded && (
        <div className="overflow-y-auto h-[calc(100%-36px)] scrollbar-thin">
          {events.length === 0 ? (
            <p className="text-center text-xs text-gray-500 py-6">No events yet</p>
          ) : (
            events.map((ev, i) => <EventItem key={`${ev.correlation_id}-${i}`} event={ev} />)
          )}
        </div>
      )}
    </div>
  );
}
