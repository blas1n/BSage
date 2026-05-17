'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { consumeAuthCallback } from '@/src/hooks/useAuth';

/**
 * OAuth callback route — `/auth/callback`.
 *
 * The auth server redirects here with the token blob in the URL fragment
 * (`/auth/callback#access_token=...&refresh_token=...&expires_in=...`), or
 * as a `?access_token=...` query fallback. `consumeAuthCallback()` parses
 * and persists the tokens, then we route to `/` where the `(app)` layout's
 * auth gate picks up the now-authenticated session.
 *
 * NOTE: the BSage `redirect_uri` registered on `auth.bsvibe.dev` is still
 * the legacy HASH form (`.../#/auth/callback`). Until that allowlist entry
 * is migrated to `/auth/callback`, the auth server keeps sending users to
 * the hash URL — `HashRedirect` (root layout) catches `#/auth/callback`,
 * preserves the token fragment, and replaces to this route. So this page
 * works for BOTH the transitional hash path and the future direct path.
 */

type CallbackStatus = 'pending' | 'ok' | 'failed';

function readCallbackStatus(): CallbackStatus {
  // `consumeAuthCallback()` reads `window.location` + `localStorage`. On
  // the server prerender `window` is undefined — return 'pending' so the
  // build's static export of this route does not crash. On the client the
  // lazy `useState` initializer runs ONCE at mount and does the real read,
  // which keeps the token consumption out of an effect (no React 19
  // `set-state-in-effect` cascading-render lint).
  if (typeof window === 'undefined') return 'pending';
  return consumeAuthCallback() ? 'ok' : 'failed';
}

export default function AuthCallbackPage() {
  const router = useRouter();
  const [status] = useState<CallbackStatus>(readCallbackStatus);

  useEffect(() => {
    // Navigation is the only genuine effect — it syncs the router (an
    // external system) with the already-derived token outcome.
    if (status === 'ok') router.replace('/');
  }, [status, router]);

  return (
    <div className="flex min-h-screen items-center justify-center bg-gray-950">
      <div className="text-center text-gray-400 p-8">
        {status === 'failed' ? (
          <>
            <h1 className="text-xl font-bold mb-2 text-gray-100">
              Sign-in failed
            </h1>
            <p className="text-sm mb-3">
              No authentication token was found in the callback URL.
            </p>
            <Link href="/" className="text-sm text-emerald-400 hover:underline">
              Return to BSage
            </Link>
          </>
        ) : (
          <div className="text-gray-500">Signing you in…</div>
        )}
      </div>
    </div>
  );
}
