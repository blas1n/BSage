import { Eye, EyeOff } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { useT } from "@bsvibe/i18n";
import { api } from "../../api/client";
import type { ConfigUpdate, LlmTestResult, RuntimeConfig } from "../../api/types";
import { useAuth } from "../../hooks/useAuth";
import { Icon } from "../common/Icon";
import { Toggle } from "../common/Toggle";
import { McpServerSetupModal } from "../plugins/McpServerSetupModal";

export function SettingsView() {
  const t = useT("sage");
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
      <h1 className="text-4xl font-extrabold tracking-tight mb-6 text-on-surface font-headline">
        {t("settings.title")}
      </h1>

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
            {t("settings.embeddingModel")}
          </h3>
          <div className="flex gap-2">
            <input
              type="text"
              value={embeddingModel}
              onChange={(e) => setEmbeddingModel(e.target.value)}
              placeholder={t("settings.embeddingModelPlaceholder")}
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
            {t("settings.embeddingModelHint")}
          </p>
        </section>

        <section>
          <h3 className="text-sm font-medium text-gray-300 mb-3">
            {t("settings.embeddingApiBaseHeading")}
          </h3>
          <div className="flex gap-2">
            <input
              type="text"
              value={embeddingApiBase}
              onChange={(e) => setEmbeddingApiBase(e.target.value)}
              placeholder={t("settings.embeddingApiBasePlaceholder")}
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
            {t("settings.embeddingApiBaseHint")}
          </p>
        </section>

        <section>
          <h3 className="text-sm font-medium text-gray-300 mb-3">
            {t("settings.embeddingApiKeyHeading")}
          </h3>
          <div className="flex gap-2">
            <div className="relative flex-1">
              <input
                type={showEmbeddingApiKey ? "text" : "password"}
                value={embeddingApiKey}
                onChange={(e) => setEmbeddingApiKey(e.target.value)}
                placeholder={t("settings.embeddingApiKeyPlaceholder")}
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
                ? t("settings.embeddingApiKeyConfigured")
                : t("settings.embeddingApiKeyMissing")}
            </span>
          </div>
        </section>

        <McpServerSection />

        <CanonicalizationSection
          config={config}
          saving={saving}
          onChange={(updated) => setConfig(updated)}
        />

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
  const t = useT("sage");
  const [open, setOpen] = useState(false);

  return (
    <>
      <section
        data-testid="mcp-server-section"
        className="border-t border-white/5 pt-6"
      >
        <h3 className="text-sm font-medium text-gray-300 mb-3">{t("settings.mcpHeading")}</h3>
        <p className="text-xs text-gray-500 mb-4">
          {t("settings.mcpDescription")}
        </p>
        <button
          onClick={() => setOpen(true)}
          className="min-h-10 inline-flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-lg bg-accent-light/15 text-accent-light hover:bg-accent-light/25 transition-colors font-bold"
        >
          <Icon name="settings" size={14} />
          {t("settings.mcpManage")}
        </button>
      </section>

      {open && <McpServerSetupModal onClose={() => setOpen(false)} />}
    </>
  );
}

interface CanonicalizationSectionProps {
  config: RuntimeConfig | null;
  saving: boolean;
  onChange: (updated: RuntimeConfig) => void;
}

function CanonicalizationSection({ config, saving, onChange }: CanonicalizationSectionProps) {
  const t = useT("sage");
  const [busy, setBusy] = useState(false);
  const [expireCron, setExpireCron] = useState(config?.canon_expire_cron ?? "0 * * * *");
  const [lintCron, setLintCron] = useState(config?.canon_lint_cron ?? "0 0 * * 0");

  useEffect(() => {
    let cancelled = false;
    queueMicrotask(() => {
      if (cancelled) return;
      if (config?.canon_expire_cron) setExpireCron(config.canon_expire_cron);
      if (config?.canon_lint_cron) setLintCron(config.canon_lint_cron);
    });
    return () => {
      cancelled = true;
    };
  }, [config?.canon_expire_cron, config?.canon_lint_cron]);

  const patch = useCallback(async (body: ConfigUpdate) => {
    setBusy(true);
    try {
      const updated = await api.updateConfig(body);
      onChange(updated);
    } finally {
      setBusy(false);
    }
  }, [onChange]);

  const disabled = busy || saving || config === null;

  return (
    <section className="border-t border-white/5 pt-6">
      <h3 className="text-sm font-medium text-gray-300 mb-3">{t("settings.canonHeading")}</h3>
      <p className="text-xs text-gray-500 mb-4">
        {t("settings.canonDescription")}
      </p>
      <div className="space-y-4">
        <div className="flex items-center justify-between gap-4">
          <div>
            <div className="text-sm text-gray-200">canon-watcher</div>
            <div className="text-xs text-gray-500">{t("settings.canonWatcherDescription")}</div>
          </div>
          <Toggle
            checked={Boolean(config?.canon_watcher_enabled)}
            onChange={(checked) => patch({ canon_watcher_enabled: checked })}
            label="canon-watcher"
            disabled={disabled}
          />
        </div>
        <div className="flex items-center justify-between gap-4">
          <div>
            <div className="text-sm text-gray-200">canon-expire</div>
            <div className="text-xs text-gray-500">{t("settings.canonExpireDescription")}</div>
          </div>
          <Toggle
            checked={Boolean(config?.canon_expire_enabled)}
            onChange={(checked) => patch({ canon_expire_enabled: checked })}
            label="canon-expire"
            disabled={disabled}
          />
        </div>
        <div className="flex items-center gap-2">
          <label className="text-xs text-gray-500 w-28">{t("settings.canonExpireCron")}</label>
          <input
            type="text"
            value={expireCron}
            onChange={(e) => setExpireCron(e.target.value)}
            placeholder="0 * * * *"
            className="flex-1 min-h-10 px-3 py-2 bg-bg-elevated border border-white/10 rounded-lg text-sm text-gray-200 font-mono"
            disabled={disabled}
          />
          <button
            type="button"
            onClick={() => patch({ canon_expire_cron: expireCron.trim() || "0 * * * *" })}
            disabled={disabled || !expireCron.trim()}
            className="min-h-10 px-3 py-2 text-xs bg-accent-light/15 text-accent-light rounded-lg hover:bg-accent-light/25 transition-colors disabled:opacity-50"
          >
            {t("common.save")}
          </button>
        </div>
        <div className="flex items-center justify-between gap-4">
          <div>
            <div className="text-sm text-gray-200">canon-lint</div>
            <div className="text-xs text-gray-500">{t("settings.canonLintDescription")}</div>
          </div>
          <Toggle
            checked={Boolean(config?.canon_lint_enabled)}
            onChange={(checked) => patch({ canon_lint_enabled: checked })}
            label="canon-lint"
            disabled={disabled}
          />
        </div>
        <div className="flex items-center gap-2">
          <label className="text-xs text-gray-500 w-28">{t("settings.canonLintCron")}</label>
          <input
            type="text"
            value={lintCron}
            onChange={(e) => setLintCron(e.target.value)}
            placeholder="0 0 * * 0"
            className="flex-1 min-h-10 px-3 py-2 bg-bg-elevated border border-white/10 rounded-lg text-sm text-gray-200 font-mono"
            disabled={disabled}
          />
          <button
            type="button"
            onClick={() => patch({ canon_lint_cron: lintCron.trim() || "0 0 * * 0" })}
            disabled={disabled || !lintCron.trim()}
            className="min-h-10 px-3 py-2 text-xs bg-accent-light/15 text-accent-light rounded-lg hover:bg-accent-light/25 transition-colors disabled:opacity-50"
          >
            {t("common.save")}
          </button>
        </div>
      </div>
    </section>
  );
}
