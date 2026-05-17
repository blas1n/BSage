'use client';

import dynamic from 'next/dynamic';

// `react-force-graph-2d` touches `window`/`canvas` at module-load time and
// fails in Node. SSR is disabled for THIS leaf only (per-page), instead of
// wrapping the whole app — every other route renders normally.
const KnowledgeGraphView = dynamic(
  () =>
    import('@/src/components/graph/KnowledgeGraphView').then(
      (m) => m.KnowledgeGraphView,
    ),
  { ssr: false },
);

export default function GraphPage() {
  return <KnowledgeGraphView />;
}
