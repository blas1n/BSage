import { Page, Locator } from "@playwright/test";

/**
 * Page Object Model for Settings page
 * Encapsulates selectors and interactions for configuration
 */
export class SettingsPage {
  readonly page: Page;
  readonly heading: Locator;
  readonly llmModelInput: Locator;
  readonly safeModeToggle: Locator;
  readonly saveButton: Locator;
  readonly cancelButton: Locator;

  constructor(page: Page) {
    this.page = page;
    this.heading = page.getByRole("heading", { name: "Settings" });
    this.llmModelInput = page.locator('input[type="text"]').first();
    this.safeModeToggle = page.getByLabel("Safe Mode");
    this.saveButton = page.locator("button:has-text('Save')");
    this.cancelButton = page.locator("button:has-text('Cancel')");
  }

  async goto() {
    await this.page.goto("/settings");
  }

  async getLLMModel(): Promise<string> {
    return await this.llmModelInput.inputValue();
  }

  async setLLMModel(model: string) {
    await this.llmModelInput.clear();
    await this.llmModelInput.fill(model);
  }

  async toggleSafeMode() {
    await this.safeModeToggle.click();
  }

  async isSafeModeEnabled(): Promise<boolean> {
    return await this.safeModeToggle.isChecked();
  }

  async clickSave() {
    await this.saveButton.click();
  }

  async clickCancel() {
    await this.cancelButton.click();
  }

  async isSaveButtonEnabled(): Promise<boolean> {
    return !(await this.saveButton.isDisabled());
  }

  async waitForConfigUpdate() {
    await this.page.waitForResponse(
      (response) =>
        response.url().includes("/api/config") &&
        response.request().method() === "PATCH" &&
        response.status() === 200
    );
  }

  async getHasLLMApiKeyStatus(): Promise<string | null> {
    return await this.page
      .locator("[data-testid='llm-api-key-status']")
      .textContent();
  }
}
