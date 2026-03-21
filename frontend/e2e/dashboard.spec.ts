import { test, expect } from "./fixtures/index";
import { DashboardPage } from "./pages/DashboardPage";

test.describe("Dashboard", () => {
  let dashboardPage: DashboardPage;

  test.beforeEach(async ({ page }) => {
    dashboardPage = new DashboardPage(page);
    await dashboardPage.goto();
  });

  test("renders plugin and skill list", async ({}) => {
    const slackVisible = await dashboardPage.isPluginVisible("slack-input");
    const shellVisible = await dashboardPage.isPluginVisible("shell-executor");

    expect(slackVisible).toBeTruthy();
    expect(shellVisible).toBeTruthy();
  });

  test("needs-setup badge and Setup button", async ({}) => {
    const hasBadge = await dashboardPage.hasNeedsSetupBadge("slack-input");
    expect(hasBadge).toBeTruthy();

    const card = dashboardPage.getPluginCard("slack-input");
    const setupButton = await card
      .getByRole("button", { name: "Setup" })
      .isVisible();
    expect(setupButton).toBeTruthy();
  });

  test("dangerous badge display", async ({}) => {
    const hasDangerousBadge =
      await dashboardPage.hasDangerousBadge("slack-input");
    expect(hasDangerousBadge).toBeTruthy();

    const shellDangerous =
      await dashboardPage.hasDangerousBadge("shell-executor");
    expect(shellDangerous).toBeTruthy();
  });

  test("Run button click sends API request", async ({ page }) => {
    const card = dashboardPage.getPluginCard("shell-executor");
    const runButton = card.getByRole("button", { name: "Run" });

    await expect(runButton).toBeVisible();

    // Monitor for run plugin request after click
    const responsePromise = page.waitForResponse(
      (r) =>
        r.url().includes("/api/run/") &&
        r.request().method() === "POST"
    );

    await runButton.click();

    const response = await responsePromise;
    expect(response.status()).toBe(200);
  });
});
