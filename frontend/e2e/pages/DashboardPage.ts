import { Page, Locator } from "@playwright/test";

/**
 * Page Object Model for Dashboard page
 * Encapsulates selectors and interactions for viewing plugins and skills
 */
export class DashboardPage {
  readonly page: Page;
  readonly heading: Locator;
  readonly pluginContainer: Locator;
  readonly setupButtons: Locator;

  constructor(page: Page) {
    this.page = page;
    this.heading = page.getByRole("heading", { name: "Dashboard" });
    this.pluginContainer = page.locator("[data-testid='plugin-container']");
    this.setupButtons = page.locator("button:has-text('Setup')");
  }

  async goto() {
    await this.page.goto("/dashboard");
  }

  async getPluginCard(name: string): Promise<Locator> {
    return this.page.locator(`text=${name}`).first().locator("..");
  }

  async isPluginVisible(name: string): Promise<boolean> {
    const card = await this.getPluginCard(name);
    return await card.isVisible();
  }

  async getPluginCategory(name: string): Promise<string | null> {
    const card = await this.getPluginCard(name);
    return await card.locator("[data-testid='plugin-category']").textContent();
  }

  async hasNeedsSetupBadge(name: string): Promise<boolean> {
    const card = await this.getPluginCard(name);
    const badge = card.locator("text=needs-setup");
    return await badge.isVisible();
  }

  async hasDangerousBadge(name: string): Promise<boolean> {
    const card = await this.getPluginCard(name);
    const badge = card.locator("text=dangerous");
    return await badge.isVisible();
  }

  async clickSetupButton(name: string) {
    const card = await this.getPluginCard(name);
    await card.locator("button:has-text('Setup')").click();
  }

  async clickRunButton(name: string) {
    const card = await this.getPluginCard(name);
    await card.locator("button:has-text('Run')").click();
  }

  async waitForPluginCardLoad() {
    await this.page.waitForResponse(
      (response) =>
        response.url().includes("/api/plugins") && response.status() === 200
    );
  }
}
