'use client';

import type { ReactNode } from 'react';
import { AppChrome } from '@/src/components/layout/AppChrome';

/**
 * Authed route-group layout.
 *
 * This layout is mounted ONCE for every page under `app/(app)/` — App Router
 * keeps the layout instance alive across client-side navigation and only
 * swaps the `children` (the route page). That is what lets `AppChrome` hold
 * the single `/ws` WebSocket connection, the auth gate, and the live event
 * stream without tearing them down on every nav.
 *
 * The route group `(app)` does not add a URL segment — `/`, `/dashboard`,
 * `/graph`, … all live directly under the domain root.
 */
export default function AppGroupLayout({ children }: { children: ReactNode }) {
  return <AppChrome>{children}</AppChrome>;
}
