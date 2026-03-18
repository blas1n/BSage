import { test, expect } from "./fixtures/index";
import { VaultPage } from "./pages/VaultPage";

test.describe("Vault", () => {
  let vaultPage: VaultPage;

  test.beforeEach(async ({ page, mockApiResponses }) => {
    vaultPage = new VaultPage(page);
    await mockApiResponses();
    await vaultPage.goto();
    await vaultPage.waitForTreeLoad();
  });

  test("ディレクトリ トリー レンダリング", async ({}) => {
    const gardenVisible = await vaultPage.isFileEntryVisible("garden");
    const seedsVisible = await vaultPage.isFileEntryVisible("seeds");

    expect(gardenVisible).toBeTruthy();
    expect(seedsVisible).toBeTruthy();
  });

  test("ファイル クリック → 内容 表示", async ({}) => {
    await vaultPage.clickFileEntry("index.md");
    await vaultPage.waitForFileLoad();

    const content = await vaultPage.getFileContentText();
    expect(content).toBeTruthy();
    expect(content).toContain("BSage Vault");
  });

  test("Raw/Rendered トグル", async ({}) => {
    await vaultPage.clickFileEntry("index.md");
    await vaultPage.waitForFileLoad();

    // Check initial rendered mode
    let isRaw = await vaultPage.isRawMode();
    expect(isRaw).toBeFalsy();

    // Switch to raw
    await vaultPage.switchToRaw();
    isRaw = await vaultPage.isRawMode();
    expect(isRaw).toBeTruthy();

    // Switch back to rendered
    await vaultPage.switchToRendered();
    isRaw = await vaultPage.isRawMode();
    expect(isRaw).toBeFalsy();
  });

  test("空の vault ガイダンス メッセージ", async ({ page, mockApiResponses }) => {
    // Mock empty vault response
    await page.route("**/api/vault/tree", (route) => {
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          name: "vault",
          type: "directory",
          children: [],
        }),
      });
    });

    // Reload page
    await page.reload();
    await page.waitForTimeout(500);

    const isEmpty = await vaultPage.isEmptyState();
    expect(isEmpty).toBeTruthy();
  });
});
