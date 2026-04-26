/**
 * Vendored shim of `@bsvibe/types`.
 *
 * Phase A Batch 5 (BSage): the bsvibe-frontend-lib packages are not yet
 * published to GitHub Packages (Decision #12 — pending user PAT issuance).
 * To keep production deploy green while still adopting the canonical
 * `@bsvibe/types` import surface, this file re-exports the same public
 * types that `@bsvibe/types` ships at version 0.1.0 (commit
 * bsvibe-frontend-lib/main `packages/types/src/index.ts`).
 *
 * Once the package is published and added to package.json, delete this
 * file and the matching tsconfig path alias — every consumer import is
 * already canonical (`from '@bsvibe/types'`) and will resolve to
 * node_modules without any code changes.
 *
 * Source of truth: https://github.com/BSVibe/bsvibe-frontend-lib
 */

/* ---------------------------------------------------------------------------
 * Auth config
 * ------------------------------------------------------------------------- */

export interface BSVibeAuthConfig {
  /** URL of the BSVibe auth app, e.g. 'https://auth.bsvibe.dev' */
  authUrl: string;
  /** Callback path on the client app. Default: '/auth/callback' */
  callbackPath?: string;
}

/* ---------------------------------------------------------------------------
 * Legacy single-tenant session shape (BSVibeAuth class)
 * ------------------------------------------------------------------------- */

/**
 * Legacy session-cached user shape produced by parseToken().
 * Kept for backward compatibility with `BSVibeAuth` (token-in-localStorage flow).
 * The new `useAuth()` hook uses `User` + `Tenant` (richer, multi-tenant) instead.
 */
export interface BSVibeUser {
  id: string;
  email: string;
  tenantId: string;
  role: string;
  accessToken: string;
  refreshToken: string;
  expiresAt: number;
}

/* ---------------------------------------------------------------------------
 * Phase 0 P0.6 — multi-tenant session shape
 * ------------------------------------------------------------------------- */

export type TenantRole = 'owner' | 'admin' | 'member' | 'viewer';
export type TenantPlan = 'free' | 'pro' | 'team' | 'enterprise';
export type TenantType = 'personal' | 'org';

export type Plan = TenantPlan;
export type Type = TenantType;

export interface Tenant {
  id: string;
  name: string;
  type: TenantType;
  role: TenantRole;
  plan: TenantPlan;
}

export interface User {
  id: string;
  email: string;
  name?: string;
  avatar_url?: string;
}

/**
 * Permission identifier in `<product>.<resource>.<action>` format.
 * E.g. `bsage.note.read`, `nexus.project.write`, `core.tenant.manage`.
 */
export type Permission = string;

/** Response envelope from `GET /api/session`. */
export interface SessionEnvelope {
  user: User;
  tenants: Tenant[];
  active_tenant_id: string | null;
  access_token: string;
  refresh_token: string;
  expires_in: number;
}

export interface SwitchTenantResponse {
  active_tenant_id: string;
  access_token: string;
  refresh_token: string;
  expires_in: number;
}
