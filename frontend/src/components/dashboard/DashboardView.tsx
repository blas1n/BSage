import { Plug, Sparkles } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../../api/client";
import type { EntryMeta } from "../../api/types";
import { Badge } from "../common/Badge";
import { Toggle } from "../common/Toggle";
import { SetupModal } from "./SetupModal";

export function DashboardView() {
  const [plugins, setPlugins] = useState<EntryMeta[]>([]);
  const [skills, setSkills] = useState<EntryMeta[]>([]);
  const [loading, setLoading] = useState(true);
  const [runningName, setRunningName] = useState<string | null>(null);
  const togglingRef = useRef(false);
  const [setupTarget, setSetupTarget] = useState<string | null>(null);

  const refreshData = useCallback(async () => {
    const [p, s] = await Promise.all([api.plugins(), api.skills()]);
    setPlugins(p);
    setSkills(s);
  }, []);

  useEffect(() => {
    refreshData().finally(() => setLoading(false));
  }, [refreshData]);

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
      <div className="flex items-center justify-center h-full text-gray-400">Loading...</div>
    );
  }

  return (
    <div className="h-full overflow-y-auto p-6 scrollbar-thin">
      <h2 className="text-lg font-semibold mb-4 text-gray-800 dark:text-gray-100">Dashboard</h2>

      <section className="mb-8">
        <h3 className="flex items-center gap-2 text-sm font-medium text-gray-500 dark:text-gray-400 mb-3">
          <Plug className="w-4 h-4" />
          Plugins ({plugins.length})
        </h3>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
          {plugins.map((p) => (
            <EntryCard
              key={p.name}
              entry={p}
              onRun={handleRun}
              onToggle={handleToggle}
              onSetup={setSetupTarget}
              running={runningName === p.name}
            />
          ))}
        </div>
      </section>

      <section>
        <h3 className="flex items-center gap-2 text-sm font-medium text-gray-500 dark:text-gray-400 mb-3">
          <Sparkles className="w-4 h-4" />
          Skills ({skills.length})
        </h3>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
          {skills.map((s) => (
            <EntryCard
              key={s.name}
              entry={s}
              onRun={handleRun}
              onToggle={handleToggle}
              onSetup={setSetupTarget}
              running={runningName === s.name}
            />
          ))}
        </div>
      </section>

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

function EntryCard({
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
  const disabled = !entry.enabled;

  return (
    <div
      data-testid="plugin-card"
      className="border border-gray-200 dark:border-gray-700 rounded-lg p-4 bg-white dark:bg-gray-800/50"
    >
      <div className="flex items-start justify-between mb-2">
        <div className="min-w-0 flex-1">
          <h4 className="font-medium text-sm text-gray-900 dark:text-gray-100 truncate">
            {entry.name}
          </h4>
          <span className="text-xs text-gray-400">v{entry.version}</span>
        </div>
        <div className="flex items-center gap-1.5 shrink-0 ml-2">
          {needsSetup && (
            <span className="text-[10px] bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300 rounded-full px-1.5 py-0.5">
              needs setup
            </span>
          )}
          {entry.is_dangerous && (
            <span className="text-[10px] bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-300 rounded-full px-1.5 py-0.5">
              dangerous
            </span>
          )}
          <Badge category={entry.category} />
        </div>
      </div>
      <p className="text-xs text-gray-500 dark:text-gray-400 mb-3 line-clamp-2">
        {entry.description}
      </p>
      <div className="flex items-center justify-between">
        <div>
          {needsSetup ? (
            <button
              onClick={() => onSetup(entry.name)}
              className="text-xs px-3 py-1.5 rounded-md bg-amber-100 dark:bg-amber-900/40 text-amber-700 dark:text-amber-300 hover:bg-amber-200 dark:hover:bg-amber-900/60 transition-colors"
            >
              Setup
            </button>
          ) : (
            <button
              onClick={() => onRun(entry.name)}
              disabled={running || disabled}
              className="text-xs px-3 py-1.5 rounded-md bg-gray-100 dark:bg-gray-700 text-gray-700 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-600 disabled:opacity-50 transition-colors"
            >
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
