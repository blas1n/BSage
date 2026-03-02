import { Activity, ChevronDown, ChevronUp, Trash2 } from "lucide-react";
import { useState } from "react";
import type { WSEvent } from "../../api/types";
import { EventItem } from "./EventItem";

interface EventPanelProps {
  events: WSEvent[];
  onClear: () => void;
}

export function EventPanel({ events, onClear }: EventPanelProps) {
  const [expanded, setExpanded] = useState(false);

  return (
    <div
      className={`border-t border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 transition-all ${
        expanded ? "h-64" : "h-9"
      }`}
    >
      <button
        onClick={() => setExpanded(!expanded)}
        className="flex items-center justify-between w-full px-3 py-1.5 text-xs font-medium text-gray-500 dark:text-gray-400 hover:bg-gray-50 dark:hover:bg-gray-700/50"
      >
        <div className="flex items-center gap-1.5">
          <Activity className="w-3.5 h-3.5" />
          Events
          {events.length > 0 && (
            <span className="bg-gray-200 dark:bg-gray-600 rounded-full px-1.5 py-0.5 text-[10px]">
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
              className="hover:text-red-500 cursor-pointer"
            >
              <Trash2 className="w-3 h-3" />
            </span>
          )}
          {expanded ? <ChevronDown className="w-3.5 h-3.5" /> : <ChevronUp className="w-3.5 h-3.5" />}
        </div>
      </button>
      {expanded && (
        <div className="overflow-y-auto h-[calc(100%-36px)] scrollbar-thin">
          {events.length === 0 ? (
            <p className="text-center text-xs text-gray-400 dark:text-gray-500 py-6">No events yet</p>
          ) : (
            events.map((ev, i) => <EventItem key={`${ev.correlation_id}-${i}`} event={ev} />)
          )}
        </div>
      )}
    </div>
  );
}
