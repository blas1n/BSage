import type { Metadata } from 'next';
import type { ReactNode } from 'react';
import { notFound } from 'next/navigation';
import { getMessages, setRequestLocale } from 'next-intl/server';
import { BSVibeIntlProvider, isSupportedLocale } from '@bsvibe/i18n';
import './globals.css';
import { HashRedirect } from '@/src/components/routing/HashRedirect';

export const metadata: Metadata = {
  title: 'BSage',
  description: 'Your AI-powered second brain.',
  icons: {
    icon: '/favicon.svg',
  },
};

/**
 * Pre-render both locale roots. The `[locale]` segment is supplied by the
 * `@bsvibe/i18n` middleware (`localePrefix: 'as-needed'`, default `en`); the
 * shared package default is `ko`, but BSage pins `en` to preserve the
 * existing English UI copy and Playwright e2e regressions. Korean is opt-in
 * via the `/ko/...` URL prefix.
 */
export function generateStaticParams() {
  return [{ locale: 'ko' }, { locale: 'en' }];
}

/**
 * Root layout for BSage. The old (pre-i18n) `app/layout.tsx` has been folded
 * into this `[locale]` layout so the locale segment is the outermost route.
 *
 * `BSVibeIntlProvider` supplies the next-intl context for every client
 * component's `useT()` call — it replaces the old `react-i18next` side-effect
 * init (`import '@/src/i18n'`).
 */
export default async function RootLayout({
  children,
  params,
}: {
  children: ReactNode;
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await params;
  if (!isSupportedLocale(locale)) {
    notFound();
  }
  // Tell next-intl which locale this server render is for so any RSC
  // `getTranslations()` in nested layouts/pages resolves correctly.
  setRequestLocale(locale);
  const messages = await getMessages();

  return (
    <html lang={locale} className="dark">
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
        <link
          href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:ital,wght@0,200..800;1,200..800&family=JetBrains+Mono:ital,wght@0,100..800;1,100..800&display=swap"
          rel="stylesheet"
        />
        <link
          href="https://fonts.googleapis.com/css2?family=Material+Symbols+Outlined:wght,FILL@100..700,0..1&display=swap"
          rel="stylesheet"
        />
      </head>
      <body className="bg-[#0a0b0f] text-[#e4e6ee]">
        <BSVibeIntlProvider locale={locale} messages={messages}>
          {/* Transitional hash-route -> path-route redirect. Catches legacy
              `#/...` URLs (old bookmarks + the still-hash-registered OAuth
              `redirect_uri`) and replaces them with the canonical path. */}
          <HashRedirect />
          {children}
        </BSVibeIntlProvider>
      </body>
    </html>
  );
}
