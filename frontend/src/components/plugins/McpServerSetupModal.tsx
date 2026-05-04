"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../../api/client";
import type { MCPAPIKey } from "../../api/types";
import { Icon } from "../common/Icon";

type ClientKind = "cursor" | "claude-desktop" | "generic";

const CLIENT_LABELS: Record<ClientKind, string> = {
  cursor: "Cursor",
  "claude-desktop": "Claude Desktop",
  generic: "Generic SSE",
};

function isHostedDeployment(): boolean {
  if (typeof window === "undefined") return false;
  const h = window.location.hostname;
  return h !== "localhost" && h !== "127.0.0.1" && !h.endsWith(".local");
}

function sseUrlFor(): string {
  const origin = typeof window === "undefined" ? "" : window.location.origin;
  return isHostedDeployment()
    ? `${origin.replace("//", "//api-")}/mcp/sse`
    : `${origin}/mcp/sse`;
}

function snippetFor(kind: ClientKind, sseUrl: string, token: string): string {
  if (kind === "cursor") {
    return JSON.stringify(
      {
        mcpServers: {
          bsage: {
            url: sseUrl,
            headers: { Authorization: `Bearer ${token}` },
          },
        },
      },
      null,
      2,
    );
  }
  if (kind === "claude-desktop") {
    return JSON.stringify(
      {
        mcpServers: {
          bsage: {
            command: "uvx",
            args: [
              "mcp-proxy",
              "--headers",
              "Authorization",
              `Bearer ${token}`,
              sseUrl,
            ],
          },
        },
      },
      null,
      2,
    );
  }
  return [`SSE URL:  ${sseUrl}`, `Header:   Authorization: Bearer ${token}`].join("\n");
}

function relTime(iso: string | null): string {
  if (!iso) return "never used";
  const d = new Date(iso).getTime();
  if (Number.isNaN(d)) return iso;
  const diff = Date.now() - d;
  const m = Math.floor(diff / 60000);
  if (m < 1) return "just now";
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  const days = Math.floor(h / 24);
  return `${days}d ago`;
}

export interface McpServerSetupModalProps {
  onClose: () => void;
}

export function McpServerSetupModal({ onClose }: McpServerSetupModalProps) {
  const [keys, setKeys] = useState<MCPAPIKey[]>([]);
  const [loading, setLoading] = useState(true);
  const [name, setName] = useState("");
  const [generating, setGenerating] = useState(false);
  const [revokeBusy, setRevokeBusy] = useState<string | null>(null);
  const [freshToken, setFreshToken] = useState<string | null>(null);
  const [client, setClient] = useState<ClientKind>("cursor");
  const [copied, setCopied] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const sseUrl = useMemo(() => sseUrlFor(), []);

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
  const snippet = snippetFor(client, sseUrl, tokenForSnippet);

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
            <h2 className="font-headline font-bold text-on-surface text-lg">BSage MCP Server</h2>
            <p className="text-xs text-gray-400 mt-1">
              Issue an API key, paste the snippet into your AI client, done.
            </p>
          </div>
          <button
            onClick={onClose}
            className="text-gray-500 hover:text-gray-300"
            aria-label="Close"
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
            Active keys{" "}
            <span className="text-gray-500">({loading ? "…" : keys.length})</span>
          </div>
          {!loading && keys.length === 0 && (
            <p className="text-xs text-gray-500 italic">
              No keys yet — generate one below.
            </p>
          )}
          <div className="space-y-2">
            {keys.map((k) => (
              <div
                key={k.id}
                className="flex items-center justify-between px-3 py-2 rounded-lg border border-white/5 bg-surface-container-low"
              >
                <div className="min-w-0 flex-1">
                  <div className="text-sm text-on-surface truncate">{k.name}</div>
                  <div className="text-[10px] text-gray-500 font-mono">
                    {relTime(k.last_used_at)} · created {relTime(k.created_at)}
                  </div>
                </div>
                <button
                  onClick={() => onRevoke(k.id)}
                  disabled={revokeBusy === k.id}
                  className="ml-3 min-h-10 px-3 py-1 text-xs rounded-lg text-red-300 hover:bg-red-400/10 disabled:opacity-40"
                >
                  {revokeBusy === k.id ? "…" : "Revoke"}
                </button>
              </div>
            ))}
          </div>
        </section>

        {/* Generate */}
        <section className="mb-5">
          <div className="text-xs font-medium text-gray-300 mb-2">Generate new key</div>
          <div className="flex gap-2">
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && void onGenerate()}
              placeholder="Name (e.g. cursor-laptop)"
              className="flex-1 min-h-10 rounded-lg border border-gray-700 bg-gray-850 px-3 py-2 text-sm text-on-surface outline-none focus:border-accent-light placeholder:text-gray-500"
              maxLength={80}
            />
            <button
              onClick={onGenerate}
              disabled={!name.trim() || generating}
              className="min-h-10 px-4 py-2 text-sm rounded-lg bg-accent-light text-gray-950 font-bold disabled:opacity-40"
            >
              {generating ? "…" : "+ Generate"}
            </button>
          </div>
        </section>

        {/* Fresh token (one-time display) */}
        {freshToken && (
          <section className="mb-5 px-3 py-3 rounded-lg border border-amber-400/30 bg-amber-400/5">
            <div className="text-xs font-medium text-amber-200 mb-1.5">
              ⚠ Copy this token now — it won't be shown again
            </div>
            <div className="flex items-center gap-2">
              <code className="flex-1 min-h-10 inline-flex items-center px-3 py-2 text-xs font-mono text-on-surface bg-gray-850 border border-gray-700 rounded-lg break-all">
                {freshToken}
              </code>
              <button
                onClick={() => copy("token", freshToken)}
                className="min-h-10 px-3 py-2 text-xs rounded-lg border border-gray-700 bg-gray-850 text-gray-200 hover:bg-gray-800"
              >
                {copied === "token" ? "Copied" : "Copy"}
              </button>
            </div>
          </section>
        )}

        {/* Connect */}
        <section>
          <div className="text-xs font-medium text-gray-300 mb-2">Connect — pick your client</div>
          <div className="flex gap-1 mb-2">
            {(Object.keys(CLIENT_LABELS) as ClientKind[]).map((k) => (
              <button
                key={k}
                onClick={() => setClient(k)}
                className={`min-h-10 px-3 py-1.5 text-xs rounded-lg font-medium transition-colors ${
                  client === k
                    ? "bg-accent-light/20 text-accent-light"
                    : "text-gray-400 hover:bg-white/5"
                }`}
              >
                {CLIENT_LABELS[k]}
              </button>
            ))}
          </div>
          <pre className="text-[11px] font-mono text-gray-200 bg-gray-850 border border-gray-700 rounded-lg p-3 overflow-x-auto whitespace-pre">
            {snippet}
          </pre>
          <div className="flex items-center justify-between mt-2">
            <p className="text-[10px] text-gray-500">
              {client === "claude-desktop" && (
                <>
                  Claude Desktop is stdio-only — <code>uvx mcp-proxy</code> bridges to SSE.
                </>
              )}
              {client === "cursor" && (
                <>Edit <code>~/.cursor/mcp.json</code> (or use Cursor settings).</>
              )}
              {client === "generic" && <>For Codex CLI, custom clients.</>}
            </p>
            <button
              onClick={() => copy("snippet", snippet)}
              className="min-h-10 px-3 py-1.5 text-xs rounded-lg border border-gray-700 bg-gray-850 text-gray-200 hover:bg-gray-800"
            >
              {copied === "snippet" ? "Copied" : "Copy snippet"}
            </button>
          </div>
        </section>
      </div>
    </div>
  );
}
