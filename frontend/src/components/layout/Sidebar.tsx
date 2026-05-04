import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  LanguageToggle,
  ResponsiveSidebar,
  SidebarBrand,
  SidebarTenantSwitcher,
  SidebarUserCard,
  type SidebarItem,
} from "@bsvibe/layout";
import { useAuth } from "../../hooks/useAuth";
import { setLanguage, SUPPORTED_LANGS, type SupportedLang } from "../../i18n";
import { Icon } from "../common/Icon";

interface SidebarProps {
  /**
   * Current hash route (e.g. "#/", "#/graph"). Drives the active-item
   * highlight because BSage runs as a single Next.js page with hash-based
   * client routing — so `usePathname()` always returns "/" and cannot
   * distinguish between hash routes on its own.
   */
  currentHash: string;
  isOpen: boolean;
  onOpenChange: (open: boolean) => void;
  onClose: () => void;
}

/**
 * BSage primary sidebar — wraps `@bsvibe/layout` `ResponsiveSidebar` with
 * the BSage-specific brand, user card, and "+ New Session" CTA.
 *
 * Routing note: BSage uses hash-based routing (`#/`, `#/graph`, `#/vault`,
 * `#/plugins`, `#/settings`) inside a single Next.js App Router page. The
 * shared `ResponsiveSidebar` ships with `next/link` which treats a
 * hash-only `href` as a same-page anchor — clicking updates
 * `window.location.hash`, which BSage's `useHashRoute` hook listens for.
 * Active state is derived from the parent-supplied `currentHash` prop and
 * applied via a `data-bsage-active` attribute that maps to the unified
 * `border-l-4 border-[var(--color-accent)]` pattern.
 */
export function Sidebar({ currentHash, isOpen, onOpenChange, onClose }: SidebarProps) {
  const { t, i18n } = useTranslation();
  const { user, logout, tenants, switchTenant } = useAuth();
  const userEmail = user?.email ?? "";
  const currentLang = (i18n.resolvedLanguage ?? i18n.language) as SupportedLang;

  // Track desktop viewport so the sidebar is always rendered as visible
  // (and not flagged `aria-hidden=true`) on `md:` and up. Without this,
  // `ResponsiveSidebar` keeps the closed-drawer aria-hidden state on
  // desktop too — the CSS still shows the rail, but assistive tech and
  // Playwright's accessible-name queries skip the entire nav.
  const [isDesktop, setIsDesktop] = useState(false);
  useEffect(() => {
    if (typeof window === "undefined" || !window.matchMedia) return;
    const mql = window.matchMedia("(min-width: 768px)");
    const update = () => setIsDesktop(mql.matches);
    update();
    mql.addEventListener("change", update);
    return () => mql.removeEventListener("change", update);
  }, []);

  const active = currentHash || "#/";

  // Map BSage hash routes onto `SidebarItem`s. The `href` strings start
  // with `#` so `next/link` treats them as anchor jumps (no Next router
  // navigation). The active-item highlight is layered on top via
  // `data-bsage-active` because `usePathname()` only sees `/` here.
  const navItems: { hash: string; icon: string; label: string }[] = [
    { hash: "#/", icon: "chat_bubble", label: t("nav.currentChat") },
    { hash: "#/graph", icon: "hub", label: t("nav.knowledgeBase") },
    { hash: "#/vault", icon: "folder_open", label: t("nav.vaultBrowser") },
    { hash: "#/plugins", icon: "extension", label: t("nav.plugins") },
    { hash: "#/imports", icon: "swap_horiz", label: t("nav.importsExports") },
    { hash: "#/settings", icon: "settings", label: t("nav.settings") },
  ];

  const isActive = (hash: string): boolean =>
    active === hash || (hash !== "#/" && active.startsWith(hash));

  const items: readonly SidebarItem[] = navItems.map(({ hash, icon, label }) => ({
    href: hash,
    icon: <Icon name={icon} size={20} />,
    label: (
      <span data-bsage-active={isActive(hash) ? "true" : undefined}>{label}</span>
    ),
  }));

  // The "+ New Session" CTA preserves the current behavior — it's a link
  // that routes back to `#/` (Chat view). The actual session-creation
  // wiring lives in `ChatView` via the `useChat().createSession` hook.
  const topAction = (
    <a
      href="#/"
      onClick={onClose}
      className="w-full inline-flex items-center justify-center gap-2 rounded-md px-3 py-2 text-sm font-semibold bg-[var(--color-accent)] text-gray-950 hover:bg-[var(--color-accent-hover)] focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-accent)] active:scale-95 transition-transform"
    >
      <Icon name="add" size={16} />
      <span>{t("nav.newSession")}</span>
    </a>
  );

  const logo = (
    <SidebarBrand
      icon={
        <span className="w-8 h-8 rounded-lg bg-[var(--color-accent)] inline-flex items-center justify-center">
          <Icon name="hub" className="text-gray-950 text-lg" filled />
        </span>
      }
      name="BSage"
      // Show the active workspace name (tenant). Collapses when not yet
      // known — unified with the other 3 products.
      tagline={user?.tenantName ?? undefined}
      href="#/"
    />
  );

  const footer = (
    <div className="flex flex-col gap-2">
      <SidebarTenantSwitcher
        tenants={tenants}
        activeTenantId={user?.tenantId ?? null}
        onSwitchTenant={(id) => void switchTenant(id)}
        dataTestId="sidebar-tenant-switcher"
      />
      <LanguageToggle
        value={currentLang}
        options={SUPPORTED_LANGS.map((l) => ({ value: l, label: l.toUpperCase() }))}
        onChange={(next) => setLanguage(next as SupportedLang)}
        ariaLabel={t("header.language")}
        dataTestId="lang-switcher"
      />
      <SidebarUserCard
        email={userEmail}
        onSignOut={() => {
          void logout();
        }}
        signOutLabel={t("nav.signOut")}
      />
    </div>
  );

  return (
    <ResponsiveSidebar
      items={items}
      logo={logo}
      footer={footer}
      topAction={topAction}
      open={isDesktop || isOpen}
      onOpenChange={onOpenChange}
    />
  );
}
