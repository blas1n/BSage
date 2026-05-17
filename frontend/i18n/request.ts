/**
 * next-intl request config — composes the shared `@bsvibe/i18n` namespaces
 * (`common`, `auth`) with the BSage-local `sage` namespace.
 *
 * BSage pins `defaultLocale: 'en'` because the existing UI copy and
 * Playwright e2e suite assert on English. Korean is opt-in via the `/ko`
 * URL prefix produced by the `localePrefix: 'as-needed'` middleware.
 */
import { getRequestConfig as defineRequestConfig } from 'next-intl/server';
import {
  getRequestConfig as buildSharedConfig,
  resolveLocale,
} from '@bsvibe/i18n';

const SAGE_DEFAULT_LOCALE = 'en' as const;

export default defineRequestConfig(async ({ requestLocale }) => {
  const requested = await requestLocale;
  const locale = resolveLocale(requested, SAGE_DEFAULT_LOCALE);

  // BSage messages live at `frontend/messages/sage.{en,ko}.json`, shaped
  // `{ nav: {...}, chat: {...}, ... }` — the same nested tree the legacy
  // react-i18next `sage.json` carried. Layering it as the `sage` namespace
  // keeps every `t('nav.dashboard')` call working; `buildSharedConfig` adds
  // the shared `common` / `auth` namespaces.
  const file = (await import(`../messages/sage.${locale}.json`)).default;

  const shared = await buildSharedConfig({
    locale,
    extra: { sage: file },
  });

  return {
    locale,
    messages: shared.messages,
  };
});
