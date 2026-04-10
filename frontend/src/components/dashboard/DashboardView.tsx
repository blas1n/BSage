import { useCallback, useEffect, useState } from "react";
import { api } from "../../api/client";
import type { EntryMeta, VaultTreeEntry } from "../../api/types";
import { type ConnectionState, wsManager } from "../../api/websocket";
import { Icon } from "../common/Icon";

interface DashboardStats {
  totalNotes: number;
  activePlugins: number;
  activeSkills: number;
  knowledgeEntries: number;
}

interface PluginStatusSummary {
  running: number;
  stopped: number;
  errors: number;
}

function countFiles(tree: VaultTreeEntry[]): number {
  return tree.reduce((sum, entry) => sum + entry.files.length, 0);
}

function computePluginStatus(plugins: EntryMeta[]): PluginStatusSummary {
  let running = 0;
  let stopped = 0;
  const errors = 0;
  for (const p of plugins) {
    if (p.enabled) running++;
    else stopped++;
  }
  return { running, stopped, errors };
}

export function DashboardView() {
  const [stats, setStats] = useState<DashboardStats>({
    totalNotes: 0,
    activePlugins: 0,
    activeSkills: 0,
    knowledgeEntries: 0,
  });
  const [pluginStatus, setPluginStatus] = useState<PluginStatusSummary>({
    running: 0,
    stopped: 0,
    errors: 0,
  });
  const [recentFiles, setRecentFiles] = useState<string[]>([]);
  const [wsState, setWsState] = useState<ConnectionState>(wsManager.state);
  const [loading, setLoading] = useState(true);

  const loadData = useCallback(async () => {
    try {
      const [tree, plugins, skills, searchResults] = await Promise.all([
        api.vaultTree(),
        api.plugins(),
        api.skills(),
        api.vaultSearch("*"),
      ]);

      const totalNotes = countFiles(tree);
      const activePlugins = plugins.filter((p) => p.enabled).length;
      const activeSkills = skills.filter((s) => s.enabled).length;
      const knowledgeEntries = searchResults.length;

      setStats({ totalNotes, activePlugins, activeSkills, knowledgeEntries });
      setPluginStatus(computePluginStatus(plugins));

      // Collect all file paths for recent activity
      const allFiles = tree.flatMap((entry) =>
        entry.files.map((f) => (entry.path ? `${entry.path}/${f}` : f)),
      );
      setRecentFiles(allFiles.slice(0, 8));
    } catch {
      // errors shown via event panel
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadData();
  }, [loadData]);

  useEffect(() => {
    const unsub = wsManager.onStateChange(setWsState);
    return unsub;
  }, []);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full text-gray-500">
        Loading...
      </div>
    );
  }

  const WS_STATE_STYLES: Record<ConnectionState, { dot: string; label: string }> = {
    connected: { dot: "bg-accent-light", label: "Connected" },
    disconnected: { dot: "bg-gray-500", label: "Offline" },
    reconnecting: { dot: "bg-tertiary animate-pulse", label: "Reconnecting" },
  };

  const wsStyle = WS_STATE_STYLES[wsState];

  return (
    <div className="h-full overflow-y-auto scrollbar-thin">
      <div className="max-w-5xl mx-auto p-8">
        <h1 className="text-4xl font-extrabold tracking-tight mb-8 text-on-surface font-headline">
          Dashboard
        </h1>

        {/* Quick Stats */}
        <section className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-10">
          <StatCard
            icon="description"
            label="Total Notes"
            value={stats.totalNotes}
            testId="stat-total-notes"
          />
          <StatCard
            icon="extension"
            label="Active Plugins"
            value={stats.activePlugins}
            testId="stat-active-plugins"
          />
          <StatCard
            icon="auto_awesome"
            label="Active Skills"
            value={stats.activeSkills}
            testId="stat-active-skills"
          />
          <StatCard
            icon="neurology"
            label="Knowledge Entries"
            value={stats.knowledgeEntries}
            testId="stat-knowledge"
          />
        </section>

        {/* Quick Actions */}
        <section className="mb-10">
          <h2 className="text-[10px] uppercase tracking-widest text-on-surface-variant font-bold mb-4">
            Quick Actions
          </h2>
          <div className="flex flex-wrap gap-3">
            <ActionLink href="#/" icon="chat" label="New Chat Session" />
            <ActionLink href="#/vault" icon="folder_open" label="Browse Vault" />
            <ActionLink href="#/graph" icon="hub" label="View Graph" />
          </div>
        </section>

        {/* Recent Activity */}
        <section className="mb-10">
          <h2 className="text-[10px] uppercase tracking-widest text-on-surface-variant font-bold mb-4">
            Recent Activity
          </h2>
          <div className="bg-surface-container-low rounded-xl border border-white/5 p-5">
            {recentFiles.length === 0 ? (
              <p className="text-sm text-on-surface-variant text-center py-4">
                No recent vault files
              </p>
            ) : (
              <ul className="space-y-2">
                {recentFiles.map((file) => (
                  <li key={file} className="flex items-center gap-2 text-sm text-on-surface">
                    <Icon name="draft" size={16} className="text-on-surface-variant" />
                    <span className="font-mono text-xs">{file}</span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </section>

        {/* System Status */}
        <section>
          <h2 className="text-[10px] uppercase tracking-widest text-on-surface-variant font-bold mb-4">
            System Status
          </h2>
          <div className="bg-surface-container-low rounded-xl border border-white/5 p-5 space-y-4">
            {/* WebSocket */}
            <div className="flex items-center justify-between">
              <span className="text-sm font-medium text-on-surface">WebSocket</span>
              <div className="flex items-center gap-2">
                <span className={`w-2 h-2 rounded-full ${wsStyle.dot}`} />
                <span className="text-xs font-mono text-on-surface-variant uppercase">
                  {wsStyle.label}
                </span>
              </div>
            </div>

            {/* Plugin Status */}
            <div className="flex items-center justify-between">
              <span className="text-sm font-medium text-on-surface">Plugin Status</span>
              <div className="flex items-center gap-3 text-xs font-mono text-on-surface-variant">
                <span className="flex items-center gap-1">
                  <span className="w-2 h-2 rounded-full bg-green-400" />
                  {pluginStatus.running} running
                </span>
                <span className="flex items-center gap-1">
                  <span className="w-2 h-2 rounded-full bg-gray-500" />
                  {pluginStatus.stopped} stopped
                </span>
                {pluginStatus.errors > 0 && (
                  <span className="flex items-center gap-1">
                    <span className="w-2 h-2 rounded-full bg-red-500" />
                    {pluginStatus.errors} errors
                  </span>
                )}
              </div>
            </div>
          </div>
        </section>
      </div>
    </div>
  );
}

function StatCard({
  icon,
  label,
  value,
  testId,
}: {
  icon: string;
  label: string;
  value: number;
  testId: string;
}) {
  return (
    <div
      data-testid="stat-card"
      className="bg-surface-container rounded-xl border border-white/5 p-5 flex flex-col gap-3"
    >
      <div className="flex items-center gap-2">
        <Icon name={icon} size={18} className="text-accent-light" />
        <span className="text-[10px] uppercase tracking-widest text-on-surface-variant font-bold">
          {label}
        </span>
      </div>
      <span
        data-testid={testId}
        className="text-3xl font-extrabold text-on-surface tabular-nums"
      >
        {value}
      </span>
    </div>
  );
}

function ActionLink({
  href,
  icon,
  label,
}: {
  href: string;
  icon: string;
  label: string;
}) {
  return (
    <a
      href={href}
      className="flex items-center gap-2 px-5 py-2.5 rounded-lg bg-surface-container-low border border-white/5 text-sm font-bold text-on-surface hover:bg-surface-container transition-colors"
    >
      <Icon name={icon} size={18} />
      {label}
    </a>
  );
}
