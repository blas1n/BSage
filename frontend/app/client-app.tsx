'use client';

import dynamic from 'next/dynamic';

// Disable SSR for the entire SPA: nested components reference window at
// module-load time (react-force-graph-2d, hash router init, etc.) which fails
// in Node. ssr: false confines rendering to the browser.
const App = dynamic(() => import('@/src/App'), { ssr: false });

export default function ClientApp() {
  return <App />;
}
