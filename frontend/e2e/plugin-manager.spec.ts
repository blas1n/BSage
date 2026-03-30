import { test, expect } from "./fixtures/index";
import { PluginManagerPage } from "./pages/PluginManagerPage";

test.describe("Plugin Manager", () => {
  let pmPage: PluginManagerPage;

  test.beforeEach(async ({ page }) => {
    pmPage = new PluginManagerPage(page);
    await pmPage.goto();
  });

  test("renders heading and entry cards", async () => {
    await expect(pmPage.heading).toBeVisible();

    expect(await pmPage.isEntryVisible("slack-input")).toBeTruthy();
    expect(await pmPage.isEntryVisible("shell-executor")).toBeTruthy();
    expect(await pmPage.isEntryVisible("weekly-digest")).toBeTruthy();
    expect(await pmPage.isEntryVisible("insight-linker")).toBeTruthy();
  });

  test("displays stats cards with correct counts", async () => {
    const total = await pmPage.getStatValue("Total");
    const active = await pmPage.getStatValue("Active");
    const dangerous = await pmPage.getStatValue("Dangerous");
    const needsSetup = await pmPage.getStatValue("Needs Setup");

    expect(total).toBe("4");
    expect(active).toBe("2");
    expect(dangerous).toBe("2");
    expect(needsSetup).toBe("1");
  });

  test("dangerous badge on dangerous entries", async () => {
    expect(await pmPage.hasDangerBadge("slack-input")).toBeTruthy();
    expect(await pmPage.hasDangerBadge("shell-executor")).toBeTruthy();
    expect(await pmPage.hasDangerBadge("weekly-digest")).toBeFalsy();
  });

  test("search filters entries", async () => {
    await pmPage.search("slack");

    expect(await pmPage.isEntryVisible("slack-input")).toBeTruthy();
    expect(await pmPage.isEntryVisible("shell-executor")).toBeFalsy();
    expect(await pmPage.isEntryVisible("weekly-digest")).toBeFalsy();
  });

  test("category filter narrows entries", async () => {
    await pmPage.getCategoryButton("Input").click();

    expect(await pmPage.isEntryVisible("slack-input")).toBeTruthy();
    // process entries should be hidden
    await expect(pmPage.getEntryCard("shell-executor")).not.toBeVisible();
    await expect(pmPage.getEntryCard("weekly-digest")).not.toBeVisible();
  });

  test("type filter shows only plugins or skills", async () => {
    await pmPage.getTypeButton("Skills").click();

    expect(await pmPage.isEntryVisible("weekly-digest")).toBeTruthy();
    expect(await pmPage.isEntryVisible("insight-linker")).toBeTruthy();
    await expect(pmPage.getEntryCard("slack-input")).not.toBeVisible();
    await expect(pmPage.getEntryCard("shell-executor")).not.toBeVisible();
  });

  test("empty filter state shows message", async () => {
    await pmPage.search("nonexistent-xyz-plugin");
    await expect(pmPage.getEmptyState()).toBeVisible();
  });

  test("Setup button opens modal for unconfigured entry", async ({ page }) => {
    await pmPage.clickSetup("slack-input");
    // SetupModal should appear
    await expect(page.getByText("Setup").first()).toBeVisible();
  });

  test("Run button sends API request", async ({ page }) => {
    const responsePromise = page.waitForResponse(
      (r) =>
        r.url().includes("/api/run/") &&
        r.request().method() === "POST"
    );

    await pmPage.clickRun("shell-executor");

    const response = await responsePromise;
    expect(response.status()).toBe(200);
  });
});
