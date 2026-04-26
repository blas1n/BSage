# Vendored `@bsvibe/*` shim — temporary

Phase A Batch 5 (2026-04-26).

## Why this exists

The bsvibe-frontend-lib packages (`@bsvibe/types`, `@bsvibe/api`, `@bsvibe/auth`, ...) are **not yet published to GitHub Packages** — that is gated on user-side action (Decision #12, [BSVibe_Execution_Lockin §5](../../../../../../../Docs/BSVibe_Execution_Lockin.md)):

- GitHub Packages org-scoped PAT (`read:packages` + `write:packages`)
- Vercel `NPM_TOKEN` env var

To unblock consumer migration **without** breaking the production Vercel deploy, BSage adopts the canonical `@bsvibe/*` import surface today by aliasing the public package names to vendored copies inside this directory via `tsconfig.json` path mapping.

## What is vendored

| Canonical package | Local path | Notes |
|-------------------|------------|-------|
| `@bsvibe/types` | `./types/` | Verbatim from bsvibe-frontend-lib `packages/types/src/index.ts` (commit `main`) |
| `@bsvibe/api` | `./api/` | Subset — `fetch.ts` + `auth.ts` only. Server-action / Vercel adapter / dual-env reader are Next.js-only patterns BSage does not consume |

## What is **not** vendored

- `@bsvibe/auth` (`useAuth` hook + `AuthProvider`) — the shared hook is built around cross-domain cookie-SSO + `/api/session` polling, while BSage's frontend uses the legacy hash-route OAuth callback + `localStorage` token flow. Migration is a **behaviour change** and is deferred to a follow-up PR alongside the BSage SSO model alignment.
- `@bsvibe/layout`, `@bsvibe/ui`, `@bsvibe/design-tokens` — BSage's existing components use Material 3 surface tokens (`bg-surface-dim`, `text-on-surface`, ...) and category-scoped Badge variants (`input` / `process` / `output`) that diverge from the shared `Button|Modal|Badge|Input|Card` surface. Migration would be a redesign, deferred.
- `@bsvibe/i18n` — BSage uses `react-i18next`, the shared package targets `next-intl`. Migration is a Phase C concern.

## How to remove the shim post-publish

1. `pnpm add -E @bsvibe/types @bsvibe/api` (or the appropriate semver) inside `frontend/`.
2. Delete `frontend/src/lib/bsvibe/`.
3. Delete the two `paths` entries in `frontend/tsconfig.json`.
4. `npm run build` — every consumer import is already canonical (`from '@bsvibe/types'` / `from '@bsvibe/api'`) and now resolves to `node_modules` without any code edits.

## Source of truth

- Repository: https://github.com/BSVibe/bsvibe-frontend-lib (commit `main`)
- Phase A extraction matrix: BSage Vault `references/phase-a-패키지-추출-완료.md`
