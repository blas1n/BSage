import { Plug, Sparkles } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { api } from "../../api/client";
import type { EntryMeta } from "../../api/types";
import { Badge } from "../common/Badge";

export function DashboardView() {
  const [plugins, setPlugins] = useState<EntryMeta[]>([]);
  const [skills, setSkills] = useState<EntryMeta[]>([]);
  const [loading, setLoading] = useState(true);
  const [runningName, setRunningName] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([api.plugins(), api.skills()])
      .then(([p, s]) => {
        setPlugins(p);
        setSkills(s);
      })
      .finally(() => setLoading(false));
  }, []);

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
            <EntryCard key={p.name} entry={p} onRun={handleRun} running={runningName === p.name} />
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
            <EntryCard key={s.name} entry={s} onRun={handleRun} running={runningName === s.name} />
          ))}
        </div>
      </section>
    </div>
  );
}

function EntryCard({
  entry,
  onRun,
  running,
}: {
  entry: EntryMeta;
  onRun: (name: string) => void;
  running: boolean;
}) {
  return (
    <div className="border border-gray-200 dark:border-gray-700 rounded-lg p-4 bg-white dark:bg-gray-800/50">
      <div className="flex items-start justify-between mb-2">
        <div>
          <h4 className="font-medium text-sm text-gray-900 dark:text-gray-100">{entry.name}</h4>
          <span className="text-xs text-gray-400">v{entry.version}</span>
        </div>
        <div className="flex items-center gap-1.5">
          {entry.is_dangerous && (
            <span className="text-[10px] bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-300 rounded-full px-1.5 py-0.5">
              dangerous
            </span>
          )}
          <Badge category={entry.category} />
        </div>
      </div>
      <p className="text-xs text-gray-500 dark:text-gray-400 mb-3 line-clamp-2">{entry.description}</p>
      <button
        onClick={() => onRun(entry.name)}
        disabled={running}
        className="text-xs px-3 py-1.5 rounded-md bg-gray-100 dark:bg-gray-700 text-gray-700 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-600 disabled:opacity-50 transition-colors"
      >
        {running ? "Running..." : "Run"}
      </button>
    </div>
  );
}
