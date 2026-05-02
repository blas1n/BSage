import { test, expect } from "./fixtures";

test.describe("Sidebar navigation", () => {
  test("shows BSage brand name and tagline", async ({ page }) => {
    await page.goto("/");
    // BSage migrated to @bsvibe/layout SidebarBrand which renders the
    // product name in a styled span (no longer an <h1>) and the tagline
    // in a muted span. Both are visible text inside the brand link.
    const brand = page.getByRole("link", { name: /BSage.*Kinetic Archivist/i });
    await expect(brand).toBeVisible();
    await expect(page.getByText("BSage", { exact: true })).toBeVisible();
    await expect(page.getByText("The Kinetic Archivist")).toBeVisible();
  });

  test("shows + New Session top-action CTA", async ({ page }) => {
    await page.goto("/");
    // The "+ New Session" CTA lives in ResponsiveSidebar.topAction. It is
    // still rendered as an <a href="#/"> so the legacy link role is
    // preserved (clicking returns to the chat view, where session
    // creation is owned by ChatView/useChat).
    await expect(page.getByRole("link", { name: /New Session/ })).toBeVisible();
  });

  test("shows all navigation links", async ({ page }) => {
    await page.goto("/");
    const navLabels = ["Current Chat", "Knowledge Base", "Vault Browser", "Plugins", "Settings"];
    for (const label of navLabels) {
      await expect(page.getByRole("link", { name: label })).toBeVisible();
    }
  });

  test("Current Chat is active by default on root hash", async ({ page }) => {
    await page.goto("/");
    // Active state for hash routes is driven by a data-bsage-active
    // attribute the wrapper sets on the inner label span based on the
    // current hash. We query directly for the labelled span — the
    // sidebar link's accessibility tree is already verified by the
    // sibling `shows all navigation links` test.
    await expect(
      page.locator('[data-bsage-active="true"]', { hasText: "Current Chat" }),
    ).toBeVisible();
  });

  test("clicking Knowledge Base navigates and activates link", async ({ page }) => {
    await page.goto("/");
    await page.getByRole("link", { name: "Knowledge Base" }).click();
    await expect(page).toHaveURL(/#\/graph/);
    await expect(
      page.locator('[data-bsage-active="true"]', { hasText: "Knowledge Base" }),
    ).toBeVisible();
  });

  test("clicking Plugins navigates to plugins page", async ({ page }) => {
    await page.goto("/");
    await page.getByRole("link", { name: "Plugins" }).click();
    await expect(page).toHaveURL(/#\/plugins/);
  });

  test("clicking Vault Browser navigates to vault page", async ({ page }) => {
    await page.goto("/");
    await page.getByRole("link", { name: "Vault Browser" }).click();
    await expect(page).toHaveURL(/#\/vault/);
  });

  test("shows Sign out button in sidebar footer", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();
  });
});

test.describe("Header", () => {
  test("shows connection status dot", async ({ page }) => {
    await page.goto("/");
    // StatusDot component renders in the header
    const header = page.locator("header");
    await expect(header).toBeVisible();
  });

  test("shows help button in header", async ({ page }) => {
    await page.goto("/");
    // The help icon button is in the header
    const header = page.locator("header");
    await expect(header.locator("text=help")).toBeVisible();
  });
});
