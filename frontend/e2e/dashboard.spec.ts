import { test, expect } from "./fixtures";

test.describe("Dashboard status overview", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/#/dashboard");
  });

  test("shows Dashboard heading", async ({ page }) => {
    await expect(page.getByRole("heading", { name: "Dashboard" })).toBeVisible();
  });

  // --- Quick Stats ---
  test("shows four stat cards with labels", async ({ page }) => {
    const stats = page.locator("[data-testid='stat-card']");
    await expect(stats).toHaveCount(4);
  });

  test("stat cards display Total Notes count", async ({ page }) => {
    // Mock vault/tree has 3 files total: index.md, idea-1.md, messages.md
    await expect(page.getByText("Total Notes")).toBeVisible();
    await expect(page.locator("[data-testid='stat-total-notes']")).toContainText("3");
  });

  test("stat cards display Active Plugins count", async ({ page }) => {
    // Mock: shell-executor is enabled (1 active out of 2)
    await expect(page.getByText("Active Plugins")).toBeVisible();
    await expect(page.locator("[data-testid='stat-active-plugins']")).toContainText("1");
  });

  test("stat cards display Active Skills count", async ({ page }) => {
    // Mock: weekly-digest is enabled (1 active out of 2)
    await expect(page.getByText("Active Skills")).toBeVisible();
    await expect(page.locator("[data-testid='stat-active-skills']")).toContainText("1");
  });

  test("stat cards display Knowledge Entries count", async ({ page }) => {
    // Mock vault/search returns [] so count is 0
    await expect(page.getByText("Knowledge Entries")).toBeVisible();
    await expect(page.locator("[data-testid='stat-knowledge']")).toContainText("0");
  });

  // --- Quick Actions ---
  test("shows Quick Actions section with navigation buttons", async ({ page }) => {
    await expect(page.getByText("Quick Actions")).toBeVisible();

    await expect(page.getByRole("link", { name: "New Chat Session" })).toBeVisible();
    await expect(page.getByRole("link", { name: "Browse Vault" })).toBeVisible();
    await expect(page.getByRole("link", { name: "View Graph" })).toBeVisible();
  });

  test("New Chat Session navigates to chat", async ({ page }) => {
    await page.getByRole("link", { name: "New Chat Session" }).click();
    await expect(page).toHaveURL(/#\//);
  });

  test("Browse Vault navigates to vault", async ({ page }) => {
    await page.getByRole("link", { name: "Browse Vault" }).click();
    await expect(page).toHaveURL(/#\/vault/);
  });

  test("View Graph navigates to graph", async ({ page }) => {
    await page.getByRole("link", { name: "View Graph" }).click();
    await expect(page).toHaveURL(/#\/graph/);
  });

  // --- System Status ---
  test("shows System Status section with WebSocket state", async ({ page }) => {
    await expect(page.getByText("System Status")).toBeVisible();
    // Should show connection status (Offline in test since no real WS)
    await expect(page.getByText("WebSocket")).toBeVisible();
  });

  test("shows plugin status summary in System Status", async ({ page }) => {
    // 1 running (shell-executor enabled), 1 stopped (slack-input disabled)
    await expect(page.getByText("Plugin Status")).toBeVisible();
    await expect(page.getByText(/1 running/)).toBeVisible();
    await expect(page.getByText(/1 stopped/)).toBeVisible();
  });

  // --- No plugin management controls ---
  test("does NOT show plugin toggle switches", async ({ page }) => {
    const toggles = page.locator("input[type='checkbox']");
    await expect(toggles).toHaveCount(0);
  });

  test("does NOT show Run buttons for plugins", async ({ page }) => {
    await expect(page.getByRole("button", { name: "Run" })).not.toBeVisible();
  });

  // --- Recent Activity ---
  test("shows Recent Activity section", async ({ page }) => {
    await expect(page.getByText("Recent Activity")).toBeVisible();
  });
});
