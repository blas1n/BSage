import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "../../api/client";
import type { EntryMeta } from "../../api/types";
import { Icon } from "../common/Icon";
import { Toggle } from "../common/Toggle";
import { SetupModal } from "../dashboard/SetupModal";

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
  const [plugins, setPlugins] = useState<EntryMeta[]>([]);
  const [skills, setSkills] = useState<EntryMeta[]>([]);
  const [loading, setLoading] = useState(true);
  const [runningName, setRunningName] = useState<string | null>(null);
  const togglingRef = useRef(false);
  const [setupTarget, setSetupTarget] = useState<string | null>(null);
  const [categoryFilter, setCategoryFilter] = useState<CategoryFilter>("all");
  const [typeFilter, setTypeFilter] = useState<EntryTypeFilter>("all");
  const [searchQuery, setSearchQuery] = useState("");

  const refreshData = useCallback(async () => {
    const [p, s] = await Promise.all([api.plugins(), api.skills()]);
    setPlugins(p);
    setSkills(s);
  }, []);

  useEffect(() => {
    refreshData().finally(() => setLoading(false));
  }, [refreshData]);

  const allEntries = useMemo(() => [...plugins, ...skills], [plugins, skills]);

  const filtered = useMemo(() => {
    return allEntries.filter((e) => {
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
  }, [allEntries, categoryFilter, typeFilter, searchQuery]);

  const handleRun = useCallback(async (name: string) => {
    setRunningName(name);
    try {
      await api.run(name);
    } catch {
      // errors shown via event panel
    } finally {
      setRunningName(null);
    }
  }, []);

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
        Loading...
      </div>
    );
  }

  return (
    <div className="h-full overflow-y-auto scrollbar-thin">
      <div className="max-w-6xl mx-auto p-8">
        {/* Header */}
        <header className="flex flex-col md:flex-row md:items-center justify-between gap-6 mb-10">
          <div>
            <h1 className="text-4xl font-extrabold tracking-tight mb-2 text-on-surface font-headline">Plugins</h1>
            <p className="text-on-surface-variant font-medium">Extend your kinetic knowledge graph capabilities.</p>
          </div>
          <div className="flex items-center gap-4">
            <button className="bg-accent text-gray-950 px-6 py-2.5 rounded-lg font-bold flex items-center gap-2 hover:brightness-110 transition-all shadow-lg shadow-accent/20 text-sm">
              <Icon name="extension" size={18} />
              Install Plugin
            </button>
          </div>
        </header>

        {/* Filters */}
        <div className="flex items-center gap-2 mb-8 overflow-x-auto no-scrollbar pb-2">
          {(["all", "input", "process", "output"] as const).map((cat) => (
            <button
              key={cat}
              onClick={() => setCategoryFilter(cat)}
              className={`px-5 py-2 rounded-full font-medium text-sm transition-colors ${
                categoryFilter === cat
                  ? "bg-accent text-gray-950 font-bold"
                  : "bg-surface-container-high text-on-surface-variant hover:text-on-surface"
              }`}
            >
              {cat === "all" ? "All" : cat.charAt(0).toUpperCase() + cat.slice(1)}
            </button>
          ))}

          <div className="h-6 w-px bg-outline-variant/30 mx-2" />

          {(["all", "plugin", "skill"] as const).map((t) => (
            <button
              key={t}
              onClick={() => setTypeFilter(t)}
              className={`px-4 py-2 rounded-full text-sm transition-colors ${
                typeFilter === t
                  ? "bg-surface-container-high text-on-surface font-bold"
                  : "text-on-surface-variant hover:text-on-surface"
              }`}
            >
              {t === "all" ? "All Types" : t === "plugin" ? "Plugins" : "Skills"}
            </button>
          ))}

          <div className="flex-1" />

          {/* Search */}
          <div className="relative min-w-[200px]">
            <Icon name="search" className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-500" size={16} />
            <input
              type="text"
              placeholder="Search plugins..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-full pl-9 pr-3 py-2 text-sm bg-surface-container-low border-none rounded-lg text-on-surface placeholder:text-gray-500 outline-none focus:ring-1 focus:ring-accent-light/30 font-sans"
            />
          </div>
        </div>

        {/* Plugin Grid */}
        {filtered.length === 0 ? (
          <div className="text-center py-16 text-gray-500">
            <Icon name="extension" className="mx-auto mb-3 opacity-40" size={32} />
            <p className="text-sm">No entries match your filters</p>
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
              <h2 className="text-2xl font-bold text-on-surface font-headline">Skills</h2>
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
  const needsSetup = entry.has_credentials && !entry.credentials_configured;
  const triggerType = entry.trigger?.type ?? "on_demand";
  const triggerIcon = TRIGGER_ICONS[triggerType] ?? "auto_awesome";
  const catStyle = CATEGORY_BADGE_STYLES[entry.category] ?? "bg-surface-container text-on-surface";
  const status = needsSetup ? "stopped" : entry.enabled ? "running" : "stopped";
  const statusInfo = STATUS_DOT_STYLES[status];

  return (
    <div
      data-testid="plugin-card"
      className={`bg-gray-900 rounded-xl p-6 border flex flex-col gap-5 transition-all group ${
        entry.is_dangerous
          ? "border-white/5 hover:border-error/30"
          : "border-white/5 hover:border-accent-light/30"
      }`}
    >
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
                Is Dangerous
              </span>
            </div>
          )}
        </div>
        {!needsSetup && (
          <Toggle
            checked={entry.enabled}
            onChange={() => onToggle(entry.name)}
            label={`Toggle ${entry.name}`}
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
          <span>Trigger Type</span>
          <span className="flex items-center gap-1.5">
            <Icon name={triggerIcon} size={14} />
            {TRIGGER_LABELS[triggerType] ?? triggerType}
          </span>
        </div>
        {triggerType === "cron" && entry.trigger?.schedule && (
          <div className="flex items-center justify-between text-xs font-mono text-on-surface-variant">
            <span>Schedule</span>
            <span className="bg-surface-container px-2 py-0.5 rounded text-[10px] text-on-surface">{entry.trigger.schedule}</span>
          </div>
        )}
      </div>

      {/* Actions */}
      <div className="flex items-center gap-3 pt-4 mt-auto border-t border-white/5">
        {needsSetup ? (
          <button
            onClick={() => onSetup(entry.name)}
            className="flex-1 py-2 rounded-md bg-tertiary/10 text-tertiary text-xs font-bold hover:bg-tertiary/20 border border-tertiary/20 transition-colors"
          >
            Configure
          </button>
        ) : (
          <>
            <button
              onClick={() => onRun(entry.name)}
              disabled={running || !entry.enabled}
              className="flex-1 py-2 rounded-md border border-outline-variant text-xs font-bold hover:bg-surface-container-high transition-colors disabled:opacity-40"
            >
              {running ? "Running..." : "Configure"}
            </button>
            <button
              onClick={() => onRun(entry.name)}
              disabled={running || !entry.enabled}
              className="text-xs font-bold text-accent-light hover:underline px-2 disabled:opacity-40"
            >
              <Icon name="play_arrow" size={16} className="inline-block mr-1" />
              Run
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
        <span className="px-3 py-1 rounded-full text-xs font-bold bg-accent/10 text-accent-light">Always Safe</span>
        <button
          onClick={() => onRun(entry.name)}
          disabled={running || !entry.enabled}
          className="text-xs font-bold text-accent-light hover:underline disabled:opacity-40"
        >
          {running ? "Running..." : "Run"}
        </button>
      </div>
    </div>
  );
}
