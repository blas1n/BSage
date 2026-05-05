/**
 * BSage demo smoke tests.
 *
 * Run locally:
 *   ~/Works/_infra/scripts/demo-up-local.sh BSage
 *   DEMO_E2E_BASE_URL=http://localhost:18900 \
 *   DEMO_E2E_API_URL=http://localhost:18900 \
 *     pnpm test:e2e --grep @demo
 */

import { runDemoSmokeSuite } from "@bsvibe/demo/testing";

runDemoSmokeSuite({
  product: "BSage",
  baseUrl: process.env.DEMO_E2E_BASE_URL ?? "http://localhost:18900",
  apiUrl: process.env.DEMO_E2E_API_URL ?? "http://localhost:18900",
  // BSage demo uses a single shared tenant — the demo vault is one
  // showcase, not per-visitor.
  tenantModel: "shared",
});
