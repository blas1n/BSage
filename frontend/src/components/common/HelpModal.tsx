import { useCallback, useEffect, useRef } from "react";
import { useTranslation } from "react-i18next";
import { Icon } from "./Icon";

interface HelpModalProps {
  open: boolean;
  onClose: () => void;
}

const FEATURE_KEYS = [
  { key: "chat", icon: "chat_bubble" },
  { key: "search", icon: "search" },
  { key: "graph", icon: "hub" },
  { key: "plugins", icon: "extension" },
  { key: "vault", icon: "folder_open" },
] as const;

export function HelpModal({ open, onClose }: HelpModalProps) {
  const { t } = useTranslation();
  const overlayRef = useRef<HTMLDivElement>(null);

  const handleKeyDown = useCallback(
    (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    },
    [onClose],
  );

  useEffect(() => {
    if (open) {
      document.addEventListener("keydown", handleKeyDown);
      return () => document.removeEventListener("keydown", handleKeyDown);
    }
  }, [open, handleKeyDown]);

  if (!open) return null;

  const SHORTCUTS = [
    { keys: "Enter", description: t("help.shortcutSendMessage") },
    { keys: "Shift + Enter", description: t("help.shortcutNewLine") },
  ];

  return (
    <div
      ref={overlayRef}
      role="dialog"
      aria-label={t("help.title")}
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm"
      onClick={(e) => {
        if (e.target === overlayRef.current) onClose();
      }}
    >
      <div className="bg-surface-container border border-white/10 rounded-xl w-full max-w-lg mx-4 shadow-2xl">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-white/5">
          <div className="flex items-center gap-2">
            <Icon name="help" size={20} className="text-accent-light" />
            <h2 className="text-lg font-headline font-bold text-on-surface">{t("help.title")}</h2>
          </div>
          <button
            onClick={onClose}
            aria-label={t("common.close")}
            className="text-gray-400 hover:text-on-surface p-1 rounded-lg transition-colors"
          >
            <Icon name="close" size={20} />
          </button>
        </div>

        {/* Content */}
        <div className="px-6 py-5 space-y-6 max-h-[70vh] overflow-y-auto scrollbar-thin">
          {/* Features */}
          <section>
            <h3 className="text-xs font-mono uppercase tracking-wider text-gray-400 mb-3">{t("help.features")}</h3>
            <div className="space-y-3">
              {FEATURE_KEYS.map((f) => {
                // Reuse short labels from existing nav/plugin/vault keys for the title
                const titleKey =
                  f.key === "chat"
                    ? "nav.currentChat"
                    : f.key === "search"
                      ? "common.search"
                      : f.key === "graph"
                        ? "nav.knowledgeBase"
                        : f.key === "plugins"
                          ? "plugins.title"
                          : "nav.vaultBrowser";
                return (
                  <div key={f.key} className="flex items-start gap-3">
                    <div className="w-8 h-8 rounded-lg bg-accent-light/10 flex items-center justify-center shrink-0 mt-0.5">
                      <Icon name={f.icon} size={16} className="text-accent-light" />
                    </div>
                    <div>
                      <p className="text-sm font-medium text-on-surface">{t(titleKey)}</p>
                      <p className="text-xs text-on-surface-variant">{t(`help.feature.${f.key}`)}</p>
                    </div>
                  </div>
                );
              })}
            </div>
          </section>

          {/* Keyboard shortcuts */}
          <section>
            <h3 className="text-xs font-mono uppercase tracking-wider text-gray-400 mb-3">{t("help.keyboardShortcuts")}</h3>
            <div className="space-y-2">
              {SHORTCUTS.map((s) => (
                <div key={s.keys} className="flex items-center justify-between">
                  <span className="text-xs text-on-surface-variant">{s.description}</span>
                  <kbd className="text-[10px] font-mono bg-surface-dim px-2 py-1 rounded border border-white/10 text-gray-300">
                    {s.keys}
                  </kbd>
                </div>
              ))}
            </div>
          </section>

          {/* About */}
          <section>
            <h3 className="text-xs font-mono uppercase tracking-wider text-gray-400 mb-2">{t("help.about")}</h3>
            <p className="text-xs text-on-surface-variant leading-relaxed">
              {t("help.aboutBody")}
            </p>
          </section>
        </div>
      </div>
    </div>
  );
}
