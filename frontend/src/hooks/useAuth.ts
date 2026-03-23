import { useCallback, useEffect, useState } from "react";
import type { Session, User } from "@supabase/supabase-js";
import { supabase } from "../lib/supabase";

const AUTH_LOGIN_URL = "https://auth.bsvibe.dev/login";

interface AuthState {
  session: Session | null;
  user: User | null;
  loading: boolean;
  signOut: () => Promise<void>;
}

export function useAuth(): AuthState {
  const [session, setSession] = useState<Session | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    supabase.auth.getSession().then(({ data }) => {
      setSession(data.session);
      setLoading(false);
    });

    const {
      data: { subscription },
    } = supabase.auth.onAuthStateChange((_event, session) => {
      setSession(session);
      // Clean up hash fragment after Supabase picks up tokens
      if (session && window.location.hash.includes("access_token")) {
        window.history.replaceState(null, "", window.location.pathname);
      }
    });

    return () => subscription.unsubscribe();
  }, []);

  const signOut = useCallback(async () => {
    await supabase.auth.signOut();
    redirectToLogin();
  }, []);

  return {
    session,
    user: session?.user ?? null,
    loading,
    signOut,
  };
}

/** Redirect browser to external auth login page. */
export function redirectToLogin() {
  const callbackUrl = `${window.location.origin}/api/auth/callback`;
  const state = crypto.randomUUID();
  window.location.href = `${AUTH_LOGIN_URL}?redirect_uri=${encodeURIComponent(callbackUrl)}&state=${encodeURIComponent(state)}`;
}
