import ClientApp from './client-app';

// SPA root — disabled SSR via the dynamic-import client wrapper.
// The underlying App + nested components touch window/localStorage and pull in
// browser-only deps (react-force-graph-2d uses canvas at import time), so we
// render entirely on the client.
export const dynamic = 'force-dynamic';

export default function Page() {
  return <ClientApp />;
}
