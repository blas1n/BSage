import { Page, Locator } from "@playwright/test";

export class DashboardPage {
  readonly page: Page;
  readonly heading: Locator;

  constructor(page: Page) {
    this.page = page;
    this.heading = page.locator("h2", { hasText: "Dashboard" });
  }

  async goto() {
    await this.page.goto("/#/dashboard");
    await this.heading.waitFor({ timeout: 10000 });
  }

  getPluginCard(name: string): Locator {
    // Find the card container that contains the plugin name
    // Use a locator chain: find h4 with plugin name, then closest card ancestor
    return this.page
      .locator("[data-testid='plugin-card']")
      .filter({ has: this.page.locator("h4", { hasText: name }) });
  }

  async isPluginVisible(name: string): Promise<boolean> {
    return await this.page.locator("h4", { hasText: name }).isVisible();
  }

  async hasNeedsSetupBadge(name: string): Promise<boolean> {
    const card = this.getPluginCard(name);
    return await card.getByText(/needs setup/i).isVisible();
  }

  async hasDangerousBadge(name: string): Promise<boolean> {
    const card = this.getPluginCard(name);
    return await card.getByText(/dangerous/i).isVisible();
  }
}
