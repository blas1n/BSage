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

test.describe("Plugins MCP card visual (PAT keys flow)", () => {
  test.beforeEach(async ({ page }) => {
    await page.route("**/api/mcp/api-keys", (r) =>
      r.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify([]),
      }),
    );
  });

  test("plugins page shows BSage MCP Server card — desktop", async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 800 });
    await page.goto("/#/plugins");
    await page.waitForSelector("text=BSage MCP Server");
    await page.screenshot({ path: "test-results/visual/plugins-mcp-card-desktop.png" });
  });

  test("plugins MCP card — mobile", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto("/#/plugins");
    await page.waitForSelector("text=BSage MCP Server");
    await page.screenshot({ path: "test-results/visual/plugins-mcp-card-mobile.png" });
  });

  test("MCP card opens Manage modal with empty keys state", async ({ page }) => {
    await page.goto("/#/plugins");
    await page.waitForSelector("text=BSage MCP Server");
    await page.getByRole("button", { name: /Manage keys & connect/ }).click();
    await expect(page.getByText("BSage MCP Server").nth(1)).toBeVisible();
    await expect(page.getByText("Generate new key")).toBeVisible();
    await expect(page.getByText("No keys yet")).toBeVisible();
    // Connect tabs
    await expect(page.getByRole("button", { name: "Cursor" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Claude Desktop" })).toBeVisible();
  });

  test("settings page no longer renders an MCP section", async ({ page }) => {
    await page.goto("/#/settings");
    await page.waitForSelector("text=Settings", { timeout: 5000 }).catch(() => null);
    // Pre-existing 'MCP Server' heading must NOT appear on Settings anymore
    await expect(page.locator("text=MCP Server")).not.toBeVisible();
  });
});
