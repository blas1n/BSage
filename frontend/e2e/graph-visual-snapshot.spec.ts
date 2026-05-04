import { test, expect } from "./fixtures";

/**
 * Visual snapshot capture for the Phase 1 graph view (mock 60-node data).
 * Not a regression assertion — generates artifacts under test-results/visual/
 * for human review.
 */

const N = 60;
const groups = ["garden", "seeds", "actions"];
const nodes = Array.from({ length: N }, (_, i) => ({
  id: `garden/n${i}.md`,
  name: `Note ${i}`,
  group: groups[i % 3],
}));
const links = Array.from({ length: 90 }, (_, i) => ({
  source: `garden/n${i % N}.md`,
  target: `garden/n${(i * 7 + 3) % N}.md`,
}));
const communities = {
  communities: [
    { id: 0, label: "cluster a", size: 20, cohesion: 0.8, members: nodes.slice(0, 20).map((n) => n.id), color: "#4edea3" },
    { id: 1, label: "cluster b", size: 20, cohesion: 0.7, members: nodes.slice(20, 40).map((n) => n.id), color: "#adc6ff" },
    { id: 2, label: "cluster c", size: 20, cohesion: 0.6, members: nodes.slice(40).map((n) => n.id), color: "#ffb95f" },
  ],
  algorithm: "louvain",
  total: 3,
};

test.describe("Graph view visual snapshot (Phase 1)", () => {
  test.beforeEach(async ({ page }) => {
    await page.route("**/api/vault/graph", (r) =>
      r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ nodes, links, truncated: false }) }),
    );
    await page.route("**/api/vault/communities**", (r) =>
      r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(communities) }),
    );
  });

  test("desktop with data", async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 800 });
    await page.goto("/#/graph");
    await page.waitForSelector("canvas");
    await page.waitForTimeout(2500); // let the simulation settle
    await page.screenshot({ path: "test-results/visual/graph-with-data-desktop.png" });
  });

  test("mobile with data", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto("/#/graph");
    await page.waitForSelector("canvas");
    await page.waitForTimeout(2500);
    await page.screenshot({ path: "test-results/visual/graph-with-data-mobile.png" });
  });

  test("desktop community color mode", async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 800 });
    await page.goto("/#/graph");
    await page.waitForSelector("canvas");
    await page.waitForTimeout(1500);
    await page.locator(".absolute.bottom-6.left-6").getByRole("button", { name: "Community" }).click();
    await page.waitForTimeout(1500);
    await page.screenshot({ path: "test-results/visual/graph-with-data-community-mode.png" });
  });
});

test.describe("Upload modal visual (Phase 5b)", () => {
  test("plugin manager with upload modal open", async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 800 });
    await page.goto("/#/plugins");
    const card = page.locator("[data-testid='plugin-card']").filter({
      hasText: "chatgpt-memory-input",
    });
    await card.locator("button").last().click();
    await page.waitForSelector("text=Import via chatgpt-memory-input");
    await page.screenshot({ path: "test-results/visual/upload-modal-desktop.png" });
  });

  test("plugin manager with upload modal — mobile", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto("/#/plugins");
    const card = page.locator("[data-testid='plugin-card']").filter({
      hasText: "chatgpt-memory-input",
    });
    await card.locator("button").last().click();
    await page.waitForSelector("text=Import via chatgpt-memory-input");
    await page.screenshot({ path: "test-results/visual/upload-modal-mobile.png" });
  });
});

test.describe("Settings MCP section visual (Phase 5c)", () => {
  test("settings page shows MCP Server section", async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 800 });
    await page.goto("/#/settings");
    const heading = page.locator("text=MCP Server").first();
    await heading.waitFor();
    // SettingsView has its own overflow-y-auto inner container — page-level
    // scroll is a no-op. Drive the inner scrollable ancestor instead.
    await heading.evaluate((el) => el.scrollIntoView({ block: "start" }));
    await page.waitForTimeout(300);
    await page.screenshot({ path: "test-results/visual/settings-mcp-desktop.png" });
  });

  test("settings MCP section — mobile", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto("/#/settings");
    const heading = page.locator("text=MCP Server").first();
    await heading.waitFor();
    await heading.evaluate((el) => el.scrollIntoView({ block: "start" }));
    await page.waitForTimeout(300);
    await page.screenshot({ path: "test-results/visual/settings-mcp-mobile.png" });
  });

  test("MCP section exposes bsage-mcp command + Claude Desktop config + SSE URL", async ({ page }) => {
    await page.goto("/#/settings");
    await page.waitForSelector("text=MCP Server");
    await expect(page.locator("text=bsage-mcp").first()).toBeVisible();
    await expect(page.locator("text=Claude Desktop config snippet")).toBeVisible();
    await expect(page.getByText("/api/mcp/sse")).toBeVisible();
  });
});
