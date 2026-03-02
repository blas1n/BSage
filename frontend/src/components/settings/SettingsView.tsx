import { useCallback, useEffect, useState } from "react";
import { api } from "../../api/client";
import type { RuntimeConfig } from "../../api/types";
import { Toggle } from "../common/Toggle";

export function SettingsView() {
  const [config, setConfig] = useState<RuntimeConfig | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [llmModel, setLlmModel] = useState("");

  useEffect(() => {
    api.getConfig().then((c) => {
      setConfig(c);
      setLlmModel(c.llm_model);
      setLoading(false);
    });
  }, []);

  const handleSafeMode = useCallback(async (checked: boolean) => {
    setSaving(true);
    try {
      const updated = await api.updateConfig({ safe_mode: checked });
      setConfig(updated);
    } finally {
      setSaving(false);
    }
  }, []);

  const handleModelSave = useCallback(async () => {
    if (!llmModel.trim()) return;
    setSaving(true);
    try {
      const updated = await api.updateConfig({ llm_model: llmModel.trim() });
      setConfig(updated);
    } finally {
      setSaving(false);
    }
  }, [llmModel]);

  if (loading || !config) {
    return (
      <div className="flex items-center justify-center h-full text-gray-400">Loading...</div>
    );
  }

  return (
    <div className="h-full overflow-y-auto p-6 scrollbar-thin">
      <h2 className="text-lg font-semibold mb-6 text-gray-800 dark:text-gray-100">Settings</h2>

      <div className="max-w-lg space-y-6">
        <section>
          <h3 className="text-sm font-medium text-gray-700 dark:text-gray-300 mb-3">Safety</h3>
          <Toggle checked={config.safe_mode} onChange={handleSafeMode} label="Safe Mode" />
          <p className="text-xs text-gray-400 mt-1">
            When enabled, dangerous plugins require approval before execution.
          </p>
        </section>

        <section>
          <h3 className="text-sm font-medium text-gray-700 dark:text-gray-300 mb-3">LLM Model</h3>
          <div className="flex gap-2">
            <input
              type="text"
              value={llmModel}
              onChange={(e) => setLlmModel(e.target.value)}
              className="flex-1 rounded-lg border border-gray-300 dark:border-gray-600 bg-gray-50 dark:bg-gray-700 px-3 py-2 text-sm outline-none focus:border-green-500"
            />
            <button
              onClick={handleModelSave}
              disabled={saving || llmModel === config.llm_model}
              className="px-4 py-2 text-sm rounded-lg bg-green-600 text-white hover:bg-green-700 disabled:opacity-40 transition-colors"
            >
              Save
            </button>
          </div>
          <p className="text-xs text-gray-400 mt-1">
            Format: provider/model (e.g. anthropic/claude-sonnet-4-20250514)
          </p>
        </section>

        {config.embedding_model && (
          <section>
            <h3 className="text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">Embedding Model</h3>
            <p className="text-sm text-gray-500 dark:text-gray-400 font-mono">{config.embedding_model}</p>
          </section>
        )}
      </div>
    </div>
  );
}
