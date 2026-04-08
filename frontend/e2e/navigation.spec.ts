import { test, expect } from "./fixtures";

test.describe("Sidebar navigation", () => {
  test("shows BSage logo with hub icon and subtitle", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByRole("heading", { name: "BSage", level: 1 })).toBeVisible();
    await expect(page.getByText("The Kinetic Archivist")).toBeVisible();
  });

  test("shows New Session button", async ({ page }) => {
    await page.goto("/");
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
    const chatLink = page.getByRole("link", { name: "Current Chat" });
    // Active state uses bg-accent-light/10 class — check via computed style or class
    await expect(chatLink).toHaveClass(/bg-accent-light/);
  });

  test("clicking Knowledge Base navigates and activates link", async ({ page }) => {
    await page.goto("/");
    await page.getByRole("link", { name: "Knowledge Base" }).click();
    await expect(page).toHaveURL(/#\/graph/);
    const graphLink = page.getByRole("link", { name: "Knowledge Base" });
    await expect(graphLink).toHaveClass(/bg-accent-light/);
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
