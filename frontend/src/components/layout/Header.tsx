import { useState } from "react";
import { useTranslation } from "react-i18next";
import type { ConnectionState } from "../../api/websocket";
import { HelpModal } from "../common/HelpModal";
import { Icon } from "../common/Icon";
import { StatusDot } from "../common/StatusDot";

interface HeaderProps {
  connectionState: ConnectionState;
  pendingApprovals: number;
}

export function Header({ connectionState, pendingApprovals }: HeaderProps) {
  const { t } = useTranslation();
  const [helpOpen, setHelpOpen] = useState(false);

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
