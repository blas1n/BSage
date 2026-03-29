import { Trash2 } from "lucide-react";
import { useChat } from "../../hooks/useChat";
import { ChatInput } from "./ChatInput";
import { MessageList } from "./MessageList";
import { MiniGraph } from "./MiniGraph";

export function ChatView() {
  const { messages, isLoading, send, clear } = useChat();

  return (
    <div className="flex h-full">
      {/* Main chat area */}
      <div className="flex-1 flex flex-col min-w-0">
        <div className="flex items-center justify-between px-4 py-2 border-b border-gray-800/50">
          <h2 className="text-sm font-medium text-gray-500">Knowledge Chat</h2>
          {messages.length > 0 && (
            <button
              onClick={clear}
              className="flex items-center gap-1 text-xs text-gray-500 hover:text-red-400 transition-colors"
            >
              <Trash2 className="w-3 h-3" />
              Clear
            </button>
          )}
        </div>
        <MessageList messages={messages} isLoading={isLoading} />
        <ChatInput onSend={send} disabled={isLoading} />
      </div>

      {/* Right sidebar: mini graph */}
      <div className="w-64 shrink-0 border-l border-gray-800 bg-gray-900/50 p-3 overflow-y-auto scrollbar-thin hidden lg:block">
        <MiniGraph />
      </div>
    </div>
  );
}
