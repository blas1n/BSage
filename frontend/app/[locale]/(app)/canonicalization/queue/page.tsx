'use client';

import { CanonicalizationQueueView } from '@/src/components/canonicalization/CanonicalizationQueueView';

// `/canonicalization/queue` renders the same view as `/canonicalization` —
// preserves the legacy `#/canonicalization/queue` hash route.
export default function CanonicalizationQueuePage() {
  return <CanonicalizationQueueView />;
}
