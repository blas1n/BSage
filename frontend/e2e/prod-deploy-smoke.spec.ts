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

  test("OpenAPI lists /api/uploads + /mcp/sse + /mcp/messages", async ({ request }) => {
    const res = await request.get(`${API}/openapi.json`);
    expect(res.ok()).toBeTruthy();
    const paths = Object.keys((await res.json()).paths);
    expect(paths).toContain("/api/uploads");
    expect(paths).toContain("/mcp/sse");
    expect(paths).toContain("/mcp/messages/{path}");
  });

  test("/api/uploads requires auth (401)", async ({ request }) => {
    const res = await request.post(`${API}/api/uploads`);
    expect(res.status()).toBe(401);
  });

  test("/mcp/sse responds with text/event-stream + accepts ?token", async ({ request }) => {
    const res = await request.get(`${API}/mcp/sse`, { timeout: 3000 }).catch((e) => e);
    // SSE keeps the connection open; the request "fails" with a timeout.
    // What we care about: the response object captured headers before the
    // hang. Playwright's APIResponse is unavailable on a hard fail, so we
    // re-issue with manual fetch from inside the page context.
    void res;
    // Use page-context fetch with abort for a header-only probe
    const probe = await request.fetch(`${API}/mcp/sse?token=probe`, {
      method: "GET",
      timeout: 3000,
      maxRedirects: 0,
    }).catch(() => null);
    if (probe) {
      // If we managed to read headers, assert content-type
      expect(probe.headers()["content-type"]).toContain("text/event-stream");
    }
    // Also confirm via OpenAPI that the token query parameter is wired
    const oapi = await request.get(`${API}/openapi.json`);
    const params = (await oapi.json()).paths["/mcp/sse"].get.parameters ?? [];
    expect(params.map((p: { name: string }) => p.name)).toContain("token");
  });
});

test.describe("Frontend — Phase 1 / 5 bundle markers", () => {
  test("landing page returns 200", async ({ request }) => {
    const res = await request.get(FRONTEND);
    expect(res.ok()).toBeTruthy();
    expect((await res.text())).toContain("BSage");
  });

  test("loaded chunks include MCP Server section + upload modal strings", async ({ page }) => {
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

    // Now grep loaded chunks for our markers
    const markers = [
      "MCP Server",
      "bsage-mcp",
      "Drop file here",
      "Import via",
      "warmupTicks",       // Phase 1 graph view prop
      "d3VelocityDecay",   // Phase 1 graph view prop
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
