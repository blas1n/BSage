import { useCallback, useState } from "react";
import { api } from "../api/client";
import type { ChatMessage } from "../api/types";

export function useChat() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [isLoading, setIsLoading] = useState(false);

  const send = useCallback(
    async (content: string) => {
      const userMsg: ChatMessage = { role: "user", content };
      setMessages((prev) => [...prev, userMsg]);
      setIsLoading(true);

      try {
        const history = [...messages, userMsg];
        const { response } = await api.chat({ message: content, history });
        const assistantMsg: ChatMessage = { role: "assistant", content: response };
        setMessages((prev) => [...prev, assistantMsg]);
      } catch (err) {
        const errorMsg: ChatMessage = {
          role: "assistant",
          content: `Error: ${err instanceof Error ? err.message : "Unknown error"}`,
        };
        setMessages((prev) => [...prev, errorMsg]);
      } finally {
        setIsLoading(false);
      }
    },
    [messages],
  );

  const clear = useCallback(() => {
    setMessages([]);
  }, []);

  return { messages, isLoading, send, clear };
}
