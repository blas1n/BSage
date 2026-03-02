import { useEffect, useState } from "react";
import { useApproval } from "./hooks/useApproval";
import { useWebSocket } from "./hooks/useWebSocket";
import { ActionsView } from "./components/actions/ActionsView";
import { ApprovalModal } from "./components/approval/ApprovalModal";
import { ChatView } from "./components/chat/ChatView";
import { DashboardView } from "./components/dashboard/DashboardView";
import { EventPanel } from "./components/events/EventPanel";
import { Layout } from "./components/layout/Layout";
import { SettingsView } from "./components/settings/SettingsView";

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
    case "#/actions":
      return <ActionsView />;
    case "#/settings":
      return <SettingsView />;
    default:
      return <ChatView />;
  }
}

export default function App() {
  const hash = useHashRoute();
  const { connectionState, events, clearEvents } = useWebSocket();
  const { current: approvalRequest, respond: respondApproval, pendingCount } = useApproval();

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
