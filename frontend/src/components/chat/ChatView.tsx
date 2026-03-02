import { Trash2 } from "lucide-react";
import { useChat } from "../../hooks/useChat";
import { ChatInput } from "./ChatInput";
import { MessageList } from "./MessageList";

export function ChatView() {
  const { messages, isLoading, send, clear } = useChat();

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center justify-between px-4 py-2 border-b border-gray-100 dark:border-gray-700/50">
        <h2 className="text-sm font-medium text-gray-500 dark:text-gray-400">Chat</h2>
        {messages.length > 0 && (
          <button
            onClick={clear}
            className="flex items-center gap-1 text-xs text-gray-400 hover:text-red-500 dark:hover:text-red-400 transition-colors"
          >
            <Trash2 className="w-3 h-3" />
            Clear
          </button>
        )}
      </div>
      <MessageList messages={messages} isLoading={isLoading} />
      <ChatInput onSend={send} disabled={isLoading} />
    </div>
  );
}
