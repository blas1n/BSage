'use client';

import { VaultView } from '@/src/components/vault/VaultView';

// `/vault/actions` is the alias of `/vault` — preserves the legacy
// `#/actions` hash route, which also rendered the VaultView.
export default function VaultActionsPage() {
  return <VaultView />;
}
