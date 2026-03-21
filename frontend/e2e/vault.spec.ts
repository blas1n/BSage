import { test, expect } from "./fixtures/index";
import { VaultPage } from "./pages/VaultPage";

test.describe("Vault", () => {
  let vaultPage: VaultPage;

  test.beforeEach(async ({ page }) => {
    vaultPage = new VaultPage(page);
    await vaultPage.goto();
  });

  test("renders directory tree", async ({}) => {
    const gardenVisible = await vaultPage.isFileEntryVisible("garden");
    const seedsVisible = await vaultPage.isFileEntryVisible("seeds");

    expect(gardenVisible).toBeTruthy();
    expect(seedsVisible).toBeTruthy();
  });

  test("click file — displays content", async ({}) => {
    await vaultPage.clickFileEntry("index.md");
    await vaultPage.fileContent.waitFor({ timeout: 10000 });

    const content = await vaultPage.getFileContentText();
    expect(content).toBeTruthy();
    expect(content).toContain("BSage Vault");
  });

  test("Raw/Rendered toggle", async ({}) => {
    await vaultPage.clickFileEntry("index.md");
    await vaultPage.fileContent.waitFor({ timeout: 10000 });

    // Check initial rendered mode
    let isRaw = await vaultPage.isRawMode();
    expect(isRaw).toBeFalsy();

    // Switch to raw — switchToRaw now waits for content update
    await vaultPage.switchToRaw();
    isRaw = await vaultPage.isRawMode();
    expect(isRaw).toBeTruthy();

    // Switch back to rendered
    await vaultPage.switchToRendered();
    isRaw = await vaultPage.isRawMode();
    expect(isRaw).toBeFalsy();
  });

  test("empty vault guidance message", async ({ page }) => {
    // Mock empty vault response — unroute first to avoid handler collision
    await page.unroute("**/api/vault/tree");
    await page.route("**/api/vault/tree", (route) => {
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify([{ path: "", dirs: [], files: [] }]),
      });
    });

    // Reload page and wait for it to finish loading
    await page.reload();
    await vaultPage.heading.waitFor({ timeout: 10000 });

    const isEmpty = await vaultPage.isEmptyState();
    expect(isEmpty).toBeTruthy();
  });
});
