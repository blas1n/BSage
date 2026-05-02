import { useTranslation } from "react-i18next";
import { useChat } from "../../hooks/useChat";
import { Icon } from "../common/Icon";
import { ChatInput } from "./ChatInput";
import { MessageList } from "./MessageList";
import { MiniGraph } from "./MiniGraph";
import { SessionList } from "./SessionList";

export function ChatView() {
  const { t } = useTranslation();
  const {
    messages,
    isLoading,
    send,
    clear,
    mode,
    setMode,
    sessions,
    activeSessionId,
    createSession,
    switchSession,
    deleteSession,
  } = useChat();

  return (
    <div className="flex h-full">
      {/* Session list sidebar */}
      <div className="w-56 shrink-0 border-r border-white/5 bg-surface-dim hidden md:block">
        <SessionList
          sessions={sessions}
          activeSessionId={activeSessionId}
          onSelect={switchSession}
          onDelete={deleteSession}
          onNewSession={createSession}
        />
      </div>

      {/* Main chat area */}
      <div className="flex-1 flex flex-col min-w-0">
        <div className="flex items-center justify-between px-6 h-12 border-b border-white/5 shrink-0">
          <div className="flex gap-3">
            <span className="inline-flex min-h-10 items-center text-accent-light border-b-2 border-accent-light text-sm font-medium tracking-tight">Chat</span>
            <a href="#/graph" className="inline-flex min-h-10 min-w-10 items-center justify-center text-gray-500 hover:text-gray-300 text-sm tracking-tight transition-colors">Graph</a>
          </div>
          {messages.length > 0 && (
            <button
              onClick={clear}
              className="flex items-center gap-1.5 text-xs text-gray-500 hover:text-red-400 transition-colors"
            >
              <Icon name="delete" size={16} />
              {t("chat.clear")}
            </button>
          )}
        </div>
        <MessageList messages={messages} isLoading={isLoading} />
        <ChatInput onSend={send} disabled={isLoading} mode={mode} onModeChange={setMode} />
      </div>

      {/* Right sidebar: mini graph */}
      <div className="w-64 shrink-0 border-l border-white/5 bg-surface p-3 overflow-y-auto scrollbar-thin hidden lg:block">
        <MiniGraph />
      </div>
    </div>
  );
}
