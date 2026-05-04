import { Eye, EyeOff } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { api } from "../../api/client";
import type { LlmTestResult, RuntimeConfig } from "../../api/types";
import { useAuth } from "../../hooks/useAuth";
import { Icon } from "../common/Icon";
import { Toggle } from "../common/Toggle";

export function SettingsView() {
  const { t } = useTranslation();
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
    const id = window.setTimeout(() => {
      void refreshConfig();
    }, 0);
    return () => window.clearTimeout(id);
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
      <div className="flex items-center justify-center h-full text-gray-600">{t("common.loading")}</div>
    );
  }

  if (loadError || !config) {
    return (
      <div className="flex flex-col items-center justify-center h-full gap-3 text-gray-400">
        <p className="text-sm">{t("settings.loadFailed")}</p>
        {loadError && (
          <p className="text-xs text-gray-600 font-mono max-w-md text-center break-all">
            {loadError}
          </p>
        )}
        <button
          onClick={() => void refreshConfig()}
          className="min-h-10 px-3 py-1.5 text-xs rounded-lg border border-gray-700 bg-gray-850 text-gray-200 hover:bg-gray-800 transition-colors"
        >
          {t("common.retry")}
        </button>
      </div>
    );
  }

  const apiBaseChanged = llmApiBase !== (config.llm_api_base ?? "");

  return (
    <div className="h-full overflow-y-auto p-6 scrollbar-thin">
      <h2 className="text-lg font-semibold mb-6 text-gray-100">{t("settings.title")}</h2>

      <div className="max-w-lg space-y-6">
        <section>
          <h3 className="text-sm font-medium text-gray-300 mb-3">{t("settings.safetyHeading")}</h3>
          <Toggle checked={config.safe_mode} onChange={handleSafeMode} label={t("settings.safeMode")} />
          <p className="text-xs text-gray-600 mt-1">
            {t("settings.safeModeHint")}
          </p>
        </section>

        <section>
          <h3 className="text-sm font-medium text-gray-300 mb-3">{t("settings.llmModelHeading")}</h3>
          <div className="flex gap-2">
            <input
              type="text"
              value={llmModel}
              onChange={(e) => setLlmModel(e.target.value)}
              className="min-h-10 flex-1 rounded-lg border border-gray-700 bg-gray-850 px-3 py-2 text-sm text-gray-100 outline-none focus:border-accent"
            />
            <button
              onClick={handleModelSave}
              disabled={saving || llmModel === config.llm_model}
              className="min-h-10 px-4 py-2 text-sm rounded-lg bg-accent text-white hover:bg-accent-dark disabled:opacity-40 transition-colors"
            >
              {t("common.save")}
            </button>
          </div>
          <p className="text-xs text-gray-600 mt-1">
            {t("settings.llmModelHint")}
          </p>
        </section>

        <section>
          <h3 className="text-sm font-medium text-gray-300 mb-3">
            {t("settings.llmApiBaseHeading")}
          </h3>
          <div className="flex gap-2">
            <input
              type="text"
              value={llmApiBase}
              onChange={(e) => setLlmApiBase(e.target.value)}
              placeholder={t("settings.llmApiBasePlaceholder")}
              className="min-h-10 flex-1 rounded-lg border border-gray-700 bg-gray-850 px-3 py-2 text-sm text-gray-100 outline-none focus:border-accent placeholder:text-gray-600"
            />
            <button
              onClick={handleApiBaseSave}
              disabled={saving || !apiBaseChanged}
              className="min-h-10 px-4 py-2 text-sm rounded-lg bg-accent text-white hover:bg-accent-dark disabled:opacity-40 transition-colors"
            >
              {t("common.save")}
            </button>
          </div>
          <p className="text-xs text-gray-600 mt-1">
            {t("settings.llmApiBaseHint")}
          </p>
        </section>

        <section>
          <h3 className="text-sm font-medium text-gray-300 mb-3">
            {t("settings.llmApiKeyHeading")}
          </h3>
          <div className="flex gap-2">
            <div className="relative flex-1">
              <input
                type={showApiKey ? "text" : "password"}
                value={llmApiKey}
                onChange={(e) => setLlmApiKey(e.target.value)}
                placeholder={t("settings.llmApiKeyPlaceholder")}
                className="min-h-10 w-full rounded-lg border border-gray-700 bg-gray-850 px-3 py-2 pr-10 text-sm text-gray-100 outline-none focus:border-accent placeholder:text-gray-600"
              />
              <button
                type="button"
                onClick={() => setShowApiKey(!showApiKey)}
                className="absolute right-1 top-1/2 inline-flex min-h-10 min-w-10 -translate-y-1/2 items-center justify-center rounded-lg text-gray-600 hover:bg-gray-800/50 hover:text-gray-300"
              >
                {showApiKey ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
              </button>
            </div>
            <button
              onClick={handleApiKeySave}
              disabled={saving || !llmApiKey.trim()}
              className="min-h-10 px-4 py-2 text-sm rounded-lg bg-accent text-white hover:bg-accent-dark disabled:opacity-40 transition-colors"
            >
              {t("common.save")}
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
              {config.has_llm_api_key ? t("settings.llmApiKeyConfigured") : t("settings.llmApiKeyMissing")}
            </span>
          </div>
          <p className="text-xs text-gray-600 mt-1">
            {t("settings.llmApiKeyHint")}
          </p>

          <div className="mt-3 flex items-center gap-3">
            <button
              onClick={handleTestLlm}
              disabled={testing || !config.has_llm_api_key}
              className="min-h-10 px-3 py-1.5 text-xs rounded-lg border border-gray-700 bg-gray-850 text-gray-200 hover:bg-gray-800 disabled:opacity-40 transition-colors"
            >
              {testing ? t("settings.testing") : t("settings.testConnection")}
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
            <h3 className="text-sm font-medium text-gray-300 mb-2">{t("settings.embeddingModel")}</h3>
            <p className="text-sm text-gray-500 font-mono">{config.embedding_model}</p>
          </section>
        )}

        <McpConnectionInfo />

        <section className="border-t border-white/5 pt-6">
          <h3 className="text-sm font-medium text-gray-300 mb-3">{t("settings.account")}</h3>
          <button
            onClick={() => logout()}
            className="flex min-h-10 items-center gap-2 px-4 py-2 text-sm text-red-400 hover:bg-red-400/10 rounded-lg transition-colors"
          >
            <Icon name="logout" size={18} />
            <span>{t("nav.signOut")}</span>
          </button>
        </section>
      </div>
    </div>
  );
}

function McpConnectionInfo() {
  const [copied, setCopied] = useState<string | null>(null);

  const sseUrl = `${window.location.origin}/api/mcp/sse`;
  const claudeDesktopConfig = JSON.stringify(
    {
      mcpServers: {
        bsage: {
          command: "bsage-mcp",
        },
      },
    },
    null,
    2,
  );

  const copy = async (key: string, text: string) => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(key);
      window.setTimeout(() => setCopied((k) => (k === key ? null : k)), 1500);
    } catch {
      // clipboard blocked — user can copy manually
    }
  };

  return (
    <section className="border-t border-white/5 pt-6">
      <h3 className="text-sm font-medium text-gray-300 mb-3">MCP Server</h3>
      <p className="text-xs text-gray-500 mb-3">
        BSage exposes its tools through the standard Model Context Protocol so
        Claude Desktop, Cursor and other MCP-aware clients can read and write
        the vault.
      </p>

      <div className="space-y-3">
        <div>
          <div className="text-xs text-gray-400 mb-1.5">stdio (Claude Desktop, Cursor local)</div>
          <div className="flex items-center gap-2">
            <code className="flex-1 min-h-10 inline-flex items-center px-3 py-2 text-xs font-mono text-gray-200 bg-gray-850 border border-gray-700 rounded-lg">
              bsage-mcp
            </code>
            <button
              onClick={() => copy("cmd", "bsage-mcp")}
              className="min-h-10 px-3 py-2 text-xs rounded-lg border border-gray-700 bg-gray-850 text-gray-200 hover:bg-gray-800 transition-colors"
            >
              {copied === "cmd" ? "Copied" : "Copy"}
            </button>
          </div>
        </div>

        <div>
          <div className="text-xs text-gray-400 mb-1.5">Claude Desktop config snippet</div>
          <pre className="text-xs font-mono text-gray-200 bg-gray-850 border border-gray-700 rounded-lg p-3 overflow-x-auto">
            {claudeDesktopConfig}
          </pre>
          <button
            onClick={() => copy("json", claudeDesktopConfig)}
            className="mt-2 min-h-10 px-3 py-1.5 text-xs rounded-lg border border-gray-700 bg-gray-850 text-gray-200 hover:bg-gray-800 transition-colors"
          >
            {copied === "json" ? "Copied" : "Copy JSON"}
          </button>
        </div>

        <div>
          <div className="text-xs text-gray-400 mb-1.5">SSE endpoint (remote clients)</div>
          <div className="flex items-center gap-2">
            <code className="flex-1 min-h-10 inline-flex items-center px-3 py-2 text-xs font-mono text-gray-200 bg-gray-850 border border-gray-700 rounded-lg break-all">
              {sseUrl}
            </code>
            <button
              onClick={() => copy("sse", sseUrl)}
              className="min-h-10 px-3 py-2 text-xs rounded-lg border border-gray-700 bg-gray-850 text-gray-200 hover:bg-gray-800 transition-colors"
            >
              {copied === "sse" ? "Copied" : "Copy"}
            </button>
          </div>
          <p className="text-[10px] text-gray-600 mt-1.5">
            EventSource cannot send Authorization headers — append{" "}
            <code className="text-gray-400">?token=&lt;jwt&gt;</code> for browser clients.
          </p>
        </div>
      </div>
    </section>
  );
}
