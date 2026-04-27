import { test, expect } from "./fixtures";

/**
 * Phase B Batch 2 — mobile viewport smoke flow.
 *
 * Runs against the `pixel-5` (393×851) and `iphone-13` (390×844) Playwright
 * projects. The chromium desktop project still owns the deep regression
 * suite — this file focuses on responsive chrome and the canonical user
 * flow (dashboard → drawer-nav → vault) on a small viewport.
 *
 * BSage is SPA-wide `ssr: false` (per Phase Z constraint). The hash router
 * resolves the route on the client after hydration so we always navigate
 * via `/#/<route>`.
 */

test.describe("Mobile viewport: BSage core flow", () => {
  test.beforeEach(async ({ page }, testInfo) => {
    if (testInfo.project.name === "chromium") {
      testInfo.skip();
    }
    await page.goto("/#/dashboard");
  });

  test("dashboard renders without horizontal overflow on mobile", async ({ page }) => {
    await expect(page.getByRole("heading", { name: "Dashboard" })).toBeVisible();
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(overflow).toBeLessThanOrEqual(2);
  });

  test("hamburger toggle opens the sidebar drawer", async ({ page }) => {
    const hamburger = page.getByRole("button", { name: /open navigation/i });
    await expect(hamburger).toBeVisible();
    await hamburger.click();
    // Backdrop appears — drawer is open.
    await expect(page.getByTestId("bsage-sidebar-backdrop")).toBeVisible();
    // Nav link reachable.
    await expect(page.getByRole("link", { name: /vault browser/i })).toBeVisible();
  });

  test("hamburger trigger meets 44px touch-target minimum", async ({ page }) => {
    const hamburger = page.getByRole("button", { name: /open navigation/i });
    const box = await hamburger.boundingBox();
    expect(box?.width ?? 0).toBeGreaterThanOrEqual(44);
    expect(box?.height ?? 0).toBeGreaterThanOrEqual(44);
  });

  test("clicking a sidebar link closes the drawer (mobile UX)", async ({ page }) => {
    await page.getByRole("button", { name: /open navigation/i }).click();
    await expect(page.getByTestId("bsage-sidebar-backdrop")).toBeVisible();
    await page.getByRole("link", { name: /vault browser/i }).click();
    // Backdrop is gone after navigation.
    await expect(page.getByTestId("bsage-sidebar-backdrop")).toHaveCount(0);
    await expect(page).toHaveURL(/#\/vault/);
  });

  test("backdrop click closes the drawer", async ({ page }) => {
    await page.getByRole("button", { name: /open navigation/i }).click();
    const backdrop = page.getByTestId("bsage-sidebar-backdrop");
    await expect(backdrop).toBeVisible();
    await backdrop.click();
    await expect(backdrop).toHaveCount(0);
  });

  test("vault browser is reachable via mobile drawer nav", async ({ page }) => {
    await page.getByRole("button", { name: /open navigation/i }).click();
    await page.getByRole("link", { name: /vault browser/i }).click();
    await expect(page).toHaveURL(/#\/vault/);
  });
});
