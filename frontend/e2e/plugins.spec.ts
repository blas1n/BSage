import { test, expect } from "./fixtures";

/**
 * The plugins / skills collections are now `@bsvibe/ui` ResponsiveTable
 * components: a real `<table>` at the `sm:` breakpoint and up, and a
 * card stack (the original PluginCard / SkillCard via `renderMobileCard`)
 * below `sm`. The `chromium` project is desktop (table visible); the
 * `pixel-5` / `iphone-13` projects are mobile (`bsvibe-table-card` cards
 * visible). Text-based assertions hold on both because only the visible
 * tree's text counts as visible.
 */
function isMobile(name: string): boolean {
  return name !== "chromium";
}

test.describe("Plugin Manager view", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/plugins");
  });

  test("shows Plugins page header", async ({ page }) => {
    await expect(page.getByRole("heading", { name: "Plugins" }).first()).toBeVisible();
    await expect(page.getByText("Extend your kinetic knowledge graph capabilities.")).toBeVisible();
  });

  test("shows Install Plugin button with extension icon", async ({ page }) => {
    await expect(page.getByRole("button", { name: /Install Plugin/ })).toBeVisible();
  });

  test("shows category filter pills — All, Input, Process, Output", async ({ page }) => {
    await expect(page.getByRole("button", { name: "All" }).first()).toBeVisible();
    await expect(page.getByRole("button", { name: "Input" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Process" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Output" })).toBeVisible();
  });

  test("shows type filter pills — All Types, Plugins, Skills", async ({ page }) => {
    await expect(page.getByRole("button", { name: "All Types" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Plugins" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Skills" })).toBeVisible();
  });

  test("shows search input for plugins", async ({ page }) => {
    await expect(page.getByPlaceholder("Search plugins...")).toBeVisible();
  });

  test("renders plugins with name, version, and description", async ({ page }) => {
    // One-shot import/export plugins (chatgpt-memory-input, obsidian-output)
    // moved to the Imports & Exports tab — only slack-input + shell-executor
    // remain on the Plugins page.
    await expect(page.getByText("slack-input")).toBeVisible();
    await expect(page.getByText("v1.0.0").first()).toBeVisible();
    await expect(page.getByText("shell-executor")).toBeVisible();
  });

  test("shows category badges on plugins", async ({ page }) => {
    // Category badges: INPUT, PROCESS
    await expect(page.getByText("input").first()).toBeVisible();
    await expect(page.getByText("process").first()).toBeVisible();
  });

  test("shows Is Dangerous badge on dangerous plugins", async ({ page }) => {
    // Both mock plugins are dangerous
    const dangerBadges = page.getByText("Is Dangerous");
    await expect(dangerBadges.first()).toBeVisible();
  });

  test("shows toggle switch on configured plugins", async ({ page }) => {
    // shell-executor has credentials_configured=true, so it shows a toggle
    const toggles = page.locator("input[type='checkbox']");
    // At least one toggle for shell-executor (table action cell or card)
    await expect(toggles.first()).toBeVisible();
  });

  test("shows Configure button for plugins needing credential setup", async ({ page }) => {
    // slack-input needs setup (has_credentials=true, credentials_configured=false)
    await expect(page.getByRole("button", { name: "Configure" }).first()).toBeVisible();
  });

  test("shows status dot with Running/Stopped label", async ({ page }) => {
    // shell-executor is enabled -> Running, slack-input is not -> Stopped
    await expect(page.getByText("Running").first()).toBeVisible();
    await expect(page.getByText("Stopped").first()).toBeVisible();
  });

  test("shows trigger metadata on plugins", async ({ page }) => {
    // Desktop: ResponsiveTable column header is "Trigger" + cell labels.
    // Mobile: the PluginCard keeps the "Trigger Type" metadata row.
    await expect(page.getByText("Webhook").first()).toBeVisible();
    await expect(page.getByText("On Demand").first()).toBeVisible();
  });

  test("filtering by Input category shows only input plugins", async ({ page }) => {
    await page.getByRole("button", { name: "Input" }).click();
    // chatgpt-memory-input moved to Imports & Exports — only slack-input remains
    await expect(page.getByText("slack-input")).toBeVisible();
    await expect(page.getByText("shell-executor")).not.toBeVisible();
  });

  test("search filters entries by name", async ({ page }) => {
    const searchInput = page.getByPlaceholder("Search plugins...");
    await searchInput.fill("shell");
    await expect(page.getByText("shell-executor")).toBeVisible();
    // slack-input should be filtered out
    await expect(page.getByText("slack-input")).not.toBeVisible();
  });
});

test.describe("Plugins ResponsiveTable — desktop table vs mobile cards", () => {
  test("desktop renders a real <table>; mobile collapses to cards", async ({
    page,
  }, testInfo) => {
    await page.goto("/plugins");
    await expect(page.getByText("shell-executor")).toBeVisible();

    if (isMobile(testInfo.project.name)) {
      // Mobile: PluginCard cards carry the bsvibe-table-card test id.
      const cards = page.locator("[data-testid='bsvibe-table-card']");
      await expect(cards.first()).toBeVisible();
      // No <table> visible below the sm breakpoint.
      await expect(page.locator("table").first()).toBeHidden();
    } else {
      // Desktop: a real <table> is visible, cards are hidden.
      await expect(page.locator("table").first()).toBeVisible();
      await expect(
        page.locator("[data-testid='bsvibe-table-card']").first(),
      ).toBeHidden();
    }
  });
});

test.describe("Skills section", () => {
  test("shows Skills heading with divider", async ({ page }) => {
    await page.goto("/plugins");
    await expect(page.getByRole("heading", { name: "Skills" })).toBeVisible();
  });

  test("renders skills with name, description, and Always Safe badge", async ({ page }) => {
    await page.goto("/plugins");
    await expect(page.getByText("weekly-digest")).toBeVisible();
    await expect(page.getByText("insight-linker")).toBeVisible();
    await expect(page.getByText("Always Safe").first()).toBeVisible();
  });

  test("skills show Run button", async ({ page }) => {
    await page.goto("/plugins");
    const skillSection = page.locator("section").filter({ has: page.getByRole("heading", { name: "Skills" }) });
    await expect(skillSection.getByText("Run").first()).toBeVisible();
  });
});

test.describe("Upload modal wiring (one-shot import) — Plugins still routes by handleRun", () => {
  test("plain plugin Run still calls /run directly (no modal)", async ({
    page,
  }, testInfo) => {
    await page.goto("/plugins");

    let ranDirectly = false;
    await page.route("**/api/run/shell-executor", (route) => {
      ranDirectly = true;
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ name: "shell-executor", results: [] }),
      });
    });

    if (isMobile(testInfo.project.name)) {
      // Mobile: shell-executor's PluginCard — the Run button is last.
      const card = page
        .locator("[data-testid='bsvibe-table-card']")
        .filter({ hasText: "shell-executor" });
      await card.locator("button").last().click();
    } else {
      // Desktop: shell-executor's table row — Run lives in the actions cell.
      const row = page.locator("tr", { hasText: "shell-executor" });
      await row.getByRole("button", { name: "Run" }).click();
    }
    await page.waitForTimeout(500);

    expect(ranDirectly).toBe(true);
    await expect(page.getByText("Import via")).not.toBeVisible();
  });
});
