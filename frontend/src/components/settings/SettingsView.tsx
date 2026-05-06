import { Eye, EyeOff } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { api } from "../../api/client";
import type { LlmTestResult, RuntimeConfig } from "../../api/types";
import { useAuth } from "../../hooks/useAuth";
import { Icon } from "../common/Icon";
import { Toggle } from "../common/Toggle";
import { McpServerSetupModal } from "../plugins/McpServerSetupModal";

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
  // Embedding (slice 5+): runtime-mutable so admins can point at a local
  // Ollama (e.g. http://bsserver:11434) without redeploy.
  const [embeddingModel, setEmbeddingModel] = useState("");
  const [embeddingApiBase, setEmbeddingApiBase] = useState("");
  const [embeddingApiKey, setEmbeddingApiKey] = useState("");
  const [showEmbeddingApiKey, setShowEmbeddingApiKey] = useState(false);

  const refreshConfig = useCallback(async () => {
    setLoading(true);
    setLoadError(null);
    try {
      const c = await api.getConfig();
      setConfig(c);
      setLlmModel(c.llm_model);
      setLlmApiBase(c.llm_api_base ?? "");
      setEmbeddingModel(c.embedding_model ?? "");
      setEmbeddingApiBase(c.embedding_api_base ?? "");
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

  const handleEmbeddingModelSave = useCallback(async () => {
    setSaving(true);
    try {
      const updated = await api.updateConfig({
        embedding_model: embeddingModel.trim(),
      });
      setConfig(updated);
    } finally {
      setSaving(false);
    }
  }, [embeddingModel]);

  const handleEmbeddingApiBaseSave = useCallback(async () => {
    setSaving(true);
    try {
      const updated = await api.updateConfig({
        embedding_api_base: embeddingApiBase.trim() || null,
      });
      setConfig(updated);
      setEmbeddingApiBase(updated.embedding_api_base ?? "");
    } finally {
      setSaving(false);
    }
  }, [embeddingApiBase]);

  const handleEmbeddingApiKeySave = useCallback(async () => {
    if (!embeddingApiKey.trim()) return;
    setSaving(true);
    try {
      const updated = await api.updateConfig({
        embedding_api_key: embeddingApiKey.trim(),
      });
      setConfig(updated);
      setEmbeddingApiKey("");
      setShowEmbeddingApiKey(false);
    } finally {
      setSaving(false);
    }
  }, [embeddingApiKey]);

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

        <section className="border-t border-white/5 pt-6">
          <h3 className="text-sm font-medium text-gray-300 mb-3">
            {t("settings.embeddingModel", "Embedding model")}
          </h3>
          <div className="flex gap-2">
            <input
              type="text"
              value={embeddingModel}
              onChange={(e) => setEmbeddingModel(e.target.value)}
              placeholder="e.g. ollama/nomic-embed-text"
              className="min-h-10 flex-1 rounded-lg border border-gray-700 bg-gray-850 px-3 py-2 text-sm text-gray-100 outline-none focus:border-accent placeholder:text-gray-600"
            />
            <button
              onClick={handleEmbeddingModelSave}
              disabled={saving || embeddingModel === (config.embedding_model ?? "")}
              className="min-h-10 px-4 py-2 text-sm rounded-lg bg-accent text-white hover:bg-accent-dark disabled:opacity-40 transition-colors"
            >
              {t("common.save")}
            </button>
          </div>
          <p className="text-xs text-gray-600 mt-1">
            Used by the canonicalization balanced proposer + vector
            search. Empty disables both.
          </p>
        </section>

        <section>
          <h3 className="text-sm font-medium text-gray-300 mb-3">
            Embedding API base
          </h3>
          <div className="flex gap-2">
            <input
              type="text"
              value={embeddingApiBase}
              onChange={(e) => setEmbeddingApiBase(e.target.value)}
              placeholder="http://bsserver:11434 (Ollama via Tailscale)"
              className="min-h-10 flex-1 rounded-lg border border-gray-700 bg-gray-850 px-3 py-2 text-sm text-gray-100 outline-none focus:border-accent placeholder:text-gray-600"
            />
            <button
              onClick={handleEmbeddingApiBaseSave}
              disabled={
                saving || embeddingApiBase === (config.embedding_api_base ?? "")
              }
              className="min-h-10 px-4 py-2 text-sm rounded-lg bg-accent text-white hover:bg-accent-dark disabled:opacity-40 transition-colors"
            >
              {t("common.save")}
            </button>
          </div>
          <p className="text-xs text-gray-600 mt-1">
            Override for self-hosted Ollama / OpenAI-compatible servers.
          </p>
        </section>

        <section>
          <h3 className="text-sm font-medium text-gray-300 mb-3">
            Embedding API key
          </h3>
          <div className="flex gap-2">
            <div className="relative flex-1">
              <input
                type={showEmbeddingApiKey ? "text" : "password"}
                value={embeddingApiKey}
                onChange={(e) => setEmbeddingApiKey(e.target.value)}
                placeholder="paste once; stored encrypted"
                className="min-h-10 w-full rounded-lg border border-gray-700 bg-gray-850 px-3 py-2 pr-10 text-sm text-gray-100 outline-none focus:border-accent placeholder:text-gray-600"
              />
              <button
                type="button"
                onClick={() => setShowEmbeddingApiKey(!showEmbeddingApiKey)}
                className="absolute right-1 top-1/2 inline-flex min-h-10 min-w-10 -translate-y-1/2 items-center justify-center rounded-lg text-gray-600 hover:bg-gray-800/50 hover:text-gray-300"
              >
                {showEmbeddingApiKey ? (
                  <EyeOff className="w-4 h-4" />
                ) : (
                  <Eye className="w-4 h-4" />
                )}
              </button>
            </div>
            <button
              onClick={handleEmbeddingApiKeySave}
              disabled={saving || !embeddingApiKey.trim()}
              className="min-h-10 px-4 py-2 text-sm rounded-lg bg-accent text-white hover:bg-accent-dark disabled:opacity-40 transition-colors"
            >
              {t("common.save")}
            </button>
          </div>
          <div className="flex items-center gap-1.5 mt-2">
            <span
              className={`w-2 h-2 rounded-full ${
                config.has_embedding_api_key ? "bg-accent" : "bg-amber-500"
              }`}
            />
            <span className="text-xs text-gray-500">
              {config.has_embedding_api_key
                ? "Configured"
                : "Not set (leave empty for local Ollama)"}
            </span>
          </div>
        </section>

        <McpServerSection />

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

function McpServerSection() {
  const [open, setOpen] = useState(false);
  const [keyCount, setKeyCount] = useState<number | null>(null);

  useEffect(() => {
    // setTimeout(0) defers setState out of the synchronous effect body —
    // satisfies React 19's set-state-in-effect rule.
    const id = window.setTimeout(() => {
      api.mcpKeys
        .list()
        .then((ks) => setKeyCount(ks.length))
        .catch(() => setKeyCount(0));
    }, 0);
    return () => window.clearTimeout(id);
  }, [open]);

  const status =
    keyCount === null
      ? "Loading…"
      : keyCount === 0
        ? "No keys yet"
        : `${keyCount} active key${keyCount === 1 ? "" : "s"}`;

  return (
    <>
      <section
        data-testid="mcp-server-section"
        className="border-t border-white/5 pt-6"
      >
        <h3 className="text-sm font-medium text-gray-300 mb-3">MCP Server</h3>
        <p className="text-xs text-gray-500 mb-4">
          Let Claude Desktop, Cursor, Codex CLI and other AI clients use your
          BSage vault — search, read notes, run import plugins. MCP is the
          inbound channel for external AI; for outbound integrations
          (Slack, email, etc.) use Plugins.
        </p>
        <div className="flex items-center justify-between gap-4 px-4 py-3 rounded-lg bg-surface-container-low border border-white/5">
          <div className="flex items-center gap-2 min-w-0">
            <span
              className={`w-2 h-2 rounded-full shrink-0 ${
                keyCount && keyCount > 0 ? "bg-accent-light" : "bg-gray-500"
              }`}
            />
            <span className="text-xs text-gray-300 truncate">{status}</span>
          </div>
          <button
            onClick={() => setOpen(true)}
            className="min-h-10 inline-flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-lg bg-accent-light/15 text-accent-light hover:bg-accent-light/25 transition-colors font-bold"
          >
            <Icon name="settings" size={14} />
            Manage keys & connect
          </button>
        </div>
      </section>

      {open && <McpServerSetupModal onClose={() => setOpen(false)} />}
    </>
  );
}
