'use client';

import { useEffect } from "react";
import { useRouter } from "next/navigation";

/**
 * Transitional hash-route -> path-route redirect shim.
 *
 * BSage previously ran as a hash-routing SPA (`#/dashboard`, `#/graph`,
 * `#/auth/callback`, …). After the App Router migration the canonical URLs
 * are real path segments (`/dashboard`, `/graph`, `/auth/callback`).
 *
 * Two compatibility concerns this covers:
 *
 *  1. OAuth callback — the `redirect_uri` registered with `auth.bsvibe.dev`
 *     for BSage is still the HASH form (`.../#/auth/callback`). Until that
 *     allowlist entry is updated to `/auth/callback`, the auth server will
 *     keep sending users to the hash URL. We detect `#/auth/callback` and
 *     redirect to `/auth/callback`, PRESERVING the token fragment that the
 *     auth server appends after the route hash
 *     (`#/auth/callback#access_token=...`) by re-attaching it as a `#`
 *     fragment so `consumeAuthCallback()` on the new route can still read it.
 *
 *  2. Old bookmarks — a saved `#/dashboard` link should still land on
 *     `/dashboard`. Any other `#/...` hash is mapped 1:1 to its path.
 *
 * This runs once on mount at the root layout, so it covers every entry
 * point. Once the auth-server allowlist is migrated and old bookmarks have
 * aged out, this component can be deleted.
 */
export function HashRedirect() {
  const router = useRouter();

  useEffect(() => {
    const raw = window.location.hash || "";
    if (!raw.startsWith("#/")) return;

    // Auth callback: `#/auth/callback` optionally followed by a second
    // `#access_token=...` fragment OR `?access_token=...` query.
    if (raw.startsWith("#/auth/callback")) {
      // Everything after the route part is the token payload. The auth
      // server emits `#/auth/callback#access_token=...`; slice from the
      // FIRST `access_token=` occurrence so we keep the raw token blob.
      const tokenIdx = raw.indexOf("access_token=");
      const tokenFragment = tokenIdx >= 0 ? "#" + raw.slice(tokenIdx) : "";
      const search = window.location.search || "";
      router.replace("/auth/callback" + search + tokenFragment);
      return;
    }

    // Generic hash -> path. Strip the leading `#`, keep the rest verbatim
    // (path + any nested query/fragment). `#/` alone maps to `/`.
    const target = raw.slice(1) || "/";
    router.replace(target);
  }, [router]);

  return null;
}
