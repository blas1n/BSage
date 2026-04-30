import { useCallback, useRef, useState, type KeyboardEvent } from "react";
import { useTranslation } from "react-i18next";
import type { InputMode } from "../../hooks/useChat";
import { Icon } from "../common/Icon";

interface ChatInputProps {
  onSend: (message: string) => void;
  disabled: boolean;
  mode: InputMode;
  onModeChange: (mode: InputMode) => void;
}

export function ChatInput({ onSend, disabled, mode, onModeChange }: ChatInputProps) {
  const { t } = useTranslation();
  const [value, setValue] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const handleSend = useCallback(() => {
    const trimmed = value.trim();
    if (!trimmed || disabled) return;
    onSend(trimmed);
    setValue("");
    if (textareaRef.current) {
      textareaRef.current.style.height = "auto";
    }
  }, [value, disabled, onSend]);

  const handleKeyDown = useCallback(
    (e: KeyboardEvent<HTMLTextAreaElement>) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        handleSend();
      }
    },
    [handleSend],
  );

  const handleInput = () => {
    const el = textareaRef.current;
    if (el) {
      el.style.height = "auto";
      el.style.height = `${Math.min(el.scrollHeight, 200)}px`;
    }
  };

  const placeholder =
    mode === "search"
      ? t("chat.placeholderSearch")
      : t("chat.placeholderChat");

  return (
    <div className="w-full max-w-4xl mx-auto px-6 pb-6 shrink-0">
      <div className="glass-panel border border-outline-variant/30 rounded-xl p-2 shadow-2xl">
        {/* Top toolbar */}
        <div className="flex items-center gap-2 px-3 pb-2 mb-2 border-b border-white/5">
          <div className="flex bg-surface-dim p-1 rounded-md border border-outline-variant/10">
            <button
              onClick={() => onModeChange("chat")}
              aria-pressed={mode === "chat"}
              className={`min-h-10 px-3 py-1 text-[10px] font-bold tracking-tighter rounded ${
                mode === "chat"
                  ? "bg-accent text-gray-950"
                  : "text-gray-400 hover:text-on-surface"
              }`}
            >
              {t("chat.modeChat")}
            </button>
            <button
              onClick={() => onModeChange("search")}
              aria-pressed={mode === "search"}
              className={`min-h-10 px-3 py-1 text-[10px] font-bold tracking-tighter rounded ${
                mode === "search"
                  ? "bg-accent text-gray-950"
                  : "text-gray-400 hover:text-on-surface"
              }`}
            >
              {t("chat.modeSearch")}
            </button>
          </div>
          <div className="h-4 w-px bg-white/10 mx-1" />
          <div className="flex gap-2">
            <button className="inline-flex min-h-10 min-w-10 items-center justify-center rounded-lg text-gray-400 hover:bg-white/5 hover:text-accent-light transition-colors">
              <Icon name="attach_file" size={20} />
            </button>
          </div>
        </div>

        {/* Input row */}
        <div className="flex items-end gap-3 px-3 py-1">
          <textarea
            ref={textareaRef}
            value={value}
            onChange={(e) => {
              setValue(e.target.value);
              handleInput();
            }}
            onKeyDown={handleKeyDown}
            placeholder={placeholder}
            disabled={disabled}
            rows={1}
            className="min-h-10 flex-1 bg-transparent border-none focus:ring-0 text-sm py-2 resize-none placeholder:text-gray-400 font-sans leading-relaxed text-on-surface disabled:opacity-50"
          />
          <button
            onClick={handleSend}
            disabled={disabled || !value.trim()}
            aria-label={t("chat.send")}
            className="mb-1 flex min-h-10 min-w-10 items-center justify-center bg-accent-light text-gray-950 rounded-lg transition-all hover:scale-105 active:scale-95 shadow-lg shadow-accent-light/20 disabled:opacity-40 disabled:cursor-not-allowed"
          >
            <Icon name={mode === "search" ? "search" : "arrow_forward"} size={20} />
          </button>
        </div>
      </div>
      <div className="mt-3 flex justify-center">
        <p className="text-[10px] text-gray-400/50 uppercase tracking-[0.2em] font-mono">{t("chat.encryptionNotice")}</p>
      </div>
    </div>
  );
}
