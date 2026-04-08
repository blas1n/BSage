import { useCallback, useEffect, useState } from "react";
import { BSVibeAuth } from "../lib/bsvibe-auth";

const AUTH_URL = import.meta.env.VITE_AUTH_URL || "https://auth.bsvibe.dev";

const auth = new BSVibeAuth({
  authUrl: AUTH_URL,
  callbackPath: "/auth/callback",
});

interface AuthState {
  token: string | null;
  loading: boolean;
  signOut: () => void;
  login: () => void;
  signup: () => void;
}

export function useAuth(): AuthState {
  const [token, setToken] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    // 1. Check if we just came back from auth callback (tokens in hash)
    const callbackUser = auth.handleCallback();
    if (callbackUser) {
      setToken(callbackUser.accessToken);
      setLoading(false);
      return;
    }

    // 2. Check local session
    const localUser = auth.getUser();
    if (localUser) {
      setToken(localUser.accessToken);
      setLoading(false);
      return;
    }

    // 3. Silent SSO check (redirect-based)
    const result = auth.checkSession();
    if (result === 'redirect') return; // page is navigating away
    if (result) {
      setToken(result.accessToken);
    }
    setLoading(false);
  }, []);

  const signOut = useCallback(() => {
    setToken(null);
    auth.logout();
  }, []);

  const login = useCallback(() => {
    auth.redirectToLogin();
  }, []);

  const signup = useCallback(() => {
    auth.redirectToSignup();
  }, []);

  return { token, loading, signOut, login, signup };
}

/** Get current access token for API calls (can be called outside React) */
export function getToken(): string | null {
  return auth.getToken();
}
