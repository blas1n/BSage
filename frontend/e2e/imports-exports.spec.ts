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

test.describe("ai-memory-input — instructions + source picker + result feedback", () => {
  test("modal shows source picker (Claude Code / Codex / opencode / Cursor / Custom)", async ({ page }) => {
    await page.goto("/#/imports");
    await page.waitForSelector("text=ai-memory-input");
    const card = page.locator("[data-testid='io-card']").filter({ hasText: "ai-memory-input" });
    await card.getByRole("button", { name: /Import/ }).click();

    await expect(page.getByRole("button", { name: "Claude Code" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Codex CLI" })).toBeVisible();
    await expect(page.getByRole("button", { name: "opencode" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Cursor" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Custom" })).toBeVisible();
  });

  test("instructions update when source changes", async ({ page }) => {
    await page.goto("/#/imports");
    const card = page.locator("[data-testid='io-card']").filter({ hasText: "ai-memory-input" });
    await card.getByRole("button", { name: /Import/ }).click();
    // Default = Claude Code
    await expect(page.getByText(/~\/\.claude\/CLAUDE\.md/)).toBeVisible();
    // Switch
    await page.getByRole("button", { name: "Codex CLI" }).click();
    await expect(page.getByText(/AGENTS\.md/)).toBeVisible();
  });

  test("import success surfaces result count", async ({ page }) => {
    await page.route("**/api/uploads", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          upload_id: "u1",
          path: "/tmp/u1/note.md",
          filename: "note.md",
          expires_at: new Date(Date.now() + 3600_000).toISOString(),
        }),
      }),
    );
    await page.route("**/api/run/ai-memory-input", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          name: "ai-memory-input",
          results: [{ imported: 3, source: "claude-code" }],
        }),
      }),
    );

    await page.goto("/#/imports");
    const card = page.locator("[data-testid='io-card']").filter({ hasText: "ai-memory-input" });
    await card.getByRole("button", { name: /Import/ }).click();

    // Inject a fake .md file
    await page.locator('input[type="file"]').setInputFiles({
      name: "memory.md",
      mimeType: "text/markdown",
      buffer: Buffer.from("# Hi\nbody"),
    });
    await page.getByRole("button", { name: /^Import$/ }).click();
    await expect(page.getByText("Import complete")).toBeVisible();
    await expect(page.getByText(/3 notes written.*claude-code/)).toBeVisible();
  });

  test("import error from plugin is surfaced (not silent)", async ({ page }) => {
    await page.route("**/api/uploads", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          upload_id: "u2",
          path: "/tmp/u2/file.txt",
          filename: "file.txt",
          expires_at: new Date(Date.now() + 3600_000).toISOString(),
        }),
      }),
    );
    await page.route("**/api/run/ai-memory-input", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          name: "ai-memory-input",
          results: [{ imported: 0, error: "unsupported extension: .txt" }],
        }),
      }),
    );

    await page.goto("/#/imports");
    const card = page.locator("[data-testid='io-card']").filter({ hasText: "ai-memory-input" });
    await card.getByRole("button", { name: /Import/ }).click();
    await page.locator('input[type="file"]').setInputFiles({
      name: "file.txt",
      mimeType: "text/plain",
      buffer: Buffer.from("not md"),
    });
    await page.getByRole("button", { name: /^Import$/ }).click();
    await expect(page.getByText(/unsupported extension/)).toBeVisible();
  });
});

test.describe("ai-memory-input visual snapshot", () => {
  test("modal with Claude Code source — desktop", async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 900 });
    await page.goto("/#/imports");
    await page.waitForSelector("text=ai-memory-input");
    const card = page.locator("[data-testid='io-card']").filter({ hasText: "ai-memory-input" });
    await card.getByRole("button", { name: /Import/ }).click();
    await page.waitForSelector("text=Claude Code");
    await page.screenshot({ path: "test-results/visual/ai-memory-modal-desktop.png" });
  });
});
