import { useEffect, useState } from "react";
import { useApproval } from "./hooks/useApproval";
import { consumeAuthCallback, useAuth } from "./hooks/useAuth";
import { useWebSocket } from "./hooks/useWebSocket";
import { ApprovalModal } from "./components/approval/ApprovalModal";
import { ChatView } from "./components/chat/ChatView";
import { DashboardView } from "./components/dashboard/DashboardView";
import { PluginManagerView } from "./components/plugins/PluginManagerView";
import { EventPanel } from "./components/events/EventPanel";
import { KnowledgeGraphView } from "./components/graph/KnowledgeGraphView";
import { LandingPage } from "./components/landing/LandingPage";
import { Layout } from "./components/layout/Layout";
import { SettingsView } from "./components/settings/SettingsView";
import { VaultView } from "./components/vault/VaultView";

function useHashRoute() {
  const [hash, setHash] = useState(window.location.hash || "#/");
  useEffect(() => {
    const handler = () => setHash(window.location.hash || "#/");
    window.addEventListener("hashchange", handler);
    return () => window.removeEventListener("hashchange", handler);
  }, []);
  return hash;
}

function RouteContent({ hash }: { hash: string }) {
  switch (hash) {
    case "#/dashboard":
      return <DashboardView />;
    case "#/plugins":
      return <PluginManagerView />;
    case "#/graph":
      return <KnowledgeGraphView />;
    case "#/vault":
    case "#/actions":
      return <VaultView />;
    case "#/settings":
      return <SettingsView />;
    default:
      return <ChatView />;
  }
}

export default function App() {
  useEffect(() => {
    if (window.location.hash.startsWith("#/auth/callback") && consumeAuthCallback()) {
      window.location.replace(window.location.pathname + "#/");
    }
  }, []);

  const hash = useHashRoute();
  const { user, loading } = useAuth();
  const { connectionState, events, clearEvents } = useWebSocket();
  const { current: approvalRequest, respond: respondApproval, pendingCount } = useApproval();

  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-gray-950">
        <div className="text-gray-500">Loading...</div>
      </div>
    );
  }

  if (!user) {
    return <LandingPage />;
  }

  return (
    <Layout
      currentHash={hash}
      connectionState={connectionState}
      pendingApprovals={pendingCount}
    >
      <div className="flex flex-col h-full">
        <div className="flex-1 min-h-0">
          <RouteContent hash={hash} />
        </div>
        <EventPanel events={events} onClear={clearEvents} />
      </div>
      {approvalRequest && (
        <ApprovalModal request={approvalRequest} onRespond={respondApproval} />
      )}
    </Layout>
  );
}
