/**
 * Dev-mode interactive verification of the MCP API key (PAT) flow.
 * Run via:
 *   pnpm test:e2e e2e/mcp-pat-flow.spec.ts --project=chromium
 *
 * Covers:
 *  - Plugins page renders the BSage MCP Server virtual card
 *  - Click → modal opens with empty keys state
 *  - Generate a new key → POST hits, raw token shown ONCE
 *  - Token auto-injects into Cursor / Claude Desktop snippets
 *  - Active key list updates after generate
 *  - Revoke removes from active list
 */
import { expect, test as base } from "./fixtures";

type StoredKey = {
  id: string;
  name: string;
  created_at: string;
  last_used_at: string | null;
  revoked_at: string | null;
};

const test = base.extend<{ pat: { keys: StoredKey[] } }>({
  pat: async ({ page }, use) => {
    const store: { keys: StoredKey[] } = { keys: [] };

    await page.route("**/api/mcp/api-keys", async (route) => {
      const req = route.request();
      const method = req.method();
      if (method === "GET") {
        return route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify(store.keys.filter((k) => !k.revoked_at)),
        });
      }
      if (method === "POST") {
        const body = JSON.parse(req.postData() || "{}");
        const id = `key_${store.keys.length + 1}`;
        const issued = {
          id,
          name: body.name,
          token: `bsg_mcp_${id}_secret_xxx`,
          created_at: new Date().toISOString(),
          last_used_at: null,
          revoked_at: null,
        };
        store.keys.push(issued);
        return route.fulfill({
          status: 201,
          contentType: "application/json",
          body: JSON.stringify(issued),
        });
      }
      return route.fallback();
    });

    await page.route("**/api/mcp/api-keys/**", async (route) => {
      if (route.request().method() === "DELETE") {
        const url = new URL(route.request().url());
        const id = decodeURIComponent(url.pathname.split("/").pop() || "");
        const k = store.keys.find((x) => x.id === id);
        if (k) k.revoked_at = new Date().toISOString();
        return route.fulfill({ status: 204, body: "" });
      }
      return route.fallback();
    });

    await use(store);
  },
});

test.describe("MCP PAT flow — Plugins MCP card → Setup modal", () => {
  test.beforeEach(async ({ pat }) => {
    void pat; // route handlers installed by fixture
  });

  test("card → modal → empty state → tabs render", async ({ page }) => {
    await page.goto("/#/plugins");
    await page.locator('[data-testid="mcp-server-card"]').waitFor();
    await page.getByRole("button", { name: /Manage keys & connect/ }).click();

    await expect(page.getByText("Active keys")).toBeVisible();
    await expect(page.getByText(/No keys yet — generate/)).toBeVisible();
    await expect(page.getByRole("button", { name: "Cursor" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Claude Desktop" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Generic SSE" })).toBeVisible();
  });

  test("generate new key → token shown once + auto-injected into snippet", async ({
    page,
  }) => {
    await page.goto("/#/plugins");
    await page.getByRole("button", { name: /Manage keys & connect/ }).click();

    await page.getByPlaceholder("Name (e.g. cursor-laptop)").fill("my-cursor");
    await page.getByRole("button", { name: /\+ Generate/ }).click();

    // Raw token displayed in amber warning box
    await expect(page.getByText(/Copy this token now/)).toBeVisible();
    const tokenCode = page.locator("code", { hasText: "bsg_mcp_key_1_secret_xxx" }).first();
    await expect(tokenCode).toBeVisible();

    // Cursor snippet (default tab) auto-injects the token
    const snippet = page.locator("pre").first();
    await expect(snippet).toContainText("bsg_mcp_key_1_secret_xxx");
    await expect(snippet).toContainText("/mcp/sse");

    // Active key now lists the generated entry
    await expect(page.getByText("my-cursor")).toBeVisible();
  });

  test("switch to Claude Desktop tab → mcp-proxy bridge config", async ({ page }) => {
    await page.goto("/#/plugins");
    await page.getByRole("button", { name: /Manage keys & connect/ }).click();
    await page.getByPlaceholder("Name (e.g. cursor-laptop)").fill("desktop");
    await page.getByRole("button", { name: /\+ Generate/ }).click();

    await page.getByRole("button", { name: "Claude Desktop" }).click();
    const snippet = page.locator("pre").first();
    await expect(snippet).toContainText("uvx");
    await expect(snippet).toContainText("mcp-proxy");
    await expect(snippet).toContainText("bsg_mcp_key_1_secret_xxx");
  });

  test("revoke removes key from active list", async ({ page }) => {
    await page.goto("/#/plugins");
    await page.getByRole("button", { name: /Manage keys & connect/ }).click();
    await page.getByPlaceholder("Name (e.g. cursor-laptop)").fill("revoke-me");
    await page.getByRole("button", { name: /\+ Generate/ }).click();

    await expect(page.getByText("revoke-me")).toBeVisible();
    await page.getByRole("button", { name: "Revoke" }).click();
    await expect(page.getByText("revoke-me")).not.toBeVisible();
    // Empty state returns inside the modal (italic placeholder)
    await expect(page.getByText(/No keys yet — generate/)).toBeVisible();
  });

  test("modal closes on backdrop click + reopens", async ({ page }) => {
    await page.goto("/#/plugins");
    await page.getByRole("button", { name: /Manage keys & connect/ }).click();
    // "Generate new key" only renders inside the modal — uniquely identifies it
    await expect(page.getByText("Generate new key")).toBeVisible();
    // Use the exact aria-label "Close" (avoids "Close navigation" / "Close help panel")
    await page.getByRole("button", { name: "Close", exact: true }).click();
    await expect(page.getByText("Generate new key")).not.toBeVisible();
    // Reopen
    await page.getByRole("button", { name: /Manage keys & connect/ }).click();
    await expect(page.getByText("Generate new key")).toBeVisible();
  });
});

test.describe("Visual snapshots for new MCP card + modal", () => {
  test("modal with fresh token — desktop", async ({ page, pat }) => {
    void pat; // fixture installs the routes
    await page.setViewportSize({ width: 1280, height: 900 });
    await page.goto("/#/plugins");
    await page.getByRole("button", { name: /Manage keys & connect/ }).click();
    await page.getByPlaceholder("Name (e.g. cursor-laptop)").fill("demo");
    await page.getByRole("button", { name: /\+ Generate/ }).click();
    await page.waitForSelector("text=Copy this token now");
    await page.screenshot({ path: "test-results/visual/mcp-modal-token-desktop.png" });
  });

  test("modal — mobile", async ({ page, pat }) => {
    void pat;
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto("/#/plugins");
    await page.getByRole("button", { name: /Manage keys & connect/ }).click();
    await page.waitForSelector("text=Active keys");
    await page.screenshot({ path: "test-results/visual/mcp-modal-mobile.png" });
  });
});
