import { createApiFetch, setOnAuthError } from "@bsvibe/api";

import { clearTokenCache, getAccessToken } from "../hooks/useAuth";
import type {
  ChatRequest,
  ChatResponse,
  ConfigUpdate,
  CredentialFieldsResponse,
  EntryMeta,
  MCPAPIKey,
  MCPAPIKeyIssued,
  RuntimeConfig,
  VaultBacklink,
  VaultCommunities,
  VaultFileResponse,
  VaultGraph,
  VaultSearchResult,
  VaultTags,
  VaultTreeEntry,
  LlmTestResult,
} from "./types";

const BASE = (() => {
  const raw = (
    process.env.NEXT_PUBLIC_API_URL ||
    process.env.VITE_API_URL ||
    "/api"
  ).replace(/\/+$/, "");
  return raw.endsWith("/api") ? raw : `${raw}/api`;
})();

// Phase A Batch 5: replace the bespoke ~30 LoC fetch wrapper with the shared
// `@bsvibe/api` `createApiFetch`. The shared client gives us:
//   - 401 cascading-logout latch (stops the flicker when several requests
//     fail concurrently after a session expiry)
//   - timeout + AbortSignal plumbing
//   - FastAPI {detail: ...} envelope parsing
//   - typed `ApiError` for downstream handlers
//
// Token resolution stays on BSage's existing hash-callback / localStorage
// path (`hooks/useAuth.getAccessToken`) — the cookie-SSO model that the
// shared `@bsvibe/auth` `useAuth` hook implements is a behaviour change
// and is deferred (see `frontend/src/lib/bsvibe/README.md`).
const apiClient = createApiFetch({
  baseUrl: BASE,
  getToken: () => getAccessToken(),
});

// Wire the cascading-logout guard into BSage's existing token-cache reset
// so a session expiry mid-page-load drops the cached token exactly once.
// On a real production cookie-SSO migration this would become a redirect
// to `${authUrl}/login`; for the hash-route flow we just clear the cache
// and the next render reroutes via the LandingPage component.
setOnAuthError(() => {
  try {
    clearTokenCache();
  } catch {
    /* noop — clearTokenCache only touches localStorage */
  }
});

async function request<T>(
  path: string,
  init?: RequestInit & { timeoutMs?: number },
): Promise<T> {
  // Preserve the legacy "fall back to fetch on raw RequestInit" surface
  // so existing tests and call sites that build init by hand keep working.
  const method = (init?.method ?? "GET").toUpperCase();
  const headers = (init?.headers as Record<string, string> | undefined) ?? {};
  const body = init?.body;
  const opts = init?.timeoutMs !== undefined ? { timeoutMs: init.timeoutMs } : undefined;

  return apiClient.request<T>(path, { method, headers, body }, opts);
}

export const api = {
  health: () => request<{ status: string }>("/health"),

  plugins: () => request<EntryMeta[]>("/plugins"),

  skills: () => request<EntryMeta[]>("/skills"),

  run: (name: string) =>
    request<{ name: string; results: unknown[] }>(`/run/${name}`, { method: "POST" }),

  chat: (body: ChatRequest) =>
    request<ChatResponse>("/chat", { method: "POST", body: JSON.stringify(body) }),

  getConfig: () => request<RuntimeConfig>("/config"),

  updateConfig: (update: ConfigUpdate) =>
    request<RuntimeConfig>("/config", { method: "PATCH", body: JSON.stringify(update) }),

  testLlm: () =>
    request<LlmTestResult>("/config/test-llm", { method: "POST" }),

  actions: () => request<string[]>("/vault/actions"),

  // Credential setup
  credentialFields: (name: string) =>
    request<CredentialFieldsResponse>(`/entries/${name}/credentials/fields`),

  storeCredentials: (name: string, credentials: Record<string, string>) =>
    request<{ status: string; name: string }>(`/entries/${name}/credentials`, {
      method: "POST",
      body: JSON.stringify({ credentials }),
    }),

  // Generic file upload (Phase 2a). Returns upload_id + path that
  // plugin invocations can pick up via input_data.upload_id.
  uploadFile: async (file: File): Promise<{
    upload_id: string;
    path: string;
    filename: string;
    expires_at: string;
  }> => {
    const form = new FormData();
    form.append("file", file);
    // ``getAccessToken`` is async — without await we send
    // ``Bearer [object Promise]`` and the backend bounces it as
    // "Not enough segments". Surfaced during PR #44 QA.
    const token = await getAccessToken();
    const resp = await fetch(`${BASE}/uploads`, {
      method: "POST",
      headers: token ? { Authorization: `Bearer ${token}` } : {},
      body: form,
    });
    if (!resp.ok) {
      const text = await resp.text().catch(() => "");
      throw new Error(`Upload failed (${resp.status}): ${text || resp.statusText}`);
    }
    return resp.json();
  },

  // Run a plugin with a JSON input payload (e.g. {upload_id}). Wraps the
  // existing /run/{name} endpoint with a body, since `run()` above is
  // body-less. Uses a 30-minute timeout because bulk imports
  // (ai-memory-input + IngestCompiler) regularly take 10-30 minutes on
  // local LLMs; the @bsvibe/api default of 30s would abort them
  // mid-flight with an obscure "signal is aborted without reason".
  runWithInput: (name: string, input: Record<string, unknown>) =>
    request<{ name: string; results: unknown[] }>(`/run/${name}`, {
      method: "POST",
      body: JSON.stringify(input),
      headers: { "Content-Type": "application/json" },
      timeoutMs: 30 * 60 * 1000,
    }),

  // Enable/Disable toggle
  toggleEntry: (name: string) =>
    request<{ name: string; enabled: boolean }>(`/entries/${name}/toggle`, { method: "POST" }),

  // Canonicalization (Handoff §15.1)
  canonListProposals: (status: string = "pending", kind?: string) => {
    const q = kind
      ? `?status=${encodeURIComponent(status)}&kind=${encodeURIComponent(kind)}`
      : `?status=${encodeURIComponent(status)}`;
    return request<{
      items: Array<{
        path: string;
        kind: string;
        status: string;
        strategy: string;
        proposal_score: number;
        evidence: Array<Record<string, unknown>>;
        action_drafts: string[];
      }>;
    }>(`/canonicalization/proposals${q}`);
  },

  canonListActions: (status?: string, kind?: string) => {
    const params = new URLSearchParams();
    if (status) params.set("status", status);
    if (kind) params.set("kind", kind);
    const q = params.toString() ? `?${params.toString()}` : "";
    return request<{
      items: Array<{
        path: string;
        kind: string;
        status: string;
        params: Record<string, unknown>;
        stability_score: number | null;
        risk_reasons: Array<Record<string, unknown>>;
        deterministic_evidence: Array<Record<string, unknown>>;
        model_evidence: Array<Record<string, unknown>>;
        human_evidence: Array<Record<string, unknown>>;
        affected_paths: string[];
        source_proposal: string | null;
      }>;
    }>(`/canonicalization/actions${q}`);
  },

  canonGetNote: (path: string) =>
    request<{ path: string; content: string }>(
      `/canonicalization/note?path=${encodeURIComponent(path)}`,
    ),

  canonApplyAction: (action_path: string) =>
    request<{
      action_path: string;
      final_status: string;
      affected_paths: string[];
    }>(`/canonicalization/actions/apply`, {
      method: "POST",
      body: JSON.stringify({ action_path }),
      headers: { "Content-Type": "application/json" },
    }),

  canonApproveAction: (action_path: string) =>
    request<{
      action_path: string;
      final_status: string;
      affected_paths: string[];
    }>(`/canonicalization/actions/approve`, {
      method: "POST",
      body: JSON.stringify({ action_path }),
      headers: { "Content-Type": "application/json" },
    }),

  canonRejectAction: (action_path: string, reason?: string) =>
    request<{ action_path: string; final_status: string }>(
      `/canonicalization/actions/reject`,
      {
        method: "POST",
        body: JSON.stringify({ action_path, reason }),
        headers: { "Content-Type": "application/json" },
      },
    ),

  canonGenerateProposals: (
    strategy: "deterministic" | "balanced",
    threshold = 0.6,
  ) =>
    request<{ strategy: string; created: string[] }>(
      `/canonicalization/proposals/generate`,
      {
        method: "POST",
        body: JSON.stringify({ strategy, threshold }),
        headers: { "Content-Type": "application/json" },
      },
    ),

  // Vault browser
  vaultTree: () => request<VaultTreeEntry[]>("/vault/tree"),

  vaultFile: (path: string) =>
    request<VaultFileResponse>(`/vault/file?path=${encodeURIComponent(path)}`),

  vaultSearch: (q: string) =>
    request<VaultSearchResult[]>(`/vault/search?q=${encodeURIComponent(q)}`),

  vaultBacklinks: (path: string) =>
    request<VaultBacklink[]>(`/vault/backlinks?path=${encodeURIComponent(path)}`),

  vaultGraph: () => request<VaultGraph>("/vault/graph"),

  vaultCommunities: () => request<VaultCommunities>("/vault/communities"),

  vaultTags: () => request<VaultTags>("/vault/tags"),

  // MCP API keys (PATs) — for connecting Claude Desktop / Cursor / etc.
  mcpKeys: {
    list: () => request<MCPAPIKey[]>("/mcp/api-keys"),
    create: (name: string) =>
      request<MCPAPIKeyIssued>("/mcp/api-keys", {
        method: "POST",
        body: JSON.stringify({ name }),
        headers: { "Content-Type": "application/json" },
      }),
    revoke: (id: string) =>
      request<void>(`/mcp/api-keys/${encodeURIComponent(id)}`, { method: "DELETE" }),
  },
};
