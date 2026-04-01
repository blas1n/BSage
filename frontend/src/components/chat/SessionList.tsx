import type { ChatSession } from "../../hooks/useChat";
import { Icon } from "../common/Icon";

interface SessionListProps {
  sessions: ChatSession[];
  activeSessionId: string | null;
  onSelect: (id: string) => void;
  onDelete: (id: string) => void;
  onNewSession: () => void;
}

function formatDate(ts: number): string {
  const d = new Date(ts);
  const now = new Date();
  const diffMs = now.getTime() - d.getTime();
  const diffMins = Math.floor(diffMs / 60000);
  const diffHours = Math.floor(diffMs / 3600000);
  const diffDays = Math.floor(diffMs / 86400000);

  if (diffMins < 1) return "Just now";
  if (diffMins < 60) return `${diffMins}m ago`;
  if (diffHours < 24) return `${diffHours}h ago`;
  if (diffDays < 7) return `${diffDays}d ago`;
  return d.toLocaleDateString();
}

export function SessionList({ sessions, activeSessionId, onSelect, onDelete, onNewSession }: SessionListProps) {
  return (
    <div className="flex flex-col h-full" data-testid="session-list">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-white/5">
        <span className="text-xs font-mono uppercase tracking-wider text-gray-400">Sessions</span>
        <button
          onClick={onNewSession}
          aria-label="New session"
          className="p-1 text-gray-400 hover:text-accent-light transition-colors rounded"
        >
          <Icon name="add" size={18} />
        </button>
      </div>

      {/* Session items */}
      <div className="flex-1 overflow-y-auto scrollbar-thin py-1">
        {sessions.length === 0 && (
          <div className="px-4 py-8 text-center">
            <p className="text-xs text-gray-500">No sessions yet</p>
            <p className="text-[10px] text-gray-600 mt-1">Start a conversation to create one</p>
          </div>
        )}
        {sessions.map((session) => {
          const isActive = session.id === activeSessionId;
          return (
            <button
              key={session.id}
              onClick={() => onSelect(session.id)}
              data-testid={`session-item-${session.id}`}
              className={`w-full text-left px-4 py-2.5 flex items-start gap-2 transition-all group ${
                isActive
                  ? "bg-accent-light/10 border-l-2 border-accent-light"
                  : "hover:bg-white/5 border-l-2 border-transparent"
              }`}
            >
              <div className="flex-1 min-w-0">
                <p
                  className={`text-xs font-medium truncate ${
                    isActive ? "text-accent-light" : "text-on-surface"
                  }`}
                >
                  {session.title}
                </p>
                <p className="text-[10px] text-gray-500 mt-0.5">
                  {session.messages.length} message{session.messages.length !== 1 ? "s" : ""} &middot; {formatDate(session.updatedAt)}
                </p>
              </div>
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  onDelete(session.id);
                }}
                aria-label={`Delete session ${session.title}`}
                className="p-0.5 text-gray-600 hover:text-red-400 opacity-0 group-hover:opacity-100 transition-all shrink-0 mt-0.5"
              >
                <Icon name="close" size={14} />
              </button>
            </button>
          );
        })}
      </div>
    </div>
  );
}
