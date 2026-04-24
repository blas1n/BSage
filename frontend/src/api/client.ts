import type {
  ChatRequest,
  ChatResponse,
  ConfigUpdate,
  CredentialFieldsResponse,
  EntryMeta,
  RuntimeConfig,
  VaultBacklink,
  VaultFileResponse,
  VaultGraph,
  VaultSearchResult,
  VaultCommunities,
  VaultTags,
  VaultTreeEntry,
  LlmTestResult,
} from "./types";
import { getAccessToken } from "../hooks/useAuth";

// Normalize VITE_API_URL so operators can set either
// `https://api.example.com` or `https://api.example.com/api` — every
// path in this module is `/vault/tree`, `/knowledge/search`, etc. (no
// `/api` prefix), so BASE must always end with `/api`. Without this,
// setting VITE_API_URL to a bare host drops the prefix and every
// request lands on the SPA fallback (200 + HTML) instead of the
// backend, which then looks like an auth failure to the caller.
const BASE = (() => {
  const raw = (import.meta.env.VITE_API_URL || "/api").replace(/\/+$/, "");
  return raw.endsWith("/api") ? raw : `${raw}/api`;
})();

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };

  const token = await getAccessToken();
  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }

  const res = await fetch(`${BASE}${path}`, {
    headers,
    ...init,
  });
  if (!res.ok) {
    const detail = await res.text().catch(() => res.statusText);
    throw new Error(`${res.status}: ${detail}`);
  }
  return res.json();
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

  // Enable/Disable toggle
  toggleEntry: (name: string) =>
    request<{ name: string; enabled: boolean }>(`/entries/${name}/toggle`, { method: "POST" }),

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
};
