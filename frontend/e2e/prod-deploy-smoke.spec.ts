/**
 * Production deploy smoke — runs against api-sage.bsvibe.dev WITHOUT auth.
 * Validates the Phase 1 / 4b / 5 changes are actually live in prod by
 * asserting endpoint contracts and frontend bundle markers.
 *
 *   pnpm test:e2e e2e/prod-deploy-smoke.spec.ts --project=chromium
 */

import { expect, test as base } from "@playwright/test";

const test = base; // bypass localhost mock fixture
const API = process.env.BSAGE_PROD_API || "https://api-sage.bsvibe.dev";
const FRONTEND = process.env.BSAGE_PROD_FRONTEND || "https://sage.bsvibe.dev";

test.describe("Backend — Phase 4b / 2a routes registered", () => {
  test("GET /api/health → ok", async ({ request }) => {
    const res = await request.get(`${API}/api/health`);
    expect(res.ok()).toBeTruthy();
    expect((await res.json()).status).toBe("ok");
  });

  test("OpenAPI lists /api/uploads + /mcp/health", async ({ request }) => {
    const res = await request.get(`${API}/openapi.json`);
    expect(res.ok()).toBeTruthy();
    const paths = Object.keys((await res.json()).paths);
    expect(paths).toContain("/api/uploads");
    // The MCP transport migrated from SSE to Streamable HTTP — the legacy
    // `/mcp/sse` + `/mcp/messages/{path}` routes were removed. The Streamable
    // HTTP transport is mounted at `/mcp` with a `/mcp/health` probe route.
    expect(paths).toContain("/mcp/health");
    expect(paths).not.toContain("/mcp/sse");
  });

  test("/api/uploads requires auth (401)", async ({ request }) => {
    const res = await request.post(`${API}/api/uploads`);
    expect(res.status()).toBe(401);
  });

  test("/mcp/health responds ok", async ({ request }) => {
    const res = await request
      .get(`${API}/mcp/health`, { timeout: 5000 })
      .catch(() => null);
    expect(res).not.toBeNull();
    expect(res!.ok()).toBeTruthy();
  });
});

test.describe("Frontend — Phase 1 / 5 bundle markers", () => {
  test("landing page returns 200", async ({ request }) => {
    const res = await request.get(FRONTEND);
    expect(res.ok()).toBeTruthy();
    expect((await res.text())).toContain("BSage");
  });

  test("loaded chunks include MCP Server section + graph view physics props", async ({ page }) => {
    const loaded: string[] = [];
    page.on("response", (r) => {
      const u = r.url();
      if (u.includes("/_next/static/") && u.endsWith(".js")) loaded.push(u);
    });

    await page.goto(FRONTEND);
    // Inject a fake-but-shaped JWT so the SPA mounts SettingsView.
    // Prod backend will reject it with 401 — expected. The chunk loads
    // happen before the API call, which is what we want.
    await page.evaluate(() => {
      const h = btoa(JSON.stringify({ alg: "none" }));
      const p = btoa(JSON.stringify({
        sub: "smoke", email: "smoke@bsvibe.dev",
        exp: 4102444800,
        app_metadata: { tenant_id: "smoke", role: "admin" },
      }));
      localStorage.setItem("bsage_access_token", `${h}.${p}.fake`);
      localStorage.setItem("bsage_refresh_token", "x");
      localStorage.setItem("bsage_expires_at", String(4102444800_000));
      location.hash = "#/settings";
    });
    await page.reload();
    // Wait for the SettingsView error branch to render — proves the
    // chunk that contains it loaded
    await page.waitForSelector("text=Failed to load settings", { timeout: 15000 });
    // Visit graph too so the graph chunk loads
    await page.evaluate(() => { location.hash = "#/graph"; });
    await page.waitForTimeout(1000);

    // Look for markers that prove the latest deploy shipped:
    //   - "MCP Server" — Settings section heading (PR #35)
    //   - "Manage keys & connect" — Settings → MCP card button (PR #35)
    //   - "warmupTicks" / "d3VelocityDecay" — graph view physics (PR #31 + #35)
    // Strings inside lazy-loaded modals (McpServerSetupModal, PluginUploadModal)
    // aren't asserted because they only download when the user actually opens
    // the modal — testing that requires a logged-in session.
    const markers = [
      "MCP Server",
      "Manage keys & connect",
      "warmupTicks",
      "d3VelocityDecay",
    ];
    const found = new Set<string>();
    for (const url of loaded) {
      const r = await page.request.get(url);
      const body = await r.text();
      for (const m of markers) if (body.includes(m)) found.add(m);
    }
    for (const m of markers) {
      expect(found, `marker not found in any loaded chunk: ${m}`).toContain(m);
    }
  });
});
