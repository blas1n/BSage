import { useCallback, useEffect, useState } from "react";
import { clearTokens, consumeHashTokens, getAccessToken } from "../lib/supabase";

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
  const callbackUrl = `${window.location.origin}/api/auth/callback`;
  const state = Math.random().toString(36).slice(2) + Date.now().toString(36);
  window.location.href = `${AUTH_LOGIN_URL}?redirect_uri=${encodeURIComponent(callbackUrl)}&state=${encodeURIComponent(state)}`;
}
