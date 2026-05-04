/**
 * Dev-mode interactive verification of the Imports & Exports tab.
 *
 * One-shot data migration plugins (trigger=on_demand + category=input/output)
 * live here, separate from persistent integrations on /#/plugins.
 */
import { expect, test } from "./fixtures";

test.describe("Imports & Exports tab", () => {
  test("sidebar nav exposes the new entry", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByRole("link", { name: /Imports & Exports/ })).toBeVisible();
  });

  test("page lists chatgpt-memory-input under Imports", async ({ page }) => {
    await page.goto("/#/imports");
    await page.waitForSelector("text=Imports & Exports");
    await expect(page.locator('h2', { hasText: "Imports" })).toBeVisible();
    await expect(page.getByText("chatgpt-memory-input")).toBeVisible();
  });

  test("page lists obsidian-output under Exports", async ({ page }) => {
    await page.goto("/#/imports");
    await page.waitForSelector("text=Imports & Exports");
    await expect(page.locator('h2', { hasText: "Exports" })).toBeVisible();
    await expect(page.getByText("obsidian-output")).toBeVisible();
  });

  test("Plugins page no longer lists one-shot import plugins", async ({ page }) => {
    await page.goto("/#/plugins");
    await page.waitForSelector("text=Plugins");
    await expect(page.getByText("chatgpt-memory-input")).not.toBeVisible();
    await expect(page.getByText("obsidian-output")).not.toBeVisible();
    // Persistent ones still shown
    await expect(page.getByText("slack-input")).toBeVisible();
    await expect(page.getByText("shell-executor")).toBeVisible();
  });

  test("Import button on a chatgpt card opens the upload modal", async ({ page }) => {
    await page.goto("/#/imports");
    await page.waitForSelector("text=chatgpt-memory-input");
    const card = page.locator("[data-testid='io-card']").filter({
      hasText: "chatgpt-memory-input",
    });
    await card.getByRole("button", { name: /Import/ }).click();
    await expect(page.getByText("Import via chatgpt-memory-input")).toBeVisible();
    await expect(page.getByText(/Accepted: \.json/)).toBeVisible();
  });

  test("Export button on obsidian-output triggers /api/run directly (no modal)", async ({
    page,
  }) => {
    let invoked = false;
    await page.route("**/api/run/obsidian-output", (route) => {
      invoked = true;
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ name: "obsidian-output", results: [] }),
      });
    });

    await page.goto("/#/imports");
    await page.waitForSelector("text=obsidian-output");
    const card = page.locator("[data-testid='io-card']").filter({
      hasText: "obsidian-output",
    });
    await card.getByRole("button", { name: /Export/ }).click();
    await page.waitForTimeout(500);
    expect(invoked).toBe(true);
    // No upload modal because the schema doesn't declare upload_id/path —
    // output_vault_path is read from credentials.
    await expect(page.getByText("Export via")).not.toBeVisible();
  });
});

test.describe("Imports & Exports visual snapshots", () => {
  test("desktop", async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 800 });
    await page.goto("/#/imports");
    await page.waitForSelector("text=chatgpt-memory-input");
    await page.screenshot({ path: "test-results/visual/imports-exports-desktop.png" });
  });

  test("mobile", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto("/#/imports");
    await page.waitForSelector("text=chatgpt-memory-input");
    await page.screenshot({ path: "test-results/visual/imports-exports-mobile.png" });
  });
});
