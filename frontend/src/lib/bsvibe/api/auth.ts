/**
 * 401 cascading-logout guard — vendored from `@bsvibe/api`.
 *
 * Vendored verbatim from bsvibe-frontend-lib/main packages/api/src/auth.ts.
 * See ../README in `frontend/src/lib/bsvibe` for the rationale (publish
 * blocked on user PAT, see Decision #12).
 */

let onAuthError: (() => void) | null = null;
let isHandlingAuthError = false;

export function setOnAuthError(cb: (() => void) | null): void {
  onAuthError = cb;
}

export function handleAuthError(): boolean {
  if (isHandlingAuthError) return false;
  isHandlingAuthError = true;
  if (onAuthError) {
    try {
      onAuthError();
    } catch {
      /* swallow — onAuthError is a fire-and-forget side-effect */
    }
  }
  return true;
}

export function resetAuthErrorGuard(): void {
  isHandlingAuthError = false;
}

export function isAuthErrorGuardEngaged(): boolean {
  return isHandlingAuthError;
}
