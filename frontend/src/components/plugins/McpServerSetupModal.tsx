"use client";

import { useCallback, useMemo, useState } from "react";
import { useT } from "@bsvibe/i18n";
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

/** Placeholder for the bearer token in the connection snippet. BSage's MCP
 * server verifies the token through `bsvibe-authz` (Supabase JWKS /
 * introspection) — it is the same BSVibe access token a user signs in
 * with. BSage issues no MCP keys of its own. */
const TOKEN_PLACEHOLDER = "<your-bsvibe-token>";

function isHostedDeployment(): boolean {
  if (typeof window === "undefined") return false;
  const h = window.location.hostname;
  return h !== "localhost" && h !== "127.0.0.1" && !h.endsWith(".local");
}

/** BSage serves the Streamable HTTP MCP transport at `/mcp`. On hosted
 * deployments the API lives on the `api-` subdomain. */
function mcpUrlFor(): string {
  const origin = typeof window === "undefined" ? "" : window.location.origin;
  return isHostedDeployment()
    ? `${origin.replace("//", "//api-")}/mcp`
    : `${origin}/mcp`;
}

function snippetFor(kind: ClientKind, mcpUrl: string): string {
  // Cursor and Claude Desktop both speak Streamable HTTP natively — a
  // remote MCP server is configured with a `url` + auth header.
  if (kind === "cursor" || kind === "claude-desktop") {
    return JSON.stringify(
      {
        mcpServers: {
          bsage: {
            url: mcpUrl,
            headers: { Authorization: `Bearer ${TOKEN_PLACEHOLDER}` },
          },
        },
      },
      null,
      2,
    );
  }
  return [
    `HTTP URL:  ${mcpUrl}`,
    `Header:    Authorization: Bearer ${TOKEN_PLACEHOLDER}`,
  ].join("\n");
}

export interface McpServerSetupModalProps {
  onClose: () => void;
}

/**
 * Connection guide for pointing an external AI client (Cursor, Claude
 * Desktop, Codex CLI, …) at BSage's Streamable HTTP MCP server.
 *
 * MCP requests authenticate with a BSVibe access token via `bsvibe-authz`
 * — BSage issues no MCP keys of its own, so this modal is a static guide,
 * not a key-management surface.
 */
export function McpServerSetupModal({ onClose }: McpServerSetupModalProps) {
  const t = useT("sage");
  const [client, setClient] = useState<ClientKind>("cursor");
  const [copied, setCopied] = useState(false);

  const mcpUrl = useMemo(() => mcpUrlFor(), []);
  const snippet = useMemo(() => snippetFor(client, mcpUrl), [client, mcpUrl]);

  const copySnippet = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(snippet);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      // clipboard blocked
    }
  }, [snippet]);

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
            <p className="text-xs text-gray-400 mt-1">{t("mcp.subtitle")}</p>
          </div>
          <button
            onClick={onClose}
            className="text-gray-500 hover:text-gray-300"
            aria-label={t("common.close")}
          >
            <Icon name="close" size={20} />
          </button>
        </div>

        {/* Token note — where the bearer token comes from. */}
        <section
          data-testid="mcp-token-note"
          className="mb-5 px-3 py-3 rounded-lg border border-white/5 bg-surface-container-low"
        >
          <p className="text-xs text-gray-300">{t("mcp.tokenNote")}</p>
        </section>

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
              onClick={copySnippet}
              className="min-h-10 px-3 py-1.5 text-xs rounded-lg border border-gray-700 bg-gray-850 text-gray-200 hover:bg-gray-800"
            >
              {copied ? t("mcp.copied") : t("mcp.copySnippet")}
            </button>
          </div>
        </section>
      </div>
    </div>
  );
}
