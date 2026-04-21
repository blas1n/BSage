import { Eye, EyeOff } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { api } from "../../api/client";
import type { LlmTestResult, RuntimeConfig } from "../../api/types";
import { useAuth } from "../../hooks/useAuth";
import { Icon } from "../common/Icon";
import { Toggle } from "../common/Toggle";

export function SettingsView() {
  const { logout } = useAuth();
  const [config, setConfig] = useState<RuntimeConfig | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [llmModel, setLlmModel] = useState("");
  const [llmApiBase, setLlmApiBase] = useState("");
  const [llmApiKey, setLlmApiKey] = useState("");
  const [showApiKey, setShowApiKey] = useState(false);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<LlmTestResult | null>(null);

  const refreshConfig = useCallback(async () => {
    setLoading(true);
    setLoadError(null);
    try {
      const c = await api.getConfig();
      setConfig(c);
      setLlmModel(c.llm_model);
      setLlmApiBase(c.llm_api_base ?? "");
    } catch (exc) {
      setLoadError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refreshConfig();
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
      setTestResult(null);
    } finally {
      setSaving(false);
    }
  }, [llmApiKey]);

  const handleTestLlm = useCallback(async () => {
    setTesting(true);
    setTestResult(null);
    try {
      setTestResult(await api.testLlm());
    } catch (exc) {
      setTestResult({ ok: false, error: "request_failed", detail: String(exc) });
    } finally {
      setTesting(false);
    }
  }, []);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full text-gray-600">Loading...</div>
    );
  }

  if (loadError || !config) {
    return (
      <div className="flex flex-col items-center justify-center h-full gap-3 text-gray-400">
        <p className="text-sm">Failed to load settings.</p>
        {loadError && (
          <p className="text-xs text-gray-600 font-mono max-w-md text-center break-all">
            {loadError}
          </p>
        )}
        <button
          onClick={() => void refreshConfig()}
          className="px-3 py-1.5 text-xs rounded-lg border border-gray-700 bg-gray-850 text-gray-200 hover:bg-gray-800 transition-colors"
        >
          Retry
        </button>
      </div>
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

          <div className="mt-3 flex items-center gap-3">
            <button
              onClick={handleTestLlm}
              disabled={testing || !config.has_llm_api_key}
              className="px-3 py-1.5 text-xs rounded-lg border border-gray-700 bg-gray-850 text-gray-200 hover:bg-gray-800 disabled:opacity-40 transition-colors"
            >
              {testing ? "Testing..." : "Test connection"}
            </button>
            {testResult && (
              <span
                className={`text-xs ${testResult.ok ? "text-accent" : "text-amber-400"}`}
              >
                {testResult.ok
                  ? `OK · ${testResult.model} · ${testResult.latency_ms}ms · "${testResult.reply}"`
                  : `${testResult.error ?? "error"}${
                      testResult.hint ? ` — ${testResult.hint}` : ""
                    }${testResult.detail ? `: ${testResult.detail}` : ""}`}
              </span>
            )}
          </div>
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
            onClick={() => logout()}
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
