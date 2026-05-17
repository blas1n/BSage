import { useEffect, useState } from "react";
import Link from "next/link";
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
  isOpen: boolean;
  onOpenChange: (open: boolean) => void;
  onClose: () => void;
}

/**
 * BSage primary sidebar — wraps `@bsvibe/layout` `ResponsiveSidebar` with
 * the BSage-specific brand, user card, and "+ New Session" CTA.
 *
 * Routing: BSage runs on the Next.js App Router with real route segments
 * (`/`, `/graph`, `/vault`, `/plugins`, `/imports`, `/canonicalization`,
 * `/settings`). `ResponsiveSidebar` ships `next/link` and derives the
 * active-item highlight from `usePathname()` itself — so the BSage wrapper
 * only supplies path `href`s and no longer tracks routing state.
 */
export function Sidebar({ isOpen, onOpenChange, onClose }: SidebarProps) {
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

  // BSage nav routes -> App Router path segments. `ResponsiveSidebar`
  // renders each as a `next/link` and computes the active highlight from
  // `usePathname()` (exact match for `/`, exact-or-child for the rest).
  const navItems: { path: string; icon: string; label: string }[] = [
    { path: "/", icon: "chat_bubble", label: t("nav.currentChat") },
    { path: "/graph", icon: "hub", label: t("nav.knowledgeBase") },
    { path: "/vault", icon: "folder_open", label: t("nav.vaultBrowser") },
    {
      path: "/canonicalization",
      icon: "rule",
      label: t("nav.canonicalization", "Canon queue"),
    },
    { path: "/plugins", icon: "extension", label: t("nav.plugins") },
    { path: "/imports", icon: "swap_horiz", label: t("nav.importsExports") },
    { path: "/settings", icon: "settings", label: t("nav.settings") },
  ];

  const items: readonly SidebarItem[] = navItems.map(({ path, icon, label }) => ({
    href: path,
    icon: <Icon name={icon} size={20} />,
    label: <span>{label}</span>,
  }));

  // The "+ New Session" CTA routes back to `/` (Chat view). The actual
  // session-creation wiring lives in `ChatView` via `useChat().createSession`.
  const topAction = (
    <Link
      href="/"
      onClick={onClose}
      className="w-full inline-flex items-center justify-center gap-2 rounded-md px-3 py-2 text-sm font-semibold bg-[var(--color-accent)] text-gray-950 hover:bg-[var(--color-accent-hover)] focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-accent)] active:scale-95 transition-transform"
    >
      <Icon name="add" size={16} />
      <span>{t("nav.newSession")}</span>
    </Link>
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
      href="/"
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
