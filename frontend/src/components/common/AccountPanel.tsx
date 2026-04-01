import { useCallback, useEffect, useRef } from "react";
import { Icon } from "./Icon";

interface AccountPanelProps {
  open: boolean;
  onClose: () => void;
  onSignOut: () => void;
  userEmail: string | null;
}

export function AccountPanel({ open, onClose, onSignOut, userEmail }: AccountPanelProps) {
  const overlayRef = useRef<HTMLDivElement>(null);

  const handleKeyDown = useCallback(
    (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    },
    [onClose],
  );

  useEffect(() => {
    if (open) {
      document.addEventListener("keydown", handleKeyDown);
      return () => document.removeEventListener("keydown", handleKeyDown);
    }
  }, [open, handleKeyDown]);

  if (!open) return null;

  return (
    <div
      ref={overlayRef}
      role="dialog"
      aria-label="Account"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm"
      onClick={(e) => {
        if (e.target === overlayRef.current) onClose();
      }}
    >
      <div className="bg-surface-container border border-white/10 rounded-xl w-full max-w-sm mx-4 shadow-2xl">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-white/5">
          <div className="flex items-center gap-2">
            <Icon name="account_circle" size={20} className="text-accent-light" />
            <h2 className="text-lg font-headline font-bold text-on-surface">Account</h2>
          </div>
          <button
            onClick={onClose}
            aria-label="Close account"
            className="text-gray-400 hover:text-on-surface p-1 rounded-lg transition-colors"
          >
            <Icon name="close" size={20} />
          </button>
        </div>

        {/* Content */}
        <div className="px-6 py-5 space-y-4">
          {/* User info */}
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-full bg-accent-light/10 flex items-center justify-center">
              <Icon name="person" size={24} className="text-accent-light" />
            </div>
            <div>
              <p className="text-sm font-medium text-on-surface" data-testid="account-email">
                {userEmail ?? "User"}
              </p>
              <p className="text-xs text-on-surface-variant">Authenticated via BSvibe</p>
            </div>
          </div>

          {/* Divider */}
          <div className="border-t border-white/5" />

          {/* Sign out */}
          <button
            onClick={() => {
              onSignOut();
              onClose();
            }}
            className="flex items-center gap-3 w-full px-3 py-2.5 text-sm text-red-400 hover:bg-red-400/10 rounded-lg transition-colors"
          >
            <Icon name="logout" size={20} />
            <span>Sign out</span>
          </button>
        </div>
      </div>
    </div>
  );
}
