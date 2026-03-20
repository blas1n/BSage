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
    // Card is a .border.rounded-lg div containing an h4 with the plugin name
    // Go up from h4 → flex wrapper → card container (3 levels)
    return this.page
      .locator("h4", { hasText: name })
      .locator("../../..");
  }

  async isPluginVisible(name: string): Promise<boolean> {
    return await this.page.locator("h4", { hasText: name }).isVisible();
  }

  async hasNeedsSetupBadge(name: string): Promise<boolean> {
    const card = this.getPluginCard(name);
    return await card.locator("text=needs setup").isVisible();
  }

  async hasDangerousBadge(name: string): Promise<boolean> {
    const card = this.getPluginCard(name);
    return await card.locator("text=dangerous").isVisible();
  }
}
