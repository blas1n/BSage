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
    return this.page
      .locator("section")
      .filter({ has: this.page.locator("h3", { hasText: "LLM Model" }) })
      .first();
  }

  get llmModelInput(): Locator {
    return this.getLLMModelSection().locator("input[type='text']").first();
  }

  get saveButton(): Locator {
    return this.getLLMModelSection().getByRole("button", { name: "Save" }).first();
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
    // sr-only checkbox is covered by visual div; use force to bypass
    await this.safeModeToggle.click({ force: true });
  }

  async isSafeModeEnabled(): Promise<boolean> {
    return await this.safeModeToggle.isChecked();
  }

  /** Check if API key is configured (green dot visible) */
  async hasApiKeyConfigured(): Promise<boolean> {
    return await this.page.getByText("API key configured").isVisible();
  }
}
