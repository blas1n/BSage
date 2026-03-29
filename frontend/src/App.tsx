import { useEffect, useState } from "react";
import { Brain } from "lucide-react";
import { useApproval } from "./hooks/useApproval";
import { useAuth, redirectToLogin } from "./hooks/useAuth";
import { useWebSocket } from "./hooks/useWebSocket";
import { ApprovalModal } from "./components/approval/ApprovalModal";
import { ChatView } from "./components/chat/ChatView";
import { DashboardView } from "./components/dashboard/DashboardView";
import { EventPanel } from "./components/events/EventPanel";
import { KnowledgeGraphView } from "./components/graph/KnowledgeGraphView";
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
  const hash = useHashRoute();
  const { token, loading } = useAuth();
  const { connectionState, events, clearEvents } = useWebSocket();
  const { current: approvalRequest, respond: respondApproval, pendingCount } = useApproval();

  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-gray-950">
        <div className="text-gray-500">Loading...</div>
      </div>
    );
  }

  if (!token) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-gray-950 px-4">
        <div className="w-full max-w-sm space-y-8 text-center">
          <div className="flex flex-col items-center gap-3">
            <Brain className="w-12 h-12 text-accent" />
            <h1 className="text-3xl font-bold text-gray-100">BSage</h1>
            <p className="text-gray-500">
              Your personal AI-powered 2nd Brain
            </p>
          </div>
          <button
            onClick={() => redirectToLogin()}
            className="w-full rounded-lg bg-accent px-4 py-2.5 text-sm font-medium text-white hover:bg-accent-dark focus:outline-none focus:ring-2 focus:ring-accent/50 focus:ring-offset-2 focus:ring-offset-gray-950 transition-colors"
          >
            Sign in with BSVibe
          </button>
        </div>
      </div>
    );
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
