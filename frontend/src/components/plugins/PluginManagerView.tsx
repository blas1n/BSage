import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { api } from "../../api/client";
import type { EntryMeta } from "../../api/types";
import { Icon } from "../common/Icon";
import { Toggle } from "../common/Toggle";
import { SetupModal } from "../dashboard/SetupModal";
import { PluginUploadModal } from "./PluginUploadModal";

/** Detect plugins whose input_schema declares an `upload_id` or `path`
 * field — these require a file via POST /api/uploads instead of a
 * payload-less /run/{name} call. */
function entryNeedsUpload(entry: EntryMeta): boolean {
  const schema = entry.input_schema;
  if (!schema || typeof schema !== "object") return false;
  const props = (schema as { properties?: Record<string, unknown> }).properties;
  if (!props || typeof props !== "object") return false;
  return "upload_id" in props || "path" in props;
}

/** Default `accept=` hint per known import plugin. */
function entryAcceptHint(name: string): string | undefined {
  if (name.includes("chatgpt")) return ".json";
  if (name.includes("claude-memory")) return ".zip,.json";
  if (name.includes("obsidian")) return ".zip";
  return undefined;
}

type CategoryFilter = "all" | "input" | "process" | "output";
type EntryTypeFilter = "all" | "plugin" | "skill";

const TRIGGER_ICONS: Record<string, string> = {
  cron: "schedule",
  webhook: "language",
  on_input: "bolt",
  on_demand: "auto_awesome",
  write_event: "bolt",
};

const TRIGGER_LABELS: Record<string, string> = {
  cron: "Cron",
  webhook: "Webhook",
  on_input: "On Input",
  on_demand: "On Demand",
  write_event: "Write Event",
};

const CATEGORY_BADGE_STYLES: Record<string, string> = {
  input: "bg-secondary-container/10 text-secondary",
  process: "bg-accent-light/10 text-accent-light",
  output: "bg-tertiary-container/10 text-tertiary",
};

const STATUS_DOT_STYLES: Record<string, { bg: string; label: string }> = {
  running: { bg: "bg-green-400", label: "Running" },
  stopped: { bg: "bg-gray-500", label: "Stopped" },
  error: { bg: "bg-red-500", label: "Error" },
};

export function PluginManagerView() {
  const { t } = useTranslation();
  const [plugins, setPlugins] = useState<EntryMeta[]>([]);
  const [skills, setSkills] = useState<EntryMeta[]>([]);
  const [loading, setLoading] = useState(true);
  const [runningName, setRunningName] = useState<string | null>(null);
  const togglingRef = useRef(false);
  const [setupTarget, setSetupTarget] = useState<string | null>(null);
  const [uploadTarget, setUploadTarget] = useState<EntryMeta | null>(null);
  const [categoryFilter, setCategoryFilter] = useState<CategoryFilter>("all");
  const [typeFilter, setTypeFilter] = useState<EntryTypeFilter>("all");
  const [searchQuery, setSearchQuery] = useState("");

  const refreshData = useCallback(async () => {
    const [p, s] = await Promise.all([api.plugins(), api.skills()]);
    setPlugins(p);
    setSkills(s);
  }, []);

  useEffect(() => {
    const id = window.setTimeout(() => {
      refreshData().finally(() => setLoading(false));
    }, 0);
    return () => window.clearTimeout(id);
  }, [refreshData]);

  const allEntries = useMemo(() => [...plugins, ...skills], [plugins, skills]);

  // Hide one-shot import/export plugins — they live in their own
  // 'Imports & Exports' tab. Plugins page is for persistent integrations
  // (cron / webhook / on_input triggers) and skills.
  const isOneShotIO = useCallback((e: EntryMeta) => {
    if (e.entry_type !== "plugin") return false;
    if (e.category !== "input" && e.category !== "output") return false;
    return e.trigger?.type === "on_demand";
  }, []);

  const filtered = useMemo(() => {
    return allEntries.filter((e) => {
      if (isOneShotIO(e)) return false;
      if (categoryFilter !== "all" && e.category !== categoryFilter) return false;
      if (typeFilter !== "all" && e.entry_type !== typeFilter) return false;
      if (searchQuery) {
        const q = searchQuery.toLowerCase();
        return (
          e.name.toLowerCase().includes(q) ||
          e.description.toLowerCase().includes(q)
        );
      }
      return true;
    });
  }, [allEntries, categoryFilter, typeFilter, searchQuery, isOneShotIO]);

  const handleRun = useCallback(
    async (name: string) => {
      // Branch upload-needing plugins (chatgpt-memory-input, claude-memory-input,
      // obsidian-input, etc.) into the dedicated dropzone modal so the user
      // can supply a file. Plain plugins keep the body-less /run path.
      const target = [...plugins, ...skills].find((e) => e.name === name);
      if (target && entryNeedsUpload(target)) {
        setUploadTarget(target);
        return;
      }
      setRunningName(name);
      try {
        await api.run(name);
      } catch {
        // errors shown via event panel
      } finally {
        setRunningName(null);
      }
    },
    [plugins, skills],
  );

  const handleToggle = useCallback(
    async (name: string) => {
      if (togglingRef.current) return;
      togglingRef.current = true;
      try {
        await api.toggleEntry(name);
        await refreshData();
      } catch {
        // errors shown via event panel
      } finally {
        togglingRef.current = false;
      }
    },
    [refreshData],
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
      <div className="max-w-6xl mx-auto p-8">
        {/* Header */}
        <header className="flex flex-col md:flex-row md:items-center justify-between gap-6 mb-10">
          <div>
            <h1 className="text-4xl font-extrabold tracking-tight mb-2 text-on-surface font-headline">{t("plugins.title")}</h1>
            <p className="text-on-surface-variant font-medium">{t("plugins.subtitle")}</p>
          </div>
          <div className="flex items-center gap-4">
            <button className="flex min-h-10 items-center gap-2 rounded-lg bg-accent px-6 py-2.5 text-sm font-bold text-gray-950 shadow-lg shadow-accent/20 transition-all hover:brightness-110">
              <Icon name="extension" size={18} />
              {t("plugins.install")}
            </button>
          </div>
        </header>

        {/* Filters */}
        <div className="flex items-center gap-2 mb-8 overflow-x-auto no-scrollbar pb-2">
          {(["all", "input", "process", "output"] as const).map((cat) => (
            <button
              key={cat}
              onClick={() => setCategoryFilter(cat)}
              className={`min-h-10 px-5 py-2 rounded-full font-medium text-sm transition-colors ${
                categoryFilter === cat
                  ? "bg-accent text-gray-950 font-bold"
                  : "bg-surface-container-high text-on-surface-variant hover:text-on-surface"
              }`}
            >
              {cat === "all" ? t("plugins.filterAll") : cat.charAt(0).toUpperCase() + cat.slice(1)}
            </button>
          ))}

          <div className="h-6 w-px bg-outline-variant/30 mx-2" />

          {(["all", "plugin", "skill"] as const).map((tf) => (
            <button
              key={tf}
              onClick={() => setTypeFilter(tf)}
              className={`min-h-10 px-4 py-2 rounded-full text-sm transition-colors ${
                typeFilter === tf
                  ? "bg-surface-container-high text-on-surface font-bold"
                  : "text-on-surface-variant hover:text-on-surface"
              }`}
            >
              {tf === "all" ? t("plugins.filterAllTypes") : tf === "plugin" ? t("plugins.filterPlugins") : t("plugins.filterSkills")}
            </button>
          ))}

          <div className="flex-1" />

          {/* Search */}
          <div className="relative min-w-[200px]">
            <Icon name="search" className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-500" size={16} />
            <input
              type="text"
              placeholder={t("plugins.searchPlaceholder")}
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="min-h-10 w-full pl-9 pr-3 py-2 text-sm bg-surface-container-low border-none rounded-lg text-on-surface placeholder:text-gray-500 outline-none focus:ring-1 focus:ring-accent-light/30 font-sans"
            />
          </div>
        </div>

        {/* Plugin Grid */}
        {filtered.length === 0 ? (
          <div className="text-center py-16 text-gray-500">
            <Icon name="extension" className="mx-auto mb-3 opacity-40" size={32} />
            <p className="text-sm">{t("plugins.noMatch")}</p>
          </div>
        ) : (
          <section className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6 mb-16">
            {filtered.filter(e => e.entry_type === "plugin").map((entry) => (
              <PluginCard
                key={entry.name}
                entry={entry}
                onRun={handleRun}
                onToggle={handleToggle}
                onSetup={setSetupTarget}
                running={runningName === entry.name}
              />
            ))}
          </section>
        )}

        {/* Skills Section */}
        {filtered.filter(e => e.entry_type === "skill").length > 0 && (
          <section className="max-w-4xl">
            <div className="flex items-center gap-4 mb-8">
              <h2 className="text-2xl font-bold text-on-surface font-headline">{t("plugins.skillsHeading")}</h2>
              <div className="h-px flex-1 bg-outline-variant/30" />
            </div>
            <div className="grid grid-cols-1 gap-4">
              {filtered.filter(e => e.entry_type === "skill").map((entry) => (
                <SkillCard
                  key={entry.name}
                  entry={entry}
                  onRun={handleRun}
                  running={runningName === entry.name}
                />
              ))}
            </div>
          </section>
        )}
      </div>

      {setupTarget && (
        <SetupModal
          entryName={setupTarget}
          onClose={() => setSetupTarget(null)}
          onSuccess={() => {
            setSetupTarget(null);
            refreshData();
          }}
        />
      )}

      {uploadTarget && (
        <PluginUploadModal
          pluginName={uploadTarget.name}
          title={`Import via ${uploadTarget.name}`}
          subtitle={uploadTarget.description}
          accept={entryAcceptHint(uploadTarget.name)}
          onClose={() => setUploadTarget(null)}
          onComplete={() => {
            setUploadTarget(null);
            refreshData();
          }}
        />
      )}


      {/* Background glow */}
      <div className="fixed bottom-0 right-0 w-[600px] h-[600px] bg-accent-light/5 rounded-full blur-[120px] -z-10 translate-x-1/2 translate-y-1/2 pointer-events-none" />
    </div>
  );
}

function PluginCard({
  entry,
  onRun,
  onToggle,
  onSetup,
  running,
}: {
  entry: EntryMeta;
  onRun: (name: string) => void;
  onToggle: (name: string) => void;
  onSetup: (name: string) => void;
  running: boolean;
}) {
  const { t } = useTranslation();
  const needsSetup = entry.has_credentials && !entry.credentials_configured;
  const triggerType = entry.trigger?.type ?? "on_demand";
  const triggerIcon = TRIGGER_ICONS[triggerType] ?? "auto_awesome";
  const catStyle = CATEGORY_BADGE_STYLES[entry.category] ?? "bg-surface-container text-on-surface";
  const status = needsSetup ? "stopped" : entry.enabled ? "running" : "stopped";
  const statusInfo = STATUS_DOT_STYLES[status];

  return (
    <div
      data-testid="plugin-card"
      className={`bg-gray-900 rounded-xl border overflow-hidden flex flex-col transition-all group ${
        entry.is_dangerous
          ? "border-white/5 hover:border-error/30"
          : "border-white/5 hover:border-accent-light/30"
      }`}
    >
    {/* Inner content padded; the action row below this stack is flush so
        Configure/Run sit edge-to-edge of the card. */}
    <div className="p-6 flex flex-col gap-5">
      {/* Top row */}
      <div className="flex justify-between items-start">
        <div>
          <h3 className="font-bold text-lg text-on-surface">
            {entry.name}
            <span className="text-xs font-mono text-on-surface-variant/60 ml-1">v{entry.version}</span>
          </h3>
          <div className="flex flex-wrap items-center gap-2 mt-2">
            <span className={`px-2 py-0.5 rounded text-[10px] font-bold tracking-wider uppercase ${catStyle}`}>
              {entry.category}
            </span>
            <div className="flex items-center gap-1.5 ml-2">
              <span className={`w-2 h-2 rounded-full ${statusInfo.bg}`} />
              <span className="text-xs text-on-surface-variant font-mono uppercase">{statusInfo.label}</span>
            </div>
          </div>
          {entry.is_dangerous && (
            <div className="mt-2">
              <span className="px-2 py-0.5 rounded text-[10px] font-bold tracking-wider uppercase bg-red-500/10 text-red-400">
                {t("plugins.isDangerous")}
              </span>
            </div>
          )}
        </div>
        {!needsSetup && (
          <Toggle
            checked={entry.enabled}
            onChange={() => onToggle(entry.name)}
            label={t("plugins.toggleAria", { name: entry.name })}
          />
        )}
      </div>

      {/* Description */}
      <p className="text-xs text-on-surface-variant line-clamp-2 leading-relaxed">
        {entry.description}
      </p>

      {/* Metadata */}
      <div className="flex flex-col gap-3">
        <div className="flex items-center justify-between text-xs font-mono text-on-surface-variant">
          <span>{t("plugins.triggerType")}</span>
          <span className="flex items-center gap-1.5">
            <Icon name={triggerIcon} size={14} />
            {TRIGGER_LABELS[triggerType] ?? triggerType}
          </span>
        </div>
        {triggerType === "cron" && entry.trigger?.schedule && (
          <div className="flex items-center justify-between text-xs font-mono text-on-surface-variant">
            <span>{t("plugins.schedule")}</span>
            <span className="bg-surface-container px-2 py-0.5 rounded text-[10px] text-on-surface">{entry.trigger.schedule}</span>
          </div>
        )}
      </div>

    </div>

      {/* Actions — flush footer, no horizontal padding so the buttons
          touch the card edges. Configure (50%) | Run (50%), divider
          between them mirrors the supervisor rules row pattern. */}
      <div className="mt-auto flex items-stretch border-t border-white/5">
        {needsSetup ? (
          <button
            onClick={() => onSetup(entry.name)}
            className="min-h-12 flex-1 py-3 bg-tertiary/10 text-tertiary text-xs font-bold hover:bg-tertiary/20 transition-colors"
          >
            {t("plugins.configure")}
          </button>
        ) : (
          <>
            <button
              onClick={() => onRun(entry.name)}
              disabled={running || !entry.enabled}
              className="min-h-12 flex-1 py-3 text-xs font-bold hover:bg-surface-container-high transition-colors disabled:opacity-40 border-r border-white/5"
            >
              {running ? t("plugins.running") : t("plugins.configure")}
            </button>
            <button
              onClick={() => onRun(entry.name)}
              disabled={running || !entry.enabled}
              className="min-h-12 flex-1 inline-flex items-center justify-center py-3 text-xs font-bold text-accent-light hover:bg-surface-container-high transition-colors disabled:opacity-40"
            >
              <Icon name="play_arrow" size={16} className="inline-block mr-1" />
              {t("plugins.run")}
            </button>
          </>
        )}
      </div>
    </div>
  );
}

function SkillCard({
  entry,
  onRun,
  running,
}: {
  entry: EntryMeta;
  onRun: (name: string) => void;
  running: boolean;
}) {
  const { t } = useTranslation();
  const SKILL_ICONS: Record<string, { icon: string; color: string }> = {
    process: { icon: "auto_graph", color: "text-accent-light" },
    input: { icon: "memory", color: "text-secondary" },
    output: { icon: "data_object", color: "text-tertiary" },
  };
  const skillStyle = SKILL_ICONS[entry.category] ?? SKILL_ICONS.process;

  return (
    <div className="bg-surface-container-low p-5 rounded-lg border border-outline-variant/10 flex items-center justify-between group hover:bg-surface-container transition-colors">
      <div className="flex items-center gap-4">
        <div className={`w-10 h-10 rounded flex items-center justify-center ${
          entry.category === "input" ? "bg-secondary/10" :
          entry.category === "output" ? "bg-tertiary/10" :
          "bg-accent-light/10"
        }`}>
          <Icon name={skillStyle.icon} className={skillStyle.color} size={20} />
        </div>
        <div>
          <h4 className="font-bold text-on-surface">{entry.name}</h4>
          <p className="text-sm text-on-surface-variant font-mono">{entry.description}</p>
        </div>
      </div>
      <div className="flex items-center gap-3">
        <span className="px-3 py-1 rounded-full text-xs font-bold bg-accent/10 text-accent-light">{t("plugins.alwaysSafe")}</span>
        <button
          onClick={() => onRun(entry.name)}
          disabled={running || !entry.enabled}
          className="inline-flex min-h-10 items-center text-xs font-bold text-accent-light hover:underline disabled:opacity-40"
        >
          {running ? t("plugins.running") : t("plugins.run")}
        </button>
      </div>
    </div>
  );
}
