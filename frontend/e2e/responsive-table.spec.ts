import { test, expect } from "./fixtures";

/**
 * Coverage for the `@bsvibe/ui` ResponsiveTable adoption (plugins /
 * settings / dashboard views). ResponsiveTable dual-renders the same
 * rows: a `<table>` at the `sm:` breakpoint and up, and a card stack
 * (`data-testid="bsvibe-table-card"`) below it.
 *
 * The `chromium` project is desktop (table visible); `pixel-5` /
 * `iphone-13` are mobile (cards visible). Each test branches on the
 * project name so it asserts the right tree for its viewport.
 */
function isMobile(projectName: string): boolean {
  return projectName !== "chromium";
}

test.describe("ResponsiveTable — Plugins view", () => {
  test("desktop shows <table>, mobile shows bsvibe-table-card articles", async ({
    page,
  }, testInfo) => {
    await page.goto("/plugins");
    await expect(page.getByText("shell-executor")).toBeVisible();

    if (isMobile(testInfo.project.name)) {
      const cards = page.locator("[data-testid='bsvibe-table-card']");
      await expect(cards.first()).toBeVisible();
      // slack-input + shell-executor cards, plus skill cards.
      expect(await cards.count()).toBeGreaterThanOrEqual(2);
    } else {
      // Desktop: a real <table> renders with the plugin column headers.
      const table = page.locator("table").first();
      await expect(table).toBeVisible();
      await expect(table.getByRole("columnheader", { name: "Name" })).toBeVisible();
      await expect(table.getByRole("columnheader", { name: "Trigger" })).toBeVisible();
      await expect(table.getByRole("columnheader", { name: "Status" })).toBeVisible();
    }
  });

  test("Skills collection also dual-renders", async ({ page }, testInfo) => {
    await page.goto("/plugins");
    await expect(page.getByRole("heading", { name: "Skills" })).toBeVisible();
    await expect(page.getByText("weekly-digest")).toBeVisible();

    if (isMobile(testInfo.project.name)) {
      await expect(
        page.locator("[data-testid='bsvibe-table-card']").first(),
      ).toBeVisible();
    } else {
      await expect(page.getByText("weekly-digest")).toBeVisible();
    }
  });
});

test.describe("ResponsiveTable — Dashboard recent files", () => {
  test("recent files dual-render as table / cards", async ({ page }, testInfo) => {
    await page.goto("/dashboard");
    await expect(page.getByText("Recent Activity")).toBeVisible();

    // Mock vault/tree exposes index.md / idea-1.md / messages.md.
    await expect(page.getByText("index.md").first()).toBeVisible();

    if (isMobile(testInfo.project.name)) {
      await expect(
        page.locator("[data-testid='bsvibe-table-card']").first(),
      ).toBeVisible();
    } else {
      const table = page.locator("table").first();
      await expect(table).toBeVisible();
      await expect(table.getByRole("columnheader", { name: "File" })).toBeVisible();
      await expect(
        table.getByRole("columnheader", { name: "Location" }),
      ).toBeVisible();
    }
  });
});
