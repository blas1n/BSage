import { useCallback, useEffect, useState } from "react";
import { clearTokens, consumeHashTokens, getAccessToken } from "../lib/auth-tokens";

const AUTH_LOGIN_URL = "https://auth.bsvibe.dev/login";

interface AuthState {
  token: string | null;
  loading: boolean;
  signOut: () => void;
}

export function useAuth(): AuthState {
  const [token, setToken] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    // 1. Check if we just came back from auth callback (tokens in hash)
    consumeHashTokens();

    // 2. Read token from storage
    setToken(getAccessToken());
    setLoading(false);
  }, []);

  const signOut = useCallback(() => {
    clearTokens();
    setToken(null);
    redirectToLogin();
  }, []);

  return { token, loading, signOut };
}

/** Redirect browser to external auth login page. */
export function redirectToLogin() {
  const callbackUrl = `${window.location.origin}/auth/callback`;
  const stateBytes = new Uint8Array(16);
  crypto.getRandomValues(stateBytes);
  const state = Array.from(stateBytes, (b) => b.toString(16).padStart(2, "0")).join("");
  window.location.href = `${AUTH_LOGIN_URL}?redirect_uri=${encodeURIComponent(callbackUrl)}&state=${encodeURIComponent(state)}`;
}
