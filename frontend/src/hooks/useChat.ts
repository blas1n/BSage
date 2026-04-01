import { useCallback, useEffect, useState } from "react";
import { api } from "../api/client";
import type { ChatMessage } from "../api/types";

export type InputMode = "chat" | "search";

export interface ChatSession {
  id: string;
  title: string;
  messages: ChatMessage[];
  createdAt: number;
  updatedAt: number;
}

const SESSIONS_STORAGE_KEY = "bsage_chat_sessions";
const ACTIVE_SESSION_KEY = "bsage_active_session";

function generateId(): string {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

function loadSessions(): ChatSession[] {
  try {
    const raw = localStorage.getItem(SESSIONS_STORAGE_KEY);
    if (!raw) return [];
    return JSON.parse(raw) as ChatSession[];
  } catch {
    return [];
  }
}

function saveSessions(sessions: ChatSession[]): void {
  localStorage.setItem(SESSIONS_STORAGE_KEY, JSON.stringify(sessions));
}

function loadActiveSessionId(): string | null {
  return localStorage.getItem(ACTIVE_SESSION_KEY);
}

function saveActiveSessionId(id: string): void {
  localStorage.setItem(ACTIVE_SESSION_KEY, id);
}

function deriveTitle(messages: ChatMessage[]): string {
  const firstUser = messages.find((m) => m.role === "user");
  if (!firstUser) return "New Session";
  const text = firstUser.content.slice(0, 50);
  return text.length < firstUser.content.length ? `${text}...` : text;
}

export function useChat() {
  const [sessions, setSessions] = useState<ChatSession[]>(() => loadSessions());
  const [activeSessionId, setActiveSessionId] = useState<string | null>(() => loadActiveSessionId());
  const [isLoading, setIsLoading] = useState(false);
  const [mode, setMode] = useState<InputMode>("chat");

  // Derive current session
  const activeSession = sessions.find((s) => s.id === activeSessionId) ?? null;
  const messages = activeSession?.messages ?? [];

  // Persist sessions to localStorage
  useEffect(() => {
    saveSessions(sessions);
  }, [sessions]);

  // Persist active session id
  useEffect(() => {
    if (activeSessionId) {
      saveActiveSessionId(activeSessionId);
    }
  }, [activeSessionId]);

  const createSession = useCallback((): string => {
    const newSession: ChatSession = {
      id: generateId(),
      title: "New Session",
      messages: [],
      createdAt: Date.now(),
      updatedAt: Date.now(),
    };
    setSessions((prev) => [newSession, ...prev]);
    setActiveSessionId(newSession.id);
    return newSession.id;
  }, []);

  const switchSession = useCallback((id: string) => {
    setActiveSessionId(id);
  }, []);

  const send = useCallback(
    async (content: string) => {
      let sessionId = activeSessionId;
      if (!sessionId) {
        // Auto-create session on first message
        const newSession: ChatSession = {
          id: generateId(),
          title: "New Session",
          messages: [],
          createdAt: Date.now(),
          updatedAt: Date.now(),
        };
        setSessions((prev) => [newSession, ...prev]);
        setActiveSessionId(newSession.id);
        sessionId = newSession.id;
      }

      const userMsg: ChatMessage = { role: "user", content };

      // Optimistically add user message
      setSessions((prev) =>
        prev.map((s) => {
          if (s.id !== sessionId) return s;
          const updated = [...s.messages, userMsg];
          return {
            ...s,
            messages: updated,
            title: s.messages.length === 0 ? deriveTitle(updated) : s.title,
            updatedAt: Date.now(),
          };
        }),
      );
      setIsLoading(true);

      try {
        // Get current messages for history
        const current = sessions.find((s) => s.id === sessionId);
        const history = [...(current?.messages ?? []), userMsg];

        let response: string;
        if (mode === "search") {
          const results = await api.vaultSearch(content);
          if (results.length === 0) {
            response = "No results found in your vault.";
          } else {
            response = results
              .map((r) => `**${r.path}**\n${r.matches.map((m) => `- Line ${m.line}: ${m.text}`).join("\n")}`)
              .join("\n\n");
          }
        } else {
          const { response: chatResponse } = await api.chat({ message: content, history });
          response = chatResponse;
        }

        const assistantMsg: ChatMessage = { role: "assistant", content: response };
        setSessions((prev) =>
          prev.map((s) => {
            if (s.id !== sessionId) return s;
            return { ...s, messages: [...s.messages, assistantMsg], updatedAt: Date.now() };
          }),
        );
      } catch (err) {
        const errorMsg: ChatMessage = {
          role: "assistant",
          content: `Error: ${err instanceof Error ? err.message : "Unknown error"}`,
        };
        setSessions((prev) =>
          prev.map((s) => {
            if (s.id !== sessionId) return s;
            return { ...s, messages: [...s.messages, errorMsg], updatedAt: Date.now() };
          }),
        );
      } finally {
        setIsLoading(false);
      }
    },
    [activeSessionId, sessions, mode],
  );

  const clear = useCallback(() => {
    if (!activeSessionId) return;
    setSessions((prev) => prev.filter((s) => s.id !== activeSessionId));
    setActiveSessionId(null);
  }, [activeSessionId]);

  const deleteSession = useCallback(
    (id: string) => {
      setSessions((prev) => prev.filter((s) => s.id !== id));
      if (activeSessionId === id) {
        setActiveSessionId(null);
      }
    },
    [activeSessionId],
  );

  return {
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
  };
}
