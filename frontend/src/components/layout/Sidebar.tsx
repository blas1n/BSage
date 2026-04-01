import { useState } from "react";
import { useAuth } from "../../hooks/useAuth";
import { AccountPanel } from "../common/AccountPanel";
import { Icon } from "../common/Icon";

const NAV_ITEMS = [
  { hash: "#/", icon: "chat_bubble", label: "Current Chat" },
  { hash: "#/graph", icon: "hub", label: "Knowledge Base" },
  { hash: "#/dashboard", icon: "dashboard", label: "Dashboard" },
  { hash: "#/plugins", icon: "extension", label: "Plugins" },
  { hash: "#/vault", icon: "folder_open", label: "Vault Browser" },
  { hash: "#/settings", icon: "settings", label: "Settings" },
];

interface SidebarProps {
  currentHash: string;
}

/** Parse JWT payload to extract email (best-effort, no crypto verification). */
function extractEmailFromToken(): string | null {
  try {
    const token = localStorage.getItem("bsage_access_token");
    if (!token) return null;
    const b64 = token.split(".")[1].replace(/-/g, "+").replace(/_/g, "/");
    const payload = JSON.parse(atob(b64));
    return payload.email ?? payload.sub ?? null;
  } catch {
    return null;
  }
}

export function Sidebar({ currentHash }: SidebarProps) {
  const active = currentHash || "#/";
  const { signOut } = useAuth();
  const [accountOpen, setAccountOpen] = useState(false);

  return (
    <>
      <aside className="flex flex-col h-screen w-64 bg-surface-dim border-r border-white/5 shrink-0">
        {/* Logo */}
        <div className="flex items-center gap-3 px-6 py-5 mb-2">
          <div className="w-8 h-8 rounded-lg bg-accent flex items-center justify-center">
            <Icon name="hub" className="text-gray-950 text-lg" filled />
          </div>
          <div>
            <h1 className="font-headline font-bold text-lg tracking-tighter leading-tight text-on-surface">BSage</h1>
            <p className="text-[10px] uppercase tracking-widest text-gray-400 font-mono">The Kinetic Archivist</p>
          </div>
        </div>

        {/* New Session button */}
        <div className="px-4 mb-6">
          <a
            href="#/"
            className="w-full py-2.5 px-4 bg-accent-light text-gray-950 font-bold rounded-lg flex items-center justify-center gap-2 hover:opacity-90 transition-all active:scale-95 text-xs"
          >
            <Icon name="add" size={16} />
            <span>New Session</span>
          </a>
        </div>

        {/* Navigation */}
        <nav className="flex-1 px-2 space-y-0.5">
          {NAV_ITEMS.map(({ hash, icon, label }) => {
            const isActive = active === hash || (hash !== "#/" && active.startsWith(hash));
            return (
              <a
                key={hash}
                href={hash}
                className={`flex items-center gap-3 px-3 py-2 rounded-md text-xs font-medium transition-all ${
                  isActive
                    ? "bg-accent-light/10 text-accent-light translate-x-0.5"
                    : "text-gray-500 hover:bg-white/5 hover:text-accent-light"
                }`}
              >
                <Icon name={icon} size={20} />
                <span className="font-sans">{label}</span>
              </a>
            );
          })}
        </nav>

        {/* Footer */}
        <div className="border-t border-white/5 px-2 py-3 space-y-0.5">
          <button
            onClick={() => setAccountOpen(true)}
            className="flex items-center gap-3 px-3 py-2 text-gray-500 hover:bg-white/5 hover:text-accent-light rounded-md transition-all w-full text-xs font-medium"
          >
            <Icon name="account_circle" size={20} />
            <span className="font-sans">Account</span>
          </button>
          <button
            onClick={() => signOut()}
            className="flex items-center gap-3 px-3 py-2 text-gray-500 hover:bg-white/5 hover:text-red-400 rounded-md transition-all w-full text-xs font-medium"
          >
            <Icon name="logout" size={20} />
            <span className="font-sans">Sign out</span>
          </button>
        </div>
      </aside>
      <AccountPanel
        open={accountOpen}
        onClose={() => setAccountOpen(false)}
        onSignOut={signOut}
        userEmail={extractEmailFromToken()}
      />
    </>
  );
}
