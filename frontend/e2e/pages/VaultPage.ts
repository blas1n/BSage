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
    // Left panel = sidebar with directory tree
    this.fileTree = page.locator(
      ".w-56.shrink-0.border-r"
    );
    // Right panel content area
    this.fileContent = page.locator(".flex-1.overflow-y-auto.px-6");
    // Toggle button text changes between Raw/Rendered
    this.rawToggle = page.locator("button:has-text('Raw')");
    this.renderedToggle = page.locator("button:has-text('Rendered')");
  }

  async goto() {
    await this.page.goto("/#/vault");
    await this.heading.waitFor({ timeout: 10000 });
  }

  async getFileEntry(name: string): Promise<Locator> {
    return this.fileTree.locator(`text=${name}`).first();
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
    // In raw mode, a <pre> with whitespace-pre-wrap is rendered
    const pre = this.fileContent.locator("pre.whitespace-pre-wrap");
    return await pre.isVisible();
  }

  async isEmptyState(): Promise<boolean> {
    // VaultView shows "Vault is empty" text
    return await this.page.locator("text=Vault is empty").isVisible();
  }
}
