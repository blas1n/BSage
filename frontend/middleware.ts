/**
 * BSage i18n middleware.
 *
 * Uses the BSVibe shared `@bsvibe/i18n/middleware` factory so locale routing
 * stays consistent across all consumer products. BSage deliberately pins
 * `defaultLocale: 'en'` (overriding the package default of `ko`) because the
 * existing UI copy and Playwright e2e suite assert on English. Korean is
 * opt-in via the `/ko/...` URL prefix.
 *
 * This middleware is i18n-only — BSage's auth gate is client-side (in
 * `AppChrome`), so there is no server-side login redirect here.
 */
import { createI18nMiddleware } from '@bsvibe/i18n/middleware';

export default createI18nMiddleware({
  locales: ['ko', 'en'],
  defaultLocale: 'en',
  localePrefix: 'as-needed',
});

// NOTE: Next.js parses `config.matcher` statically — spread operators or
// computed values are rejected. The `/api` and `/ws` rewrites in
// `next.config.mjs` must NOT be locale-routed: `/api` is already excluded by
// the package default matcher; `/ws` has no dot so it is added explicitly to
// the negative lookahead.
export const config = {
  matcher: ['/((?!api|ws|_next|_vercel|.*\\..*).*)'],
};
