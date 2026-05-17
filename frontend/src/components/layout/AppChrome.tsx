'use client';

import type { ReactNode } from "react";
import { useT } from "@bsvibe/i18n";
import { DemoBanner, isDemoMode, useAutoDemoSession } from "@bsvibe/demo";
import { useApproval } from "../../hooks/useApproval";
import { injectDemoToken, useAuth } from "../../hooks/useAuth";
import { useWebSocket } from "../../hooks/useWebSocket";
import { ApprovalModal } from "../approval/ApprovalModal";
import { EventsProvider } from "../../contexts/EventsContext";
import { EventPanel } from "../events/EventPanel";
import { LandingPage } from "../landing/LandingPage";
import { Layout } from "./Layout";

const DEMO_API_URL =
  (typeof process !== "undefined" && process.env?.NEXT_PUBLIC_API_URL) ||
  "https://api-demo-sage.bsvibe.dev";

/**
 * Shared authed chrome for every App Router page.
 *
 * Owns the single mounts that must survive client-side navigation:
 *  - the auth gate (landing page vs. authed shell),
 *  - the `/ws` WebSocket connection (via `useWebSocket`),
 *  - the live event stream + approval queue,
 *  - the sidebar / header chrome (`Layout`) and the `EventPanel`.
 *
 * Rendered by `app/(app)/layout.tsx` so it is mounted ONCE for the whole
 * route group — App Router keeps the layout instance alive while only the
 * `children` (the route page) swap on navigation. This is what keeps the
 * WebSocket from being torn down and re-opened on every nav, which the old
 * single-page SPA got for free.
 */
function DemoChrome({ children }: { children: ReactNode }) {
  const { loading, error } = useAutoDemoSession(DEMO_API_URL, {
    onSessionReady: ({ token, expiresIn }) => {
      injectDemoToken(token, expiresIn);
    },
  });
  const { connectionState, events, clearEvents } = useWebSocket({
    enabled: !loading && !error,
  });
  const { current: approvalRequest, respond: respondApproval, pendingCount } =
    useApproval();
  const t = useT("sage");

  if (loading) {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center gap-4 bg-gray-950">
        <div className="text-gray-500">{t("common.loading")}</div>
        <div className="text-gray-600 text-sm">{t("demo.settingUp")}</div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-gray-950">
        <div className="text-center text-gray-400 p-8">
          <h1 className="text-xl font-bold mb-2 text-gray-100">{t("demo.unavailable")}</h1>
          <p className="text-sm">{error}</p>
        </div>
      </div>
    );
  }

  return (
    <EventsProvider events={events}>
      <DemoBanner productName="BSage" locale="en" />
      <Layout connectionState={connectionState} pendingApprovals={pendingCount}>
        <div className="flex flex-col h-full">
          <div className="flex-1 min-h-0">{children}</div>
          <EventPanel events={events} onClear={clearEvents} />
        </div>
        {approvalRequest && (
          <ApprovalModal request={approvalRequest} onRespond={respondApproval} />
        )}
      </Layout>
    </EventsProvider>
  );
}

function ProdChrome({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth({ probeRemoteSession: false });
  const { connectionState, events, clearEvents } = useWebSocket({
    enabled: Boolean(user),
  });
  const { current: approvalRequest, respond: respondApproval, pendingCount } =
    useApproval();
  const t = useT("sage");

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
      <Layout connectionState={connectionState} pendingApprovals={pendingCount}>
        <div className="flex flex-col h-full">
          <div className="flex-1 min-h-0">{children}</div>
          <EventPanel events={events} onClear={clearEvents} />
        </div>
        {approvalRequest && (
          <ApprovalModal request={approvalRequest} onRespond={respondApproval} />
        )}
      </Layout>
    </EventsProvider>
  );
}

export function AppChrome({ children }: { children: ReactNode }) {
  // Build-time switch — demo branch tree-shaken from prod bundles.
  return isDemoMode() ? (
    <DemoChrome>{children}</DemoChrome>
  ) : (
    <ProdChrome>{children}</ProdChrome>
  );
}
