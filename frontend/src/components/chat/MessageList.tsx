import { useEffect, useRef } from "react";
import type { ChatMessage } from "../../api/types";
import { Icon } from "../common/Icon";
import { MessageBubble } from "./MessageBubble";
import { TypingIndicator } from "./TypingIndicator";

interface MessageListProps {
  messages: ChatMessage[];
  isLoading: boolean;
}

export function MessageList({ messages, isLoading }: MessageListProps) {
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, isLoading]);

  if (messages.length === 0 && !isLoading) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <div className="text-center">
          <div className="w-12 h-12 rounded-xl bg-accent-light/10 flex items-center justify-center mx-auto mb-4">
            <Icon name="hub" className="text-accent-light" size={24} filled />
          </div>
          <p className="text-lg font-headline font-bold text-on-surface mb-1">Start a conversation</p>
          <p className="text-sm text-on-surface-variant">Ask anything about your 2nd Brain</p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex-1 overflow-y-auto p-8 space-y-8 scrollbar-thin">
      {messages.map((msg, i) => (
        <MessageBubble key={`${msg.role}-${i}`} message={msg} />
      ))}
      {isLoading && <TypingIndicator />}
      <div ref={bottomRef} />
    </div>
  );
}
