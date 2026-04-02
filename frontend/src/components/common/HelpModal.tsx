import { useCallback, useEffect, useRef } from "react";
import { Icon } from "./Icon";

interface HelpModalProps {
  open: boolean;
  onClose: () => void;
}

const SHORTCUTS = [
  { keys: "Enter", description: "Send message" },
  { keys: "Shift + Enter", description: "New line" },
];

const FEATURES = [
  { icon: "chat_bubble", title: "Chat", description: "Ask anything about your 2nd Brain knowledge graph." },
  { icon: "search", title: "Search", description: "Switch to search mode to find notes in your vault." },
  { icon: "hub", title: "Knowledge Graph", description: "Explore connections between notes visually." },
  { icon: "extension", title: "Plugins", description: "Manage input, process, and output plugins." },
  { icon: "folder_open", title: "Vault Browser", description: "Browse and read files in your vault." },
];

export function HelpModal({ open, onClose }: HelpModalProps) {
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

  return (
    <div
      ref={overlayRef}
      role="dialog"
      aria-label="Help"
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
            <h2 className="text-lg font-headline font-bold text-on-surface">Help</h2>
          </div>
          <button
            onClick={onClose}
            aria-label="Close help"
            className="text-gray-400 hover:text-on-surface p-1 rounded-lg transition-colors"
          >
            <Icon name="close" size={20} />
          </button>
        </div>

        {/* Content */}
        <div className="px-6 py-5 space-y-6 max-h-[70vh] overflow-y-auto scrollbar-thin">
          {/* Features */}
          <section>
            <h3 className="text-xs font-mono uppercase tracking-wider text-gray-400 mb-3">Features</h3>
            <div className="space-y-3">
              {FEATURES.map((f) => (
                <div key={f.title} className="flex items-start gap-3">
                  <div className="w-8 h-8 rounded-lg bg-accent-light/10 flex items-center justify-center shrink-0 mt-0.5">
                    <Icon name={f.icon} size={16} className="text-accent-light" />
                  </div>
                  <div>
                    <p className="text-sm font-medium text-on-surface">{f.title}</p>
                    <p className="text-xs text-on-surface-variant">{f.description}</p>
                  </div>
                </div>
              ))}
            </div>
          </section>

          {/* Keyboard shortcuts */}
          <section>
            <h3 className="text-xs font-mono uppercase tracking-wider text-gray-400 mb-3">Keyboard Shortcuts</h3>
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
            <h3 className="text-xs font-mono uppercase tracking-wider text-gray-400 mb-2">About</h3>
            <p className="text-xs text-on-surface-variant leading-relaxed">
              BSage is your personal AI agent that manages a 2nd Brain (Obsidian Vault).
              It collects data via input Plugins, provides tool functionality via process Plugins/Skills,
              and syncs the Vault to external storage via output Plugins.
            </p>
          </section>
        </div>
      </div>
    </div>
  );
}
