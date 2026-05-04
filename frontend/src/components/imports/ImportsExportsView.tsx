"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { api } from "../../api/client";
import type { EntryMeta } from "../../api/types";
import { Icon } from "../common/Icon";
import { PluginUploadModal, type SourceOption } from "../plugins/PluginUploadModal";

/** Detect plugins whose input_schema declares an `upload_id` or `path` field. */
function entryNeedsUpload(entry: EntryMeta): boolean {
  const schema = entry.input_schema;
  if (!schema || typeof schema !== "object") return false;
  const props = (schema as { properties?: Record<string, unknown> }).properties;
  if (!props || typeof props !== "object") return false;
  return "upload_id" in props || "path" in props;
}

/** Default `accept=` hint per known import plugin. */
function entryAcceptHint(name: string): string | undefined {
  if (name === "ai-memory-input") return ".md,.zip";
  if (name.includes("chatgpt")) return ".json";
  if (name.includes("claude-memory")) return ".zip,.json";
  if (name.includes("obsidian")) return ".zip";
  return undefined;
}

/** Static instructions per plugin — where to find the file the user should upload. */
const PLUGIN_INSTRUCTIONS: Record<string, string> = {
  "chatgpt-memory-input":
    "1. Visit chatgpt.com → Settings → Data controls → Export data\n" +
    "2. Wait for the email, download the ZIP\n" +
    "3. Extract → upload conversations.json (or memory.json for saved memories)",
  "claude-memory-input":
    "1. Visit claude.ai → Settings → Account → Export data\n" +
    "2. Wait for the email, download the ZIP\n" +
    "3. Upload the ZIP as-is — we'll find conversations.json inside",
  "obsidian-input":
    "1. Compress your Obsidian vault folder into a ZIP\n" +
    "   (e.g. right-click the vault folder → Compress)\n" +
    "2. Upload the ZIP — we'll walk the *.md files",
  "ai-memory-input":
    "Drop in any markdown memory/context file from your AI tool of choice.\n\n" +
    "Single file or a ZIP of many. Pick the source above so we can tag it.",
};

/** Source picker options for ai-memory-input. */
const AI_MEMORY_SOURCES: SourceOption[] = [
  {
    value: "claude-code",
    label: "Claude Code",
    instructions:
      "Anthropic's CLI agent.\n\n" +
      "Look in: ~/.claude/CLAUDE.md (user-level)\n" +
      "         ~/.claude/projects/<slug>/CLAUDE.md (per-project)\n" +
      "         ~/.claude/projects/<slug>/memory/*.md (topic notes)\n\n" +
      "Easiest: tar/zip the entire ~/.claude folder, upload here.",
  },
  {
    value: "codex",
    label: "Codex CLI",
    instructions:
      "OpenAI's coding agent CLI.\n\n" +
      "Look in: ~/.codex/AGENTS.md or your project's AGENTS.md\n\n" +
      "Upload the .md file directly, or zip multiple together.",
  },
  {
    value: "opencode",
    label: "opencode",
    instructions:
      "Open-source AI coding agent.\n\n" +
      "Look in: ~/.config/opencode/ (or your project's AGENTS.md)\n\n" +
      "Upload the .md file directly, or zip multiple together.",
  },
  {
    value: "cursor",
    label: "Cursor",
    instructions:
      "Cursor IDE rules.\n\n" +
      "Look in: <project>/.cursor/rules/*.mdc\n" +
      "         or <project>/.cursorrules\n\n" +
      "Upload the file directly. (.mdc → rename to .md before upload.)",
  },
  {
    value: "custom",
    label: "Custom",
    instructions:
      "Any markdown file you want to import as a memory/preference note.\n\n" +
      "Title is taken from the first H1 heading, falling back to the filename.",
  },
];

function entrySourceOptions(name: string): SourceOption[] | undefined {
  if (name === "ai-memory-input") return AI_MEMORY_SOURCES;
  return undefined;
}

/** True for one-shot import/export plugins — not the persistent kind. */
function isOneShotIO(entry: EntryMeta): boolean {
  if (entry.entry_type !== "plugin") return false;
  if (entry.category !== "input" && entry.category !== "output") return false;
  return entry.trigger?.type === "on_demand";
}

const SOURCE_ICONS: Record<string, string> = {
  chatgpt: "chat",
  claude: "psychology",
  "claude-code": "terminal",
  obsidian: "book",
};

function entryIcon(name: string): string {
  for (const [k, icon] of Object.entries(SOURCE_ICONS)) {
    if (name.includes(k)) return icon;
  }
  return "swap_horiz";
}

export function ImportsExportsView() {
  const { t } = useTranslation();
  const [entries, setEntries] = useState<EntryMeta[]>([]);
  const [loading, setLoading] = useState(true);
  const [target, setTarget] = useState<EntryMeta | null>(null);
  const [running, setRunning] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    const all = await api.plugins();
    setEntries(all.filter(isOneShotIO));
  }, []);

  useEffect(() => {
    const id = window.setTimeout(() => {
      refresh().finally(() => setLoading(false));
    }, 0);
    return () => window.clearTimeout(id);
  }, [refresh]);

  const { imports, exports } = useMemo(() => {
    return {
      imports: entries.filter((e) => e.category === "input"),
      exports: entries.filter((e) => e.category === "output"),
    };
  }, [entries]);

  const handleClick = useCallback(
    async (entry: EntryMeta) => {
      if (entryNeedsUpload(entry)) {
        setTarget(entry);
        return;
      }
      // Output plugins (obsidian-output) accept input_data without upload —
      // for now we just trigger a body-less run; users wire output_vault_path
      // via credentials. A future iteration could add a path-picker modal.
      setRunning(entry.name);
      try {
        await api.run(entry.name);
      } finally {
        setRunning(null);
      }
    },
    [],
  );

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full text-gray-500">
        {t("common.loading")}
      </div>
    );
  }

  return (
    <div className="h-full overflow-y-auto scrollbar-thin">
      <div className="max-w-5xl mx-auto p-8">
        <header className="mb-10">
          <h1 className="text-4xl font-extrabold tracking-tight mb-2 text-on-surface font-headline">
            Imports & Exports
          </h1>
          <p className="text-on-surface-variant font-medium">
            One-shot data migration. For ongoing integrations (Slack, email,
            calendar polling) see Plugins.
          </p>
        </header>

        <Section
          title="Imports"
          subtitle="Bring data into your vault — ChatGPT/Claude/Obsidian exports, etc."
          entries={imports}
          actionLabel="Import"
          running={running}
          onClick={handleClick}
        />

        <Section
          title="Exports"
          subtitle="Push your vault content out to another tool."
          entries={exports}
          actionLabel="Export"
          running={running}
          onClick={handleClick}
        />

        {entries.length === 0 && (
          <div className="text-center py-16 text-gray-500">
            <Icon name="swap_horiz" className="mx-auto mb-3 opacity-40" size={32} />
            <p className="text-sm">No import/export plugins installed.</p>
          </div>
        )}
      </div>

      {target && (
        <PluginUploadModal
          pluginName={target.name}
          title={`${target.category === "output" ? "Export via" : "Import via"} ${target.name}`}
          subtitle={target.description}
          accept={entryAcceptHint(target.name)}
          instructions={PLUGIN_INSTRUCTIONS[target.name]}
          sourceOptions={entrySourceOptions(target.name)}
          onClose={() => setTarget(null)}
          onComplete={() => {
            void refresh();
          }}
        />
      )}
    </div>
  );
}

function Section({
  title,
  subtitle,
  entries,
  actionLabel,
  running,
  onClick,
}: {
  title: string;
  subtitle: string;
  entries: EntryMeta[];
  actionLabel: string;
  running: string | null;
  onClick: (e: EntryMeta) => void;
}) {
  if (entries.length === 0) return null;
  return (
    <section className="mb-12">
      <div className="flex items-baseline gap-3 mb-2">
        <h2 className="text-xl font-bold text-on-surface font-headline">{title}</h2>
        <span className="text-xs font-mono text-gray-500">{entries.length}</span>
      </div>
      <p className="text-xs text-on-surface-variant mb-5">{subtitle}</p>
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {entries.map((entry) => (
          <Card
            key={entry.name}
            entry={entry}
            actionLabel={actionLabel}
            running={running === entry.name}
            onClick={() => onClick(entry)}
          />
        ))}
      </div>
    </section>
  );
}

function Card({
  entry,
  actionLabel,
  running,
  onClick,
}: {
  entry: EntryMeta;
  actionLabel: string;
  running: boolean;
  onClick: () => void;
}) {
  return (
    <div
      data-testid="io-card"
      className="bg-gray-900 rounded-xl border border-white/5 hover:border-accent-light/40 transition-colors flex flex-col overflow-hidden"
    >
      <div className="px-4 py-4 flex-1">
        <div className="flex items-start gap-3 mb-2">
          <div className="w-9 h-9 rounded-lg bg-accent-light/10 flex items-center justify-center shrink-0">
            <Icon name={entryIcon(entry.name)} className="text-accent-light" size={18} />
          </div>
          <div className="min-w-0 flex-1">
            <div className="font-bold text-on-surface text-sm truncate">{entry.name}</div>
            <div className="font-mono text-[10px] text-gray-500 mt-0.5">v{entry.version}</div>
          </div>
        </div>
        <p className="text-xs text-on-surface-variant line-clamp-3">{entry.description}</p>
      </div>
      <button
        onClick={onClick}
        disabled={running}
        className="w-full min-h-12 py-3 px-4 inline-flex items-center justify-center gap-1.5 text-xs font-bold text-accent-light border-t border-white/5 hover:bg-accent-light/10 transition-colors disabled:opacity-40"
      >
        <Icon name={entry.category === "output" ? "upload" : "download"} size={14} />
        {running ? "Running…" : actionLabel}
      </button>
    </div>
  );
}
