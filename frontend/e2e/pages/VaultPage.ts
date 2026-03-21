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
    // Use data-testid for stable selectors; fall back to role-based
    this.fileTree = page.locator(
      "[data-testid='vault-file-tree'], nav[aria-label='File tree']"
    );
    this.fileContent = page.locator(
      "[data-testid='vault-file-content'], [role='main']"
    );
    // Toggle button text changes between Raw/Rendered
    this.rawToggle = page.getByRole("button", { name: "Raw" });
    this.renderedToggle = page.getByRole("button", { name: "Rendered" });
  }

  async goto() {
    await this.page.goto("/#/vault");
    await this.heading.waitFor({ timeout: 10000 });
  }

  async getFileEntry(name: string): Promise<Locator> {
    return this.fileTree.getByText(name, { exact: true }).first();
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
    // Wait for content area to update after toggle
    await this.fileContent.waitFor({ state: "visible" });
  }

  async switchToRendered() {
    await this.renderedToggle.click();
    // Wait for content area to update after toggle
    await this.fileContent.waitFor({ state: "visible" });
  }

  async isRawMode(): Promise<boolean> {
    const pre = this.fileContent.locator("[data-testid='vault-raw-content']");
    return await pre.isVisible();
  }

  async isEmptyState(): Promise<boolean> {
    // VaultView shows "Vault is empty" text
    return await this.page.getByText("Vault is empty").isVisible();
  }
}
