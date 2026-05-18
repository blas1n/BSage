import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useT } from "@bsvibe/i18n";
import { ResponsiveTable } from "@bsvibe/ui";
import type { ResponsiveTableColumn } from "@bsvibe/ui";
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

/** Maps backend trigger types to `plugins.trigger.*` i18n keys. The map
 * itself is module-level (no hooks); the value is translated at the render
 * site inside the component. */
const TRIGGER_LABEL_KEYS: Record<string, string> = {
  cron: "plugins.trigger.cron",
  webhook: "plugins.trigger.webhook",
  on_input: "plugins.trigger.onInput",
  on_demand: "plugins.trigger.onDemand",
  write_event: "plugins.trigger.writeEvent",
};

const CATEGORY_BADGE_STYLES: Record<string, string> = {
  input: "bg-secondary-container/10 text-secondary",
  process: "bg-accent-light/10 text-accent-light",
  output: "bg-tertiary-container/10 text-tertiary",
};

/** Status dot color + `plugins.statusLabel.*` i18n key per status. The
 * label is translated at the render site (module-level maps cannot call
 * hooks). */
const STATUS_DOT_STYLES: Record<string, { bg: string; labelKey: string }> = {
  running: { bg: "bg-green-400", labelKey: "plugins.statusLabel.running" },
  stopped: { bg: "bg-gray-500", labelKey: "plugins.statusLabel.stopped" },
  error: { bg: "bg-red-500", labelKey: "plugins.statusLabel.error" },
};

export function PluginManagerView() {
  const t = useT("sage");
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

  const pluginRows = useMemo(
    () => filtered.filter((e) => e.entry_type === "plugin"),
    [filtered],
  );
  const skillRows = useMemo(
    () => filtered.filter((e) => e.entry_type === "skill"),
    [filtered],
  );

  // Desktop table columns for plugins. Mobile keeps the PluginCard look via
  // ResponsiveTable's renderMobileCard — these columns only drive the
  // sm:+ <table>. All behaviour (run / toggle / setup) is preserved.
  const pluginColumns = useMemo<ResponsiveTableColumn<EntryMeta>[]>(
    () => [
      {
        key: "name",
        header: t("plugins.col.name"),
        cell: (entry) => (
          <span className="font-bold text-on-surface">
            {entry.name}
            <span className="text-xs font-mono text-on-surface-variant/60 ml-1">
              v{entry.version}
            </span>
            {entry.is_dangerous && (
              <span className="ml-2 px-2 py-0.5 rounded text-[10px] font-bold tracking-wider uppercase bg-red-500/10 text-red-400">
                {t("plugins.isDangerous")}
              </span>
            )}
          </span>
        ),
      },
      {
        key: "type",
        header: t("plugins.col.type"),
        cell: (entry) => {
          const catStyle =
            CATEGORY_BADGE_STYLES[entry.category] ??
            "bg-surface-container text-on-surface";
          return (
            <span
              className={`px-2 py-0.5 rounded text-[10px] font-bold tracking-wider uppercase ${catStyle}`}
            >
              {entry.category}
            </span>
          );
        },
      },
      {
        key: "trigger",
        header: t("plugins.col.trigger"),
        cell: (entry) => {
          const triggerType = entry.trigger?.type ?? "on_demand";
          const triggerIcon = TRIGGER_ICONS[triggerType] ?? "auto_awesome";
          return (
            <span className="flex items-center gap-1.5 font-mono text-on-surface-variant">
              <Icon name={triggerIcon} size={14} />
              {TRIGGER_LABEL_KEYS[triggerType]
                ? t(TRIGGER_LABEL_KEYS[triggerType])
                : triggerType}
            </span>
          );
        },
      },
      {
        key: "status",
        header: t("plugins.col.status"),
        cell: (entry) => {
          const needsSetup =
            entry.has_credentials && !entry.credentials_configured;
          const status = needsSetup
            ? "stopped"
            : entry.enabled
              ? "running"
              : "stopped";
          const statusInfo = STATUS_DOT_STYLES[status];
          return (
            <span className="flex items-center gap-1.5">
              <span className={`w-2 h-2 rounded-full ${statusInfo.bg}`} />
              <span className="text-xs text-on-surface-variant font-mono uppercase">
                {t(statusInfo.labelKey)}
              </span>
            </span>
          );
        },
      },
      {
        key: "actions",
        header: t("plugins.col.actions"),
        cellClassName: "text-right",
        cell: (entry) => {
          const needsSetup =
            entry.has_credentials && !entry.credentials_configured;
          const running = runningName === entry.name;
          return (
            <span className="inline-flex items-center gap-2 justify-end">
              {!needsSetup && (
                <Toggle
                  checked={entry.enabled}
                  onChange={() => handleToggle(entry.name)}
                  label={t("plugins.toggleAria", { name: entry.name })}
                />
              )}
              {needsSetup ? (
                <button
                  onClick={() => setSetupTarget(entry.name)}
                  className="min-h-8 px-3 py-1.5 rounded-lg bg-tertiary/10 text-tertiary text-xs font-bold hover:bg-tertiary/20 transition-colors"
                >
                  {t("plugins.configure")}
                </button>
              ) : (
                <button
                  onClick={() => handleRun(entry.name)}
                  disabled={running || !entry.enabled}
                  className="min-h-8 inline-flex items-center gap-1 px-3 py-1.5 rounded-lg text-xs font-bold text-accent-light hover:bg-surface-container-high transition-colors disabled:opacity-40"
                >
                  <Icon name="play_arrow" size={14} />
                  {running ? t("plugins.running") : t("plugins.run")}
                </button>
              )}
            </span>
          );
        },
      },
    ],
    [t, runningName, handleRun, handleToggle],
  );

  const skillColumns = useMemo<ResponsiveTableColumn<EntryMeta>[]>(
    () => [
      {
        key: "name",
        header: t("plugins.col.name"),
        cell: (entry) => (
          <span className="font-bold text-on-surface">{entry.name}</span>
        ),
      },
      {
        key: "type",
        header: t("plugins.col.type"),
        cell: (entry) => (
          <span className="font-mono text-xs uppercase text-on-surface-variant">
            {entry.category}
          </span>
        ),
      },
      {
        key: "status",
        header: t("plugins.col.status"),
        cell: () => (
          <span className="px-3 py-1 rounded-full text-xs font-bold bg-accent/10 text-accent-light">
            {t("plugins.alwaysSafe")}
          </span>
        ),
      },
      {
        key: "actions",
        header: t("plugins.col.actions"),
        cellClassName: "text-right",
        cell: (entry) => {
          const running = runningName === entry.name;
          return (
            <button
              onClick={() => handleRun(entry.name)}
              disabled={running || !entry.enabled}
              className="inline-flex min-h-8 items-center text-xs font-bold text-accent-light hover:underline disabled:opacity-40"
            >
              {running ? t("plugins.running") : t("plugins.run")}
            </button>
          );
        },
      },
    ],
    [t, runningName, handleRun],
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
            {/* Plugins/skills are installed server-side by dropping files into
              * the `plugins/`/`skills/` directories — there is no in-app
              * upload endpoint. The CTA opens the docs that explain how. */}
            <button
              type="button"
              onClick={() =>
                window.open(
                  "https://bsvibe.dev/bsage/features/plugins",
                  "_blank",
                  "noopener,noreferrer",
                )
              }
              className="flex min-h-10 items-center gap-2 rounded-lg bg-accent px-6 py-2.5 text-sm font-bold text-gray-950 shadow-lg shadow-accent/20 transition-all hover:brightness-110"
            >
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
              {cat === "all"
                ? t("plugins.filterAll")
                : cat === "input"
                  ? t("plugins.filterInput")
                  : cat === "process"
                    ? t("plugins.filterProcess")
                    : t("plugins.filterOutput")}
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

        {/* Plugin table — desktop <table>, mobile card stack (PluginCard) */}
        <section className="mb-16">
          <ResponsiveTable<EntryMeta>
            columns={pluginColumns}
            rows={pluginRows}
            rowKey={(e) => e.name}
            emptyMessage={
              <span className="inline-flex flex-col items-center gap-3">
                <Icon name="extension" className="opacity-40" size={32} />
                {t("plugins.noMatch")}
              </span>
            }
            renderMobileCard={(entry) => (
              <PluginCard
                entry={entry}
                onRun={handleRun}
                onToggle={handleToggle}
                onSetup={setSetupTarget}
                running={runningName === entry.name}
              />
            )}
          />
        </section>

        {/* Skills Section */}
        {skillRows.length > 0 && (
          <section className="max-w-4xl">
            <div className="flex items-center gap-4 mb-8">
              <h2 className="text-2xl font-bold text-on-surface font-headline">{t("plugins.skillsHeading")}</h2>
              <div className="h-px flex-1 bg-outline-variant/30" />
            </div>
            <ResponsiveTable<EntryMeta>
              columns={skillColumns}
              rows={skillRows}
              rowKey={(e) => e.name}
              emptyMessage={t("plugins.noMatch")}
              renderMobileCard={(entry) => (
                <SkillCard
                  entry={entry}
                  onRun={handleRun}
                  running={runningName === entry.name}
                />
              )}
            />
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
          title={t("plugins.importVia", { name: uploadTarget.name })}
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
  const t = useT("sage");
  const needsSetup = entry.has_credentials && !entry.credentials_configured;
  const triggerType = entry.trigger?.type ?? "on_demand";
  const triggerIcon = TRIGGER_ICONS[triggerType] ?? "auto_awesome";
  const catStyle = CATEGORY_BADGE_STYLES[entry.category] ?? "bg-surface-container text-on-surface";
  const status = needsSetup ? "stopped" : entry.enabled ? "running" : "stopped";
  const statusInfo = STATUS_DOT_STYLES[status];

  return (
    <div
      data-testid="bsvibe-table-card"
      data-card-kind="plugin-card"
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
              <span className="text-xs text-on-surface-variant font-mono uppercase">{t(statusInfo.labelKey)}</span>
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
            {TRIGGER_LABEL_KEYS[triggerType] ? t(TRIGGER_LABEL_KEYS[triggerType]) : triggerType}
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
  const t = useT("sage");
  const SKILL_ICONS: Record<string, { icon: string; color: string }> = {
    process: { icon: "auto_graph", color: "text-accent-light" },
    input: { icon: "memory", color: "text-secondary" },
    output: { icon: "data_object", color: "text-tertiary" },
  };
  const skillStyle = SKILL_ICONS[entry.category] ?? SKILL_ICONS.process;

  return (
    <div
      data-testid="bsvibe-table-card"
      data-card-kind="skill-card"
      className="bg-surface-container-low p-5 rounded-lg border border-outline-variant/10 flex items-center justify-between group hover:bg-surface-container transition-colors"
    >
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
