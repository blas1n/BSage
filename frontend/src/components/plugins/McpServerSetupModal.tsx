"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useT } from "@bsvibe/i18n";
import { ResponsiveTable } from "@bsvibe/ui";
import type { ResponsiveTableColumn } from "@bsvibe/ui";
import { api } from "../../api/client";
import type { MCPAPIKey } from "../../api/types";
import { Icon } from "../common/Icon";

type ClientKind = "cursor" | "claude-desktop" | "generic";

/** Stable client kinds in display order. Labels come from the `mcp.client*`
 * i18n keys and are translated at the render site. */
const CLIENT_KINDS: ClientKind[] = ["cursor", "claude-desktop", "generic"];

const CLIENT_LABEL_KEYS: Record<ClientKind, string> = {
  cursor: "mcp.clientCursor",
  "claude-desktop": "mcp.clientClaudeDesktop",
  generic: "mcp.clientGeneric",
};

type Translate = ReturnType<typeof useT>;

function isHostedDeployment(): boolean {
  if (typeof window === "undefined") return false;
  const h = window.location.hostname;
  return h !== "localhost" && h !== "127.0.0.1" && !h.endsWith(".local");
}

/** BSage serves the Streamable HTTP MCP transport at `/mcp` (the legacy
 * SSE transport at `/mcp/sse` was removed). On hosted deployments the API
 * lives on the `api-` subdomain. */
function mcpUrlFor(): string {
  const origin = typeof window === "undefined" ? "" : window.location.origin;
  return isHostedDeployment()
    ? `${origin.replace("//", "//api-")}/mcp`
    : `${origin}/mcp`;
}

function snippetFor(kind: ClientKind, mcpUrl: string, token: string): string {
  // Cursor and Claude Desktop both speak Streamable HTTP natively — a
  // remote MCP server is configured with a `url` + auth header. No stdio
  // bridge (mcp-proxy) is needed since the SSE-transport migration.
  if (kind === "cursor" || kind === "claude-desktop") {
    return JSON.stringify(
      {
        mcpServers: {
          bsage: {
            url: mcpUrl,
            headers: { Authorization: `Bearer ${token}` },
          },
        },
      },
      null,
      2,
    );
  }
  return [`HTTP URL:  ${mcpUrl}`, `Header:    Authorization: Bearer ${token}`].join("\n");
}

function relTime(iso: string | null, t: Translate): string {
  if (!iso) return t("mcp.neverUsed");
  const d = new Date(iso).getTime();
  if (Number.isNaN(d)) return iso;
  const diff = Date.now() - d;
  const m = Math.floor(diff / 60000);
  if (m < 1) return t("time.justNow");
  if (m < 60) return t("time.minutesAgo", { count: m });
  const h = Math.floor(m / 60);
  if (h < 24) return t("time.hoursAgo", { count: h });
  const days = Math.floor(h / 24);
  return t("time.daysAgo", { count: days });
}

export interface McpServerSetupModalProps {
  onClose: () => void;
}

export function McpServerSetupModal({ onClose }: McpServerSetupModalProps) {
  const t = useT("sage");
  const [keys, setKeys] = useState<MCPAPIKey[]>([]);
  const [loading, setLoading] = useState(true);
  const [name, setName] = useState("");
  const [generating, setGenerating] = useState(false);
  const [revokeBusy, setRevokeBusy] = useState<string | null>(null);
  const [freshToken, setFreshToken] = useState<string | null>(null);
  const [client, setClient] = useState<ClientKind>("cursor");
  const [copied, setCopied] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const mcpUrl = useMemo(() => mcpUrlFor(), []);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      setKeys(await api.mcpKeys.list());
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    // setTimeout(0) defers the setState path out of the effect's synchronous
    // body — satisfies React 19's set-state-in-effect rule.
    const id = window.setTimeout(() => void refresh(), 0);
    return () => window.clearTimeout(id);
  }, [refresh]);

  const onGenerate = useCallback(async () => {
    if (!name.trim()) return;
    setGenerating(true);
    setError(null);
    try {
      const issued = await api.mcpKeys.create(name.trim());
      setFreshToken(issued.token);
      setName("");
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setGenerating(false);
    }
  }, [name, refresh]);

  const onRevoke = useCallback(
    async (id: string) => {
      setRevokeBusy(id);
      try {
        await api.mcpKeys.revoke(id);
        if (keys.find((k) => k.id === id) && freshToken) {
          // The fresh token shown belongs to this key — clear it
          setFreshToken(null);
        }
        await refresh();
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      } finally {
        setRevokeBusy(null);
      }
    },
    [keys, freshToken, refresh],
  );

  const copy = useCallback(async (key: string, text: string) => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(key);
      window.setTimeout(() => setCopied((k) => (k === key ? null : k)), 1500);
    } catch {
      // clipboard blocked
    }
  }, []);

  const tokenForSnippet = freshToken ?? "<paste-token-here>";
  const snippet = snippetFor(client, mcpUrl, tokenForSnippet);

  // Active-keys table columns. Desktop renders a real <table>; mobile keeps
  // the original two-line card via renderMobileCard. Revoke behaviour and
  // the per-key busy state are preserved.
  const keyColumns = useMemo<ResponsiveTableColumn<MCPAPIKey>[]>(
    () => [
      {
        key: "key",
        header: t("mcp.col.key"),
        cell: (k) => (
          <span className="text-sm text-on-surface">{k.name}</span>
        ),
      },
      {
        key: "status",
        header: t("mcp.col.status"),
        cell: (k) => (
          <span className="text-[10px] text-gray-500 font-mono">
            {relTime(k.last_used_at, t)} ·{" "}
            {t("mcp.createdAt", { time: relTime(k.created_at, t) })}
          </span>
        ),
      },
      {
        key: "actions",
        header: t("mcp.col.actions"),
        cellClassName: "text-right",
        cell: (k) => (
          <button
            onClick={() => onRevoke(k.id)}
            disabled={revokeBusy === k.id}
            className="min-h-8 px-3 py-1 text-xs rounded-lg text-red-300 hover:bg-red-400/10 disabled:opacity-40"
          >
            {revokeBusy === k.id ? "…" : t("mcp.revoke")}
          </button>
        ),
      },
    ],
    [t, revokeBusy, onRevoke],
  );

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur p-4"
      onClick={onClose}
    >
      <div
        className="w-full max-w-2xl max-h-[90vh] overflow-y-auto rounded-xl bg-surface border border-white/10 p-6"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between mb-4">
          <div>
            <h2 className="font-headline font-bold text-on-surface text-lg">{t("mcp.title")}</h2>
            <p className="text-xs text-gray-400 mt-1">
              {t("mcp.subtitle")}
            </p>
          </div>
          <button
            onClick={onClose}
            className="text-gray-500 hover:text-gray-300"
            aria-label={t("common.close")}
          >
            <Icon name="close" size={20} />
          </button>
        </div>

        {error && (
          <div className="mb-3 px-3 py-2 rounded-lg border border-red-400/30 bg-red-400/10 text-xs text-red-300 break-words">
            {error}
          </div>
        )}

        {/* Active keys */}
        <section className="mb-5">
          <div className="text-xs font-medium text-gray-300 mb-2">
            {t("mcp.activeKeys")}{" "}
            <span className="text-gray-500">({loading ? "…" : keys.length})</span>
          </div>
          {!loading && (
            <ResponsiveTable<MCPAPIKey>
              columns={keyColumns}
              rows={keys}
              rowKey={(k) => k.id}
              emptyMessage={
                <span className="italic">{t("mcp.noKeysHint")}</span>
              }
              renderMobileCard={(k) => (
                <div
                  data-testid="bsvibe-table-card"
                  className="flex items-center justify-between px-3 py-2 rounded-lg border border-white/5 bg-surface-container-low"
                >
                  <div className="min-w-0 flex-1">
                    <div className="text-sm text-on-surface truncate">{k.name}</div>
                    <div className="text-[10px] text-gray-500 font-mono">
                      {relTime(k.last_used_at, t)} ·{" "}
                      {t("mcp.createdAt", { time: relTime(k.created_at, t) })}
                    </div>
                  </div>
                  <button
                    onClick={() => onRevoke(k.id)}
                    disabled={revokeBusy === k.id}
                    className="ml-3 min-h-10 px-3 py-1 text-xs rounded-lg text-red-300 hover:bg-red-400/10 disabled:opacity-40"
                  >
                    {revokeBusy === k.id ? "…" : t("mcp.revoke")}
                  </button>
                </div>
              )}
            />
          )}
        </section>

        {/* Generate */}
        <section className="mb-5">
          <div className="text-xs font-medium text-gray-300 mb-2">{t("mcp.generateHeading")}</div>
          <div className="flex gap-2">
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && void onGenerate()}
              placeholder={t("mcp.namePlaceholder")}
              className="flex-1 min-h-10 rounded-lg border border-gray-700 bg-gray-850 px-3 py-2 text-sm text-on-surface outline-none focus:border-accent-light placeholder:text-gray-500"
              maxLength={80}
            />
            <button
              onClick={onGenerate}
              disabled={!name.trim() || generating}
              className="min-h-10 px-4 py-2 text-sm rounded-lg bg-accent-light text-gray-950 font-bold disabled:opacity-40"
            >
              {generating ? "…" : t("mcp.generate")}
            </button>
          </div>
        </section>

        {/* Fresh token (one-time display) */}
        {freshToken && (
          <section className="mb-5 px-3 py-3 rounded-lg border border-amber-400/30 bg-amber-400/5">
            <div className="text-xs font-medium text-amber-200 mb-1.5">
              {t("mcp.freshTokenWarning")}
            </div>
            <div className="flex items-center gap-2">
              <code className="flex-1 min-h-10 inline-flex items-center px-3 py-2 text-xs font-mono text-on-surface bg-gray-850 border border-gray-700 rounded-lg break-all">
                {freshToken}
              </code>
              <button
                onClick={() => copy("token", freshToken)}
                className="min-h-10 px-3 py-2 text-xs rounded-lg border border-gray-700 bg-gray-850 text-gray-200 hover:bg-gray-800"
              >
                {copied === "token" ? t("mcp.copied") : t("mcp.copy")}
              </button>
            </div>
          </section>
        )}

        {/* Connect */}
        <section>
          <div className="text-xs font-medium text-gray-300 mb-2">{t("mcp.connectHeading")}</div>
          <div className="flex gap-1 mb-2">
            {CLIENT_KINDS.map((k) => (
              <button
                key={k}
                onClick={() => setClient(k)}
                className={`min-h-10 px-3 py-1.5 text-xs rounded-lg font-medium transition-colors ${
                  client === k
                    ? "bg-accent-light/20 text-accent-light"
                    : "text-gray-400 hover:bg-white/5"
                }`}
              >
                {t(CLIENT_LABEL_KEYS[k])}
              </button>
            ))}
          </div>
          <pre className="text-[11px] font-mono text-gray-200 bg-gray-850 border border-gray-700 rounded-lg p-3 overflow-x-auto whitespace-pre">
            {snippet}
          </pre>
          <div className="flex items-center justify-between mt-2">
            <p className="text-[10px] text-gray-500">
              {client === "claude-desktop" && t("mcp.hintClaudeDesktop")}
              {client === "cursor" && t("mcp.hintCursor")}
              {client === "generic" && t("mcp.hintGeneric")}
            </p>
            <button
              onClick={() => copy("snippet", snippet)}
              className="min-h-10 px-3 py-1.5 text-xs rounded-lg border border-gray-700 bg-gray-850 text-gray-200 hover:bg-gray-800"
            >
              {copied === "snippet" ? t("mcp.copied") : t("mcp.copySnippet")}
            </button>
          </div>
        </section>
      </div>
    </div>
  );
}
