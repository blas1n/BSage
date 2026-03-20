import { Page, Locator } from "@playwright/test";

export class SettingsPage {
  readonly page: Page;
  readonly heading: Locator;
  readonly safeModeToggle: Locator;

  constructor(page: Page) {
    this.page = page;
    this.heading = page.locator("h2", { hasText: "Settings" });
    // Toggle component renders sr-only checkbox input inside a label
    this.safeModeToggle = page.getByLabel("Safe Mode");
  }

  async goto() {
    await this.page.goto("/#/settings");
    await this.heading.waitFor({ timeout: 10000 });
  }

  private getLLMModelSection(): Locator {
    return this.page.locator("h3", { hasText: "LLM Model" }).locator("..");
  }

  get llmModelInput(): Locator {
    return this.getLLMModelSection().locator('input[type="text"]');
  }

  get saveButton(): Locator {
    return this.getLLMModelSection().locator("button", { hasText: "Save" });
  }

  async getLLMModel(): Promise<string> {
    return await this.llmModelInput.inputValue();
  }

  async setLLMModel(model: string) {
    await this.llmModelInput.clear();
    await this.llmModelInput.fill(model);
  }

  async clickSave() {
    await this.saveButton.click();
  }

  async toggleSafeMode() {
    // The toggle is a visual div wrapping a hidden checkbox; use check/uncheck
    if (await this.safeModeToggle.isChecked()) {
      await this.safeModeToggle.uncheck();
    } else {
      await this.safeModeToggle.check();
    }
  }

  async isSafeModeEnabled(): Promise<boolean> {
    return await this.safeModeToggle.isChecked();
  }

  /** Check if API key is configured (green dot visible) */
  async hasApiKeyConfigured(): Promise<boolean> {
    return await this.page.locator("text=API key configured").isVisible();
  }
}
