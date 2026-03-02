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
    <div className="flex h-screen bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100">
      <Sidebar currentHash={currentHash} />
      <div className="flex flex-col flex-1 min-w-0">
        <Header connectionState={connectionState} pendingApprovals={pendingApprovals} />
        <main className="flex-1 overflow-hidden">{children}</main>
      </div>
    </div>
  );
}
