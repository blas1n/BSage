'use client';

import './i18n';
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { DemoBanner, isDemoMode, useAutoDemoSession } from "@bsvibe/demo";
import { useApproval } from "./hooks/useApproval";
import { consumeAuthCallback, useAuth } from "./hooks/useAuth";
import { useWebSocket } from "./hooks/useWebSocket";
import { ApprovalModal } from "./components/approval/ApprovalModal";
import { EventsProvider } from "./contexts/EventsContext";
import { ChatView } from "./components/chat/ChatView";
import { DashboardView } from "./components/dashboard/DashboardView";
import { ImportsExportsView } from "./components/imports/ImportsExportsView";
import { PluginManagerView } from "./components/plugins/PluginManagerView";
import { EventPanel } from "./components/events/EventPanel";
import { KnowledgeGraphView } from "./components/graph/KnowledgeGraphView";
import { LandingPage } from "./components/landing/LandingPage";
import { Layout } from "./components/layout/Layout";
import { SettingsView } from "./components/settings/SettingsView";
import { VaultView } from "./components/vault/VaultView";

const DEMO_API_URL =
  (typeof process !== "undefined" && process.env?.NEXT_PUBLIC_API_URL) ||
  "https://api-demo-sage.bsvibe.dev";

function useHashRoute() {
  // SSR-safe initial value — hash is only available on the client.
  const [hash, setHash] = useState(() =>
    typeof window === "undefined" ? "#/" : window.location.hash || "#/",
  );
  useEffect(() => {
    const handler = () => setHash(window.location.hash || "#/");
    // `hashchange` covers user-driven anchor clicks and back/forward.
    // `popstate` covers programmatic history navigation.
    window.addEventListener("hashchange", handler);
    window.addEventListener("popstate", handler);
    // Next.js `<Link>` clicked with a hash-only href updates the URL
    // via `history.pushState` and does NOT fire `hashchange` (the
    // SPA stays on the single Next.js route). Patch `pushState` /
    // `replaceState` to broadcast a `hashchange`-equivalent so the
    // sidebar's active state stays in sync after sidebar nav clicks.
    const origPush = window.history.pushState;
    const origReplace = window.history.replaceState;
    window.history.pushState = function (...args) {
      const ret = origPush.apply(this, args);
      handler();
      return ret;
    };
    window.history.replaceState = function (...args) {
      const ret = origReplace.apply(this, args);
      handler();
      return ret;
    };
    return () => {
      window.removeEventListener("hashchange", handler);
      window.removeEventListener("popstate", handler);
      window.history.pushState = origPush;
      window.history.replaceState = origReplace;
    };
  }, []);
  return hash;
}

function RouteContent({ hash }: { hash: string }) {
  switch (hash) {
    case "#/dashboard":
      return <DashboardView />;
    case "#/plugins":
      return <PluginManagerView />;
    case "#/imports":
      return <ImportsExportsView />;
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

function DemoApp() {
  const { loading, error } = useAutoDemoSession(DEMO_API_URL);
  const hash = useHashRoute();
  const { connectionState, events, clearEvents } = useWebSocket({ enabled: !loading && !error });
  const { current: approvalRequest, respond: respondApproval, pendingCount } = useApproval();
  const { t } = useTranslation();

  if (loading) {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center gap-4 bg-gray-950">
        <div className="text-gray-500">{t("common.loading")}</div>
        <div className="text-gray-600 text-sm">Setting up your demo sandbox…</div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-gray-950">
        <div className="text-center text-gray-400 p-8">
          <h1 className="text-xl font-bold mb-2 text-gray-100">Demo unavailable</h1>
          <p className="text-sm">{error}</p>
        </div>
      </div>
    );
  }

  return (
    <EventsProvider events={events}>
      <DemoBanner productName="BSage" locale="en" />
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
    </EventsProvider>
  );
}

function ProdApp() {
  useEffect(() => {
    if (window.location.hash.startsWith("#/auth/callback") && consumeAuthCallback()) {
      window.location.replace(window.location.pathname + "#/");
    }
  }, []);

  const hash = useHashRoute();
  const { user, loading } = useAuth({ probeRemoteSession: false });
  const { connectionState, events, clearEvents } = useWebSocket({ enabled: Boolean(user) });
  const { current: approvalRequest, respond: respondApproval, pendingCount } = useApproval();
  const { t } = useTranslation();

  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-gray-950">
        <div className="text-gray-500">{t("common.loading")}</div>
      </div>
    );
  }

  if (!user) {
    return <LandingPage />;
  }

  return (
    <EventsProvider events={events}>
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
    </EventsProvider>
  );
}

export default function App() {
  // Build-time switch — demo branch tree-shaken from prod bundles.
  return isDemoMode() ? <DemoApp /> : <ProdApp />;
}
