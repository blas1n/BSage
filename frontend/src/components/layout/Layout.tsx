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
  // Drawer state lives on the Layout because the Sidebar is rendered as a
  // sibling of `<main>` and the (mobile) hamburger trigger ships with the
  // shared `ResponsiveSidebar` component itself — no separate trigger
  // button is needed in Layout anymore.
  const [sidebarOpen, setSidebarOpen] = useState(false);

  return (
    <div className="flex h-screen bg-surface-dim text-on-surface font-sans selection:bg-accent-light/30 selection:text-accent-light">
      <Sidebar
        currentHash={currentHash}
        isOpen={sidebarOpen}
        onOpenChange={setSidebarOpen}
        onClose={() => setSidebarOpen(false)}
      />
      <div className="flex flex-col flex-1 min-w-0">
        <Header connectionState={connectionState} pendingApprovals={pendingApprovals} />
        <main className="flex-1 overflow-hidden bg-gray-900 relative">{children}</main>
      </div>
      <HelpButton />
    </div>
  );
}
