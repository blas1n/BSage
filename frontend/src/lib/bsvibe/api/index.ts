/**
 * Vendored shim of `@bsvibe/api`.
 *
 * Phase A Batch 5 (BSage): the bsvibe-frontend-lib `@bsvibe/api` package
 * is not yet published to GitHub Packages (Decision #12 — pending user
 * PAT issuance). This shim re-exports the same public surface that
 * `@bsvibe/api@0.1.0` ships, so consumer code uses the canonical
 * `import { createApiFetch } from '@bsvibe/api'` path today.
 *
 * BSage only consumes the **client-side** surface (createApiFetch,
 * setOnAuthError, ApiError) — Server Actions / Vercel adapters are
 * Next.js-only patterns that do not apply to BSage's hash-routed SPA.
 *
 * Once `@bsvibe/api` is published, delete this directory and the matching
 * tsconfig path alias — every consumer import is already canonical and
 * will resolve to node_modules without any code changes.
 */

export {
  ApiError,
  createApiFetch,
  type ApiClient,
  type CreateApiFetchOptions,
  type RequestOptions,
} from './fetch';

export {
  handleAuthError,
  isAuthErrorGuardEngaged,
  resetAuthErrorGuard,
  setOnAuthError,
} from './auth';
