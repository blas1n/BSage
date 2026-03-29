/**
 * Simple token store for the redirect-based auth flow.
 * Replaces the Supabase JS client — tokens come from the
 * /auth/callback redirect (URL hash fragment).
 */

const ACCESS_TOKEN_KEY = "bsage_access_token";
const REFRESH_TOKEN_KEY = "bsage_refresh_token";

export function getAccessToken(): string | null {
  const token = localStorage.getItem(ACCESS_TOKEN_KEY);
  if (!token) return null;

  // Validate JWT expiry (client-side only — server validates signature)
  try {
    // JWT uses base64url encoding: replace URL-safe chars before decoding
    const b64 = token.split(".")[1].replace(/-/g, "+").replace(/_/g, "/");
    const payload = JSON.parse(atob(b64));
    if (payload.exp && payload.exp * 1000 < Date.now()) {
      clearTokens();
      return null;
    }
  } catch {
    // Malformed token — treat as invalid
    clearTokens();
    return null;
  }

  return token;
}

export function setTokens(accessToken: string, refreshToken: string): void {
  localStorage.setItem(ACCESS_TOKEN_KEY, accessToken);
  localStorage.setItem(REFRESH_TOKEN_KEY, refreshToken);
}

export function clearTokens(): void {
  localStorage.removeItem(ACCESS_TOKEN_KEY);
  localStorage.removeItem(REFRESH_TOKEN_KEY);
}

/**
 * Try to extract auth tokens from the URL hash fragment.
 * Returns true if tokens were found and stored.
 */
export function consumeHashTokens(): boolean {
  const hash = window.location.hash;
  if (!hash.includes("access_token")) return false;

  const params = new URLSearchParams(hash.replace(/^#/, ""));
  const accessToken = params.get("access_token");
  const refreshToken = params.get("refresh_token");

  if (accessToken) {
    setTokens(accessToken, refreshToken ?? "");
    // Clean up the URL
    window.history.replaceState(null, "", window.location.pathname);
    return true;
  }
  return false;
}
