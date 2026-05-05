import { useEffect, useState } from "react";
import { isDemoMode } from "@bsvibe/demo";
import type { User as SharedUser } from "@bsvibe/types";

// BSage's local "session user" carries tenant + role denormalised out of
// the JWT `app_metadata` claim, while the canonical `@bsvibe/types.User`
// only models identity (id/email/name/avatar). Phase A Batch 5: we
// extend the shared type so the BSage UI keeps the tenantId/role fields
// it already renders, while the shared identity shape stays the source
// of truth — once BSage migrates to the cookie-SSO `useAuth()` provider
// (deferred, see `src/lib/bsvibe/README.md`), tenant/role will move into
// `Tenant` from `@bsvibe/types` and this local extension goes away.
interface User extends SharedUser {
  tenantId: string;
  tenantName: string | null;
  role: string;
}

const AUTH_URL =
  process.env.NEXT_PUBLIC_AUTH_URL ||
  process.env.VITE_AUTH_URL ||
  "https://auth.bsvibe.dev";

// LocalStorage keys for non-cookie-SSO environments (local dev, Tailscale, etc.)
const LS_ACCESS_TOKEN = "bsage_access_token";
const LS_REFRESH_TOKEN = "bsage_refresh_token";
const LS_EXPIRES_AT = "bsage_expires_at";

interface SessionTenant {
  id: string;
  name: string;
  role?: string;
}

interface SessionResponse {
  access_token: string;
  refresh_token: string;
  expires_in: number;
  tenants?: SessionTenant[];
  active_tenant_id?: string;
}

let cachedToken: { value: string; expiresAt: number } | null = null;
interface AccessTokenOptions {
  probeRemoteSession?: boolean;
}
// Dedupe concurrent getAccessToken callers onto a single in-flight cookie-
// SSO fetch. Without this, App.tsx's useAuth, Sidebar's useAuth,
// useWebSocket, and api.client each fire their own /api/session request
// at mount time. If any one returns a transient error (Cloudflare
// challenge, cold start, brief network hiccup), its caller resolves to
// null and the downstream API request goes out without Authorization —
// even though a sibling caller ultimately populated cachedToken. The
// resulting 401 leaves VaultView etc. stuck on "Vault is empty".
let inFlightSession: Promise<string | null> | null = null;

function loadTokenFromLocalStorage(): { value: string; expiresAt: number } | null {
  const value = localStorage.getItem(LS_ACCESS_TOKEN);
  const expiresAtStr = localStorage.getItem(LS_EXPIRES_AT);
  if (!value || !expiresAtStr) return null;
  const expiresAt = Number(expiresAtStr);
  if (!Number.isFinite(expiresAt)) return null;
  return { value, expiresAt };
}

function saveTokenToLocalStorage(
  accessToken: string,
  refreshToken: string,
  expiresIn: number,
): void {
  const expiresAt = Date.now() + expiresIn * 1000;
  localStorage.setItem(LS_ACCESS_TOKEN, accessToken);
  localStorage.setItem(LS_REFRESH_TOKEN, refreshToken);
  localStorage.setItem(LS_EXPIRES_AT, String(expiresAt));
}

function clearLocalStorageTokens(): void {
  localStorage.removeItem(LS_ACCESS_TOKEN);
  localStorage.removeItem(LS_REFRESH_TOKEN);
  localStorage.removeItem(LS_EXPIRES_AT);
}

export async function getAccessToken({
  probeRemoteSession = true,
}: AccessTokenOptions = {}): Promise<string | null> {
  if (cachedToken && Date.now() < cachedToken.expiresAt - 30_000) {
    return cachedToken.value;
  }

  // Non-cookie-SSO fallback: token stashed in localStorage by auth callback.
  const stored = loadTokenFromLocalStorage();
  if (stored && Date.now() < stored.expiresAt - 30_000) {
    cachedToken = stored;
    return stored.value;
  }

  if (!probeRemoteSession) {
    return null;
  }

  // Production path: cross-subdomain cookie SSO via auth.bsvibe.dev.
  // Every caller during this window awaits the same Promise so a
  // single 401/Cloudflare failure can't de-sync callers.
  if (inFlightSession) return inFlightSession;
  inFlightSession = (async () => {
    try {
      const res = await fetch(`${AUTH_URL}/api/session`, { credentials: "include" });
      if (!res.ok) return null;
      const data: SessionResponse = await res.json();
      cachedToken = {
        value: data.access_token,
        expiresAt: Date.now() + data.expires_in * 1000,
      };
      // Persist so a reload doesn't require another cookie round-trip
      // (and so sibling tabs can reuse the token).
      saveTokenToLocalStorage(data.access_token, data.refresh_token, data.expires_in);
      return data.access_token;
    } catch {
      return null;
    } finally {
      inFlightSession = null;
    }
  })();
  return inFlightSession;
}

export function clearTokenCache() {
  cachedToken = null;
  inFlightSession = null;
  clearLocalStorageTokens();
}

/**
 * Inject a demo session JWT into the auth token cache so getAccessToken()
 * returns the demo Bearer for every fetch. Without this, the demo shell
 * renders but every data fetch goes out without Authorization → 401 →
 * Settings shows "missing Authorization header", VaultView empty, etc.
 *
 * Wire from App.tsx DemoApp via @bsvibe/demo 0.3 onSessionReady.
 */
export function injectDemoToken(token: string, expiresIn: number): void {
  const expiresAt = Date.now() + expiresIn * 1000;
  cachedToken = { value: token, expiresAt };
  if (typeof window !== "undefined") {
    saveTokenToLocalStorage(token, "", expiresIn);
  }
}

/**
 * Parse tokens from the OAuth callback URL fragment and persist them.
 * Called by the /auth/callback route handler. Returns true if a token
 * was found and stored.
 */
export function consumeAuthCallback(): boolean {
  // Hash looks like: "#/auth/callback#access_token=...&refresh_token=...&expires_in=..."
  // after the route hash, tokens are in a second fragment. We also support
  // the plain "?access_token=..." query form as a fallback.
  const raw = window.location.hash || "";
  const queryRaw = window.location.search || "";
  const tokenPart = raw.includes("access_token=")
    ? raw.slice(raw.indexOf("access_token="))
    : queryRaw.includes("access_token=")
      ? queryRaw.slice(queryRaw.indexOf("access_token="))
      : "";
  if (!tokenPart) return false;
  const params = new URLSearchParams(tokenPart);
  const accessToken = params.get("access_token");
  const refreshToken = params.get("refresh_token") ?? "";
  const expiresIn = Number(params.get("expires_in") ?? "3600");
  if (!accessToken) return false;
  saveTokenToLocalStorage(accessToken, refreshToken, expiresIn);
  cachedToken = {
    value: accessToken,
    expiresAt: Date.now() + expiresIn * 1000,
  };
  return true;
}

function decodeJwt(token: string): Record<string, unknown> {
  const parts = token.split(".");
  let base64 = parts[1].replace(/-/g, "+").replace(/_/g, "/");
  const pad = base64.length % 4;
  if (pad) base64 += "=".repeat(4 - pad);
  return JSON.parse(atob(base64));
}

export function useAuth({
  probeRemoteSession = true,
}: AccessTokenOptions = {}) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const [tenants, setTenants] = useState<SessionTenant[]>([]);

  useEffect(() => {
    (async () => {
      const token = await getAccessToken({ probeRemoteSession });
      if (!token) {
        setLoading(false);
        return;
      }
      const payload = decodeJwt(token);
      const appMeta = payload.app_metadata as Record<string, string> | undefined;
      // Demo JWT carries `tenant_id` directly + `is_demo: true`; no
      // app_metadata envelope, no auth.bsvibe.dev session.
      const directTenantId =
        (payload.tenant_id as string | undefined) ?? "";
      const isDemoSession = payload.is_demo === true;
      const tenantId = appMeta?.tenant_id ?? directTenantId;
      let tenantName: string | null = isDemoSession ? "Demo sandbox" : null;
      let tenantList: SessionTenant[] = [];
      let activeTenantId: string = tenantId;
      // Skip the prod tenants probe in demo mode — auth.bsvibe.dev does
      // not allow the demo origin and the call CORS-fails noisily.
      if (!isDemoSession && !isDemoMode()) {
        try {
          const res = await fetch(`${AUTH_URL}/api/session`, {
            credentials: "include",
            headers: { Authorization: `Bearer ${token}` },
          });
          if (res.ok) {
            const data: SessionResponse = await res.json();
            tenantList = data.tenants ?? [];
            activeTenantId = data.active_tenant_id ?? tenantId;
            tenantName =
              tenantList.find((t) => t.id === activeTenantId)?.name ?? null;
          }
        } catch {
          // ignore
        }
      }
      setUser({
        id: (payload.sub as string) ?? (isDemoSession ? "demo-user" : ""),
        email:
          (payload.email as string) ??
          (isDemoSession ? "demo@bsvibe.dev" : ""),
        tenantId: activeTenantId,
        tenantName,
        role: appMeta?.role ?? (isDemoSession ? "demo" : "member"),
      });
      setTenants(tenantList);
      setLoading(false);
    })();
  }, [probeRemoteSession]);

  // Switch active workspace via /api/session/switch_tenant. The endpoint
  // sets a server-side cookie + writes the new active_tenant_id; reload
  // so every consumer (frontend + backend) picks up the new context.
  async function switchTenant(nextTenantId: string): Promise<void> {
    if (nextTenantId === user?.tenantId) return;
    const token = await getAccessToken({ probeRemoteSession });
    if (!token) return;
    try {
      const res = await fetch(`${AUTH_URL}/api/session/switch_tenant`, {
        method: "POST",
        credentials: "include",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({ tenant_id: nextTenantId }),
      });
      if (res.ok) {
        clearTokenCache();
        window.location.reload();
      }
    } catch {
      // ignore — caller can surface a toast if needed
    }
  }

  function callbackUrl(): string {
    // Hash-route callback so SPA can parse fragment tokens.
    return `${window.location.origin}/#/auth/callback`;
  }

  function login() {
    const redirect = encodeURIComponent(callbackUrl());
    window.location.href = `${AUTH_URL}/login?redirect_uri=${redirect}`;
  }

  function signup() {
    const redirect = encodeURIComponent(callbackUrl());
    window.location.href = `${AUTH_URL}/signup?redirect_uri=${redirect}`;
  }

  async function logout() {
    try {
      await fetch(`${AUTH_URL}/api/session`, { method: "DELETE", credentials: "include" });
    } catch {
      // Cookie session may not exist (localStorage-only env) — ignore.
    }
    clearTokenCache();
    setUser(null);
    window.location.href = "https://bsvibe.dev/";
  }

  return { user, loading, login, signup, logout, tenants, switchTenant };
}
