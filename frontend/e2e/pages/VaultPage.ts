import { Page, Locator } from "@playwright/test";

/**
 * Page Object Model for Vault page
 * Encapsulates selectors and interactions for browsing the vault
 */
export class VaultPage {
  readonly page: Page;
  readonly heading: Locator;
  readonly fileTree: Locator;
  readonly fileContent: Locator;
  readonly rawToggle: Locator;
  readonly renderedToggle: Locator;

  constructor(page: Page) {
    this.page = page;
    this.heading = page.getByRole("heading", { name: "Vault" });
    this.fileTree = page.locator("[data-testid='file-tree']");
    this.fileContent = page.locator("[data-testid='file-content']");
    this.rawToggle = page.locator("button:has-text('Raw')");
    this.renderedToggle = page.locator("button:has-text('Rendered')");
  }

  async goto() {
    await this.page.goto("/vault");
  }

  async getFileEntry(name: string): Promise<Locator> {
    return this.page.locator(`text=${name}`).first();
  }

  async isFileEntryVisible(name: string): Promise<boolean> {
    const entry = await this.getFileEntry(name);
    return await entry.isVisible();
  }

  async clickFileEntry(name: string) {
    const entry = await this.getFileEntry(name);
    await entry.click();
  }

  async getFileContentText(): Promise<string | null> {
    return await this.fileContent.textContent();
  }

  async switchToRaw() {
    await this.rawToggle.click();
  }

  async switchToRendered() {
    await this.renderedToggle.click();
  }

  async isRawMode(): Promise<boolean> {
    const classAttr = await this.fileContent.getAttribute("class");
    return classAttr?.includes("whitespace-pre-wrap") ?? false;
  }

  async isEmptyState(): Promise<boolean> {
    const message = await this.page
      .locator("text=Your vault is empty")
      .isVisible();
    return message;
  }

  async waitForTreeLoad() {
    await this.page.waitForResponse(
      (response) =>
        response.url().includes("/api/vault/tree") && response.status() === 200
    );
  }

  async waitForFileLoad() {
    await this.page.waitForResponse(
      (response) =>
        response.url().includes("/api/vault/file") && response.status() === 200
    );
  }
}
