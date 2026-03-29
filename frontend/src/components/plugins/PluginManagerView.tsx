import {
  AlertTriangle,
  Clock,
  Filter,
  Globe,
  Play,
  Plug,
  Search,
  Sparkles,
  Zap,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "../../api/client";
import type { EntryMeta } from "../../api/types";
import { Badge } from "../common/Badge";
import { Toggle } from "../common/Toggle";
import { SetupModal } from "../dashboard/SetupModal";

type CategoryFilter = "all" | "input" | "process" | "output";
type EntryTypeFilter = "all" | "plugin" | "skill";

const TRIGGER_ICONS: Record<string, typeof Clock> = {
  cron: Clock,
  webhook: Globe,
  on_input: Zap,
  on_demand: Sparkles,
  write_event: Zap,
};

const TRIGGER_LABELS: Record<string, string> = {
  cron: "Cron",
  webhook: "Webhook",
  on_input: "On Input",
  on_demand: "On Demand",
  write_event: "Write Event",
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

  const stats = useMemo(() => {
    const total = allEntries.length;
    const active = allEntries.filter((e) => e.enabled).length;
    const dangerous = allEntries.filter((e) => e.is_dangerous).length;
    const needsSetup = allEntries.filter(
      (e) => e.has_credentials && !e.credentials_configured,
    ).length;
    return { total, active, dangerous, needsSetup };
  }, [allEntries]);

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
      <div className="flex items-center justify-center h-full text-gray-600">
        Loading...
      </div>
    );
  }

  return (
    <div className="h-full overflow-y-auto scrollbar-thin">
      <div className="max-w-6xl mx-auto p-6">
        {/* Header */}
        <div className="mb-6">
          <h2 className="text-xl font-semibold text-gray-100 mb-1">
            Plugin Manager
          </h2>
          <p className="text-sm text-gray-500">
            Manage plugins and skills for your 2nd Brain
          </p>
        </div>

        {/* Stats row */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-6">
          <StatCard label="Total" value={stats.total} accent="text-gray-100" />
          <StatCard label="Active" value={stats.active} accent="text-accent-light" />
          <StatCard
            label="Dangerous"
            value={stats.dangerous}
            accent="text-red-400"
          />
          <StatCard
            label="Needs Setup"
            value={stats.needsSetup}
            accent="text-amber-400"
          />
        </div>

        {/* Filters */}
        <div className="flex flex-wrap items-center gap-3 mb-5">
          {/* Search */}
          <div className="relative flex-1 min-w-[200px] max-w-xs">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-gray-500" />
            <input
              type="text"
              placeholder="Search entries..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-full pl-9 pr-3 py-2 text-sm bg-gray-900 border border-gray-800 rounded-lg text-gray-100 placeholder:text-gray-600 outline-none focus:border-accent/50"
            />
          </div>

          {/* Category filter */}
          <div className="flex items-center gap-1.5">
            <Filter className="w-3.5 h-3.5 text-gray-500" />
            {(["all", "input", "process", "output"] as const).map((cat) => (
              <button
                key={cat}
                onClick={() => setCategoryFilter(cat)}
                className={`px-3 py-1.5 text-xs rounded-md transition-colors ${
                  categoryFilter === cat
                    ? "bg-gray-800 text-gray-100"
                    : "text-gray-500 hover:text-gray-300"
                }`}
              >
                {cat === "all" ? "All" : cat.charAt(0).toUpperCase() + cat.slice(1)}
              </button>
            ))}
          </div>

          {/* Type filter */}
          <div className="flex items-center gap-1.5 border-l border-gray-800 pl-3">
            {(["all", "plugin", "skill"] as const).map((t) => (
              <button
                key={t}
                onClick={() => setTypeFilter(t)}
                className={`px-3 py-1.5 text-xs rounded-md transition-colors ${
                  typeFilter === t
                    ? "bg-gray-800 text-gray-100"
                    : "text-gray-500 hover:text-gray-300"
                }`}
              >
                {t === "all" ? "All Types" : t === "plugin" ? "Plugins" : "Skills"}
              </button>
            ))}
          </div>
        </div>

        {/* Grid */}
        {filtered.length === 0 ? (
          <div className="text-center py-16 text-gray-600">
            <Plug className="w-8 h-8 mx-auto mb-3 opacity-40" />
            <p className="text-sm">No entries match your filters</p>
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {filtered.map((entry) => (
              <PluginCard
                key={entry.name}
                entry={entry}
                onRun={handleRun}
                onToggle={handleToggle}
                onSetup={setSetupTarget}
                running={runningName === entry.name}
              />
            ))}
          </div>
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
    </div>
  );
}

function StatCard({
  label,
  value,
  accent,
}: {
  label: string;
  value: number;
  accent: string;
}) {
  return (
    <div className="bg-gray-900 border border-gray-800 rounded-lg p-4">
      <p className="text-xs text-gray-500 mb-1">{label}</p>
      <p className={`text-2xl font-bold ${accent}`}>{value}</p>
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
  const TriggerIcon = TRIGGER_ICONS[triggerType] ?? Sparkles;

  return (
    <div
      data-testid="plugin-card"
      className="bg-gray-900 border border-gray-800 rounded-xl p-5 hover:border-gray-700 transition-colors group"
    >
      {/* Top row: status dot + name + badges */}
      <div className="flex items-start gap-3 mb-3">
        {/* Status dot */}
        <div className="mt-1.5 shrink-0">
          <div
            className={`w-2.5 h-2.5 rounded-full ${
              needsSetup
                ? "bg-amber-400"
                : entry.enabled
                  ? "bg-accent shadow-[0_0_6px_rgba(16,185,129,0.4)]"
                  : "bg-gray-600"
            }`}
            title={
              needsSetup
                ? "Needs setup"
                : entry.enabled
                  ? "Active"
                  : "Disabled"
            }
          />
        </div>

        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 mb-0.5">
            <h4 className="font-semibold text-sm text-gray-100 truncate">
              {entry.name}
            </h4>
            {entry.entry_type === "plugin" ? (
              <Plug className="w-3 h-3 text-gray-600 shrink-0" />
            ) : (
              <Sparkles className="w-3 h-3 text-gray-600 shrink-0" />
            )}
          </div>
          <span className="text-[11px] text-gray-600 font-mono">
            v{entry.version}
          </span>
        </div>

        <div className="flex items-center gap-1.5 shrink-0">
          {entry.is_dangerous && (
            <span className="flex items-center gap-1 text-[10px] bg-red-900/30 text-red-400 rounded-full px-2 py-0.5 border border-red-900/40">
              <AlertTriangle className="w-2.5 h-2.5" />
              danger
            </span>
          )}
          <Badge category={entry.category} />
        </div>
      </div>

      {/* Description */}
      <p className="text-xs text-gray-500 mb-4 line-clamp-2 leading-relaxed">
        {entry.description}
      </p>

      {/* Trigger type */}
      <div className="flex items-center gap-1.5 mb-4 text-[11px] text-gray-500">
        <TriggerIcon className="w-3 h-3" />
        <span>{TRIGGER_LABELS[triggerType] ?? triggerType}</span>
        {triggerType === "cron" && entry.trigger?.schedule && (
          <span className="text-gray-600 font-mono ml-1">
            {entry.trigger.schedule}
          </span>
        )}
      </div>

      {/* Actions */}
      <div className="flex items-center justify-between pt-3 border-t border-gray-800">
        <div className="flex items-center gap-2">
          {needsSetup ? (
            <button
              onClick={() => onSetup(entry.name)}
              className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg bg-amber-900/30 text-amber-300 hover:bg-amber-900/50 border border-amber-900/40 transition-colors"
            >
              Setup
            </button>
          ) : (
            <button
              onClick={() => onRun(entry.name)}
              disabled={running || !entry.enabled}
              className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg bg-accent/10 text-accent-light hover:bg-accent/20 border border-accent/20 disabled:opacity-40 disabled:hover:bg-accent/10 transition-colors"
            >
              <Play className="w-3 h-3" />
              {running ? "Running..." : "Run"}
            </button>
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
    </div>
  );
}
