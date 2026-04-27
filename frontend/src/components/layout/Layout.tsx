import { useState } from "react";
import type { ReactNode } from "react";
import type { ConnectionState } from "../../api/websocket";
import { HelpButton } from "../help/HelpButton";
import { Header } from "./Header";
import { Sidebar } from "./Sidebar";

interface LayoutProps {
  children: ReactNode;
  currentHash: string;
  connectionState: ConnectionState;
  pendingApprovals: number;
}

export function Layout({ children, currentHash, connectionState, pendingApprovals }: LayoutProps) {
  const [sidebarOpen, setSidebarOpen] = useState(false);

  return (
    <div className="flex h-screen bg-surface-dim text-on-surface font-sans selection:bg-accent-light/30 selection:text-accent-light">
      <Sidebar currentHash={currentHash} isOpen={sidebarOpen} onClose={() => setSidebarOpen(false)} />
      <div className="flex flex-col flex-1 min-w-0">
        <Header connectionState={connectionState} pendingApprovals={pendingApprovals} />
        <main className="flex-1 overflow-hidden bg-gray-900 relative">
          {/* Hamburger - mobile only */}
          <button
            type="button"
            aria-label="Open navigation"
            aria-expanded={sidebarOpen}
            className="md:hidden fixed top-3 left-4 z-30 p-2 rounded-lg bg-surface-dim text-gray-400 inline-flex items-center justify-center min-w-11 min-h-11"
            onClick={() => setSidebarOpen(true)}
          >
            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M4 6h16M4 12h16M4 18h16" />
            </svg>
          </button>
          {children}
        </main>
      </div>
      <HelpButton />
    </div>
  );
}
