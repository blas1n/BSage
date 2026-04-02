import type { ReactNode } from "react";
import type { ConnectionState } from "../../api/websocket";
import { Header } from "./Header";
import { Sidebar } from "./Sidebar";

interface LayoutProps {
  children: ReactNode;
  currentHash: string;
  connectionState: ConnectionState;
  pendingApprovals: number;
}

export function Layout({ children, currentHash, connectionState, pendingApprovals }: LayoutProps) {
  return (
    <div className="flex h-screen bg-surface-dim text-on-surface font-sans selection:bg-accent-light/30 selection:text-accent-light">
      <Sidebar currentHash={currentHash} />
      <div className="flex flex-col flex-1 min-w-0">
        <Header connectionState={connectionState} pendingApprovals={pendingApprovals} />
        <main className="flex-1 overflow-hidden bg-gray-900">{children}</main>
      </div>
    </div>
  );
}
