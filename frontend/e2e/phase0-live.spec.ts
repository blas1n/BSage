/**
 * Live smoke tests against the real backend.
 *
 * Disables the mockApiResponses fixture and hits the actual Gateway at
 * localhost:18400 through the dev server's NEXT_PUBLIC_API_URL. Validates that
 * Phase 0/1/6 endpoints return the expected data for a seeded vault.
 */

import { test as base, expect } from "@playwright/test";

// Bypass the auto-mock fixture — raw page, real network calls.
const test = base;

const BACKEND = process.env.BSAGE_BACKEND_URL || "http://localhost:18400";

test.describe("Phase 0/1/6 — live backend smoke", () => {
  test("GET /api/health returns ok", async ({ request }) => {
    const res = await request.get(`${BACKEND}/api/health`);
    expect(res.ok()).toBeTruthy();
    const body = await res.json();
    expect(body.status).toBe("ok");
  });

  test("GET /api/vault/graph returns seeded nodes", async ({ request }) => {
    const res = await request.get(`${BACKEND}/api/vault/graph`);
    expect(res.ok()).toBeTruthy();
    const body = await res.json();
    expect(Array.isArray(body.nodes)).toBeTruthy();
    expect(body.nodes.length).toBeGreaterThan(0);
  });

  test("GET /api/vault/communities (Phase 1) detects communities", async ({
    request,
  }) => {
    const res = await request.get(`${BACKEND}/api/vault/communities`);
    expect(res.ok()).toBeTruthy();
    const body = await res.json();
    expect(body.algorithm).toBe("louvain");
    expect(Array.isArray(body.communities)).toBeTruthy();
    expect(body.total).toBeGreaterThan(0);
    // Each community must have color + label
    for (const c of body.communities) {
      expect(c.color).toMatch(/^#[0-9a-f]{6}$/i);
      expect(typeof c.label).toBe("string");
      expect(c.size).toBeGreaterThanOrEqual(2);
    }
  });

  test("GET /api/vault/communities?algorithm=label_propagation works", async ({
    request,
  }) => {
    const res = await request.get(
      `${BACKEND}/api/vault/communities?algorithm=label_propagation`,
    );
    expect(res.ok()).toBeTruthy();
    const body = await res.json();
    expect(body.algorithm).toBe("label_propagation");
  });

  test("GET /api/vault/analytics (Phase 6) returns stats + centrality", async ({
    request,
  }) => {
    const res = await request.get(`${BACKEND}/api/vault/analytics?top_k=5`);
    expect(res.ok()).toBeTruthy();
    const body = await res.json();
    expect(body.stats).toBeTruthy();
    expect(body.stats.num_nodes).toBeGreaterThan(0);
    expect(Array.isArray(body.centrality)).toBeTruthy();
    expect(Array.isArray(body.god_nodes)).toBeTruthy();
    expect(body.gaps).toBeTruthy();
    // Centrality must be sorted by pagerank desc
    const ranks = body.centrality.map((n: { pagerank: number }) => n.pagerank);
    const sorted = [...ranks].sort((a, b) => b - a);
    expect(ranks).toEqual(sorted);
  });

  test("analytics detects Orphan note in thin/isolated gaps", async ({
    request,
  }) => {
    const res = await request.get(`${BACKEND}/api/vault/analytics`);
    const body = await res.json();
    const thinNames = body.gaps.thin.map((n: { name: string }) => n.name);
    const isolatedNames = body.gaps.isolated.map((n: { name: string }) => n.name);
    const allGapNames = [...thinNames, ...isolatedNames];
    expect(allGapNames).toContain("Orphan Note");
  });
});
