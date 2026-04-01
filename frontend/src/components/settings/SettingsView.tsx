import { Eye, EyeOff } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { api } from "../../api/client";
import type { RuntimeConfig } from "../../api/types";
import { useAuth } from "../../hooks/useAuth";
import { Icon } from "../common/Icon";
import { Toggle } from "../common/Toggle";

export function SettingsView() {
  const { signOut } = useAuth();
  const [config, setConfig] = useState<RuntimeConfig | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [llmModel, setLlmModel] = useState("");
  const [llmApiBase, setLlmApiBase] = useState("");
  const [llmApiKey, setLlmApiKey] = useState("");
  const [showApiKey, setShowApiKey] = useState(false);

  const refreshConfig = useCallback(async () => {
    const c = await api.getConfig();
    setConfig(c);
    setLlmModel(c.llm_model);
    setLlmApiBase(c.llm_api_base ?? "");
  }, []);

  useEffect(() => {
    refreshConfig().then(() => setLoading(false));
  }, [refreshConfig]);

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

  const handleApiBaseSave = useCallback(async () => {
    setSaving(true);
    try {
      const updated = await api.updateConfig({
        llm_api_base: llmApiBase.trim() || null,
      });
      setConfig(updated);
      setLlmApiBase(updated.llm_api_base ?? "");
    } finally {
      setSaving(false);
    }
  }, [llmApiBase]);

  const handleApiKeySave = useCallback(async () => {
    if (!llmApiKey.trim()) return;
    setSaving(true);
    try {
      const updated = await api.updateConfig({ llm_api_key: llmApiKey.trim() });
      setConfig(updated);
      setLlmApiKey("");
      setShowApiKey(false);
    } finally {
      setSaving(false);
    }
  }, [llmApiKey]);

  if (loading || !config) {
    return (
      <div className="flex items-center justify-center h-full text-gray-600">Loading...</div>
    );
  }

  const apiBaseChanged = llmApiBase !== (config.llm_api_base ?? "");

  return (
    <div className="h-full overflow-y-auto p-6 scrollbar-thin">
      <h2 className="text-lg font-semibold mb-6 text-gray-100">Settings</h2>

      <div className="max-w-lg space-y-6">
        <section>
          <h3 className="text-sm font-medium text-gray-300 mb-3">Safety</h3>
          <Toggle checked={config.safe_mode} onChange={handleSafeMode} label="Safe Mode" />
          <p className="text-xs text-gray-600 mt-1">
            When enabled, dangerous plugins require approval before execution.
          </p>
        </section>

        <section>
          <h3 className="text-sm font-medium text-gray-300 mb-3">LLM Model</h3>
          <div className="flex gap-2">
            <input
              type="text"
              value={llmModel}
              onChange={(e) => setLlmModel(e.target.value)}
              className="flex-1 rounded-lg border border-gray-700 bg-gray-850 px-3 py-2 text-sm text-gray-100 outline-none focus:border-accent"
            />
            <button
              onClick={handleModelSave}
              disabled={saving || llmModel === config.llm_model}
              className="px-4 py-2 text-sm rounded-lg bg-accent text-white hover:bg-accent-dark disabled:opacity-40 transition-colors"
            >
              Save
            </button>
          </div>
          <p className="text-xs text-gray-600 mt-1">
            Format: provider/model (e.g. anthropic/claude-sonnet-4-20250514)
          </p>
        </section>

        <section>
          <h3 className="text-sm font-medium text-gray-300 mb-3">
            LLM API Base
          </h3>
          <div className="flex gap-2">
            <input
              type="text"
              value={llmApiBase}
              onChange={(e) => setLlmApiBase(e.target.value)}
              placeholder="https://api.openai.com/v1"
              className="flex-1 rounded-lg border border-gray-700 bg-gray-850 px-3 py-2 text-sm text-gray-100 outline-none focus:border-accent placeholder:text-gray-600"
            />
            <button
              onClick={handleApiBaseSave}
              disabled={saving || !apiBaseChanged}
              className="px-4 py-2 text-sm rounded-lg bg-accent text-white hover:bg-accent-dark disabled:opacity-40 transition-colors"
            >
              Save
            </button>
          </div>
          <p className="text-xs text-gray-600 mt-1">
            Optional. Override for self-hosted models (e.g. http://localhost:11434)
          </p>
        </section>

        <section>
          <h3 className="text-sm font-medium text-gray-300 mb-3">
            LLM API Key
          </h3>
          <div className="flex gap-2">
            <div className="relative flex-1">
              <input
                type={showApiKey ? "text" : "password"}
                value={llmApiKey}
                onChange={(e) => setLlmApiKey(e.target.value)}
                placeholder="Enter new API key"
                className="w-full rounded-lg border border-gray-700 bg-gray-850 px-3 py-2 pr-10 text-sm text-gray-100 outline-none focus:border-accent placeholder:text-gray-600"
              />
              <button
                type="button"
                onClick={() => setShowApiKey(!showApiKey)}
                className="absolute right-2 top-1/2 -translate-y-1/2 text-gray-600 hover:text-gray-300"
              >
                {showApiKey ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
              </button>
            </div>
            <button
              onClick={handleApiKeySave}
              disabled={saving || !llmApiKey.trim()}
              className="px-4 py-2 text-sm rounded-lg bg-accent text-white hover:bg-accent-dark disabled:opacity-40 transition-colors"
            >
              Save
            </button>
          </div>
          <div className="flex items-center gap-1.5 mt-2">
            <span
              className={`w-2 h-2 rounded-full ${
                config.has_llm_api_key
                  ? "bg-accent"
                  : "bg-amber-500"
              }`}
            />
            <span className="text-xs text-gray-500">
              {config.has_llm_api_key ? "API key configured" : "No API key set"}
            </span>
          </div>
          <p className="text-xs text-gray-600 mt-1">
            The key is stored securely and never displayed after saving.
          </p>
        </section>

        {config.embedding_model && (
          <section>
            <h3 className="text-sm font-medium text-gray-300 mb-2">Embedding Model</h3>
            <p className="text-sm text-gray-500 font-mono">{config.embedding_model}</p>
          </section>
        )}

        <section className="border-t border-white/5 pt-6">
          <h3 className="text-sm font-medium text-gray-300 mb-3">Account</h3>
          <button
            onClick={() => signOut()}
            className="flex items-center gap-2 px-4 py-2 text-sm text-red-400 hover:bg-red-400/10 rounded-lg transition-colors"
          >
            <Icon name="logout" size={18} />
            <span>Sign out</span>
          </button>
        </section>
      </div>
    </div>
  );
}
