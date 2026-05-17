import { test, expect } from "./fixtures";

/**
 * Korean locale routing — `[locale]` segment + `@bsvibe/i18n` middleware.
 *
 * Middleware runs `localePrefix: 'as-needed'` with `defaultLocale: 'en'`, so
 * the default-locale routes stay bare (`/`, `/graph`, …) and Korean is opt-in
 * under the `/ko` prefix. Visiting `/ko` must keep the prefix and render the
 * sidebar nav in Korean.
 */
test.describe("Korean locale (/ko)", () => {
  test("/ko renders the sidebar nav in Korean", async ({ page }) => {
    await page.goto("/ko");
    await expect(page).toHaveURL(/\/ko\/?$/);
    // `nav.currentChat` ko = "현재 대화"; `nav.knowledgeBase` ko = "지식 베이스".
    await expect(page.getByRole("link", { name: "현재 대화" })).toBeVisible();
    await expect(page.getByRole("link", { name: "지식 베이스" })).toBeVisible();
  });

  test("/ko/graph keeps the locale prefix", async ({ page }) => {
    await page.goto("/ko/graph");
    await expect(page).toHaveURL(/\/ko\/graph$/);
    await expect(page.getByRole("link", { name: "볼트 탐색기" })).toBeVisible();
  });

  test("html lang attribute reflects the ko locale", async ({ page }) => {
    await page.goto("/ko");
    await expect(page.locator("html")).toHaveAttribute("lang", "ko");
  });
});
