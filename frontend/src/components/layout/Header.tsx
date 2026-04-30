import { useState } from "react";
import { useTranslation } from "react-i18next";
import { setLanguage, SUPPORTED_LANGS, type SupportedLang } from "../../i18n";
import type { ConnectionState } from "../../api/websocket";
import { HelpModal } from "../common/HelpModal";
import { Icon } from "../common/Icon";
import { StatusDot } from "../common/StatusDot";

interface HeaderProps {
  connectionState: ConnectionState;
  pendingApprovals: number;
}

const LANG_LABELS: Record<SupportedLang, string> = {
  en: "EN",
  ko: "KO",
};

export function Header({ connectionState, pendingApprovals }: HeaderProps) {
  const { t, i18n } = useTranslation();
  const [helpOpen, setHelpOpen] = useState(false);
  const currentLang = (i18n.resolvedLanguage ?? i18n.language) as SupportedLang;

  return (
    <>
      <header className="flex items-center justify-between px-6 h-14 border-b border-white/5 bg-gray-800 shrink-0">
        <div />
        <div className="flex items-center gap-4">
          {pendingApprovals > 0 && (
            <div className="flex items-center gap-1.5 text-tertiary">
              <Icon name="shield" size={18} />
              <span className="text-xs font-medium font-mono">
                {t("header.pendingApprovals", { count: pendingApprovals })}
              </span>
            </div>
          )}

          {/* Language switcher */}
          <div
            data-testid="lang-switcher"
            role="group"
            aria-label={t("header.language")}
            className="flex items-center bg-white/5 rounded-md overflow-hidden text-[10px] font-mono"
          >
            {SUPPORTED_LANGS.map((lng) => {
              const isActive = currentLang === lng;
              return (
                <button
                  key={lng}
                  type="button"
                  onClick={() => setLanguage(lng)}
                  aria-pressed={isActive}
                  data-testid={`lang-switcher-${lng}`}
                  className={`min-h-10 min-w-10 px-2 py-1 transition-colors ${
                    isActive
                      ? "bg-accent text-gray-950 font-bold"
                      : "text-gray-400 hover:text-on-surface"
                  }`}
                >
                  {LANG_LABELS[lng]}
                </button>
              );
            })}
          </div>

          <button
            onClick={() => setHelpOpen(true)}
            aria-label={t("header.help")}
            className="inline-flex min-h-10 min-w-10 items-center justify-center text-gray-400 hover:bg-white/5 p-2 rounded-lg transition-colors active:scale-95"
          >
            <Icon name="help" size={20} />
          </button>
          <StatusDot state={connectionState} />
        </div>
      </header>
      <HelpModal open={helpOpen} onClose={() => setHelpOpen(false)} />
    </>
  );
}
