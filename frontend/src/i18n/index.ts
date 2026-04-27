import i18n from 'i18next'
import { initReactI18next } from 'react-i18next'

import koSage from './ko/sage.json'
import enSage from './en/sage.json'

export const SUPPORTED_LANGS = ['en', 'ko'] as const
export type SupportedLang = (typeof SUPPORTED_LANGS)[number]

const STORAGE_KEY = 'bsage.lang'

/**
 * Resolve the initial language. Order:
 *   1. Persisted choice in localStorage
 *   2. Default to 'en'
 *
 * Browser navigator.language is intentionally NOT used as the default —
 * Phase B/C e2e tests assert visible English text, so 'en' must be the
 * stable baseline. Korean is opt-in via the language switcher.
 */
function resolveInitialLang(): SupportedLang {
  if (typeof window === 'undefined') return 'en'
  try {
    const saved = window.localStorage.getItem(STORAGE_KEY)
    if (saved && (SUPPORTED_LANGS as readonly string[]).includes(saved)) {
      return saved as SupportedLang
    }
  } catch {
    // localStorage may be blocked (private mode, SSR, etc.) — fall through
  }
  return 'en'
}

i18n.use(initReactI18next).init({
  resources: {
    ko: { sage: koSage },
    en: { sage: enSage },
  },
  lng: resolveInitialLang(),
  fallbackLng: 'en',
  defaultNS: 'sage',
  ns: ['sage'],
  interpolation: {
    escapeValue: false,
  },
})

export function setLanguage(lang: SupportedLang): void {
  if (!(SUPPORTED_LANGS as readonly string[]).includes(lang)) return
  void i18n.changeLanguage(lang)
  if (typeof window !== 'undefined') {
    try {
      window.localStorage.setItem(STORAGE_KEY, lang)
    } catch {
      // ignore — language still applied in-memory
    }
  }
}

export default i18n
