import { Page, Locator } from "@playwright/test";

export class PluginManagerPage {
  readonly page: Page;
  readonly heading: Locator;
  readonly searchInput: Locator;

  constructor(page: Page) {
    this.page = page;
    this.heading = page.getByRole("heading", { name: "Plugin Manager", level: 2 });
    this.searchInput = page.getByPlaceholder("Search entries...");
  }

  async goto() {
    await this.page.goto("/#/plugins");
    await this.heading.waitFor({ timeout: 10000 });
  }

  getEntryCard(name: string): Locator {
    return this.page
      .locator("[data-testid='plugin-card']")
      .filter({ hasText: name });
  }

  async isEntryVisible(name: string): Promise<boolean> {
    return await this.getEntryCard(name).isVisible();
  }

  getStatCard(label: string): Locator {
    return this.page.locator("div").filter({ hasText: label }).locator("..").first();
  }

  async getStatValue(label: string): Promise<string | null> {
    const container = this.page.locator(".grid.grid-cols-2 > div").filter({ hasText: label });
    return await container.locator("p.text-2xl").textContent();
  }

  getCategoryButton(category: string): Locator {
    return this.page.getByRole("button", { name: category, exact: true });
  }

  getTypeButton(label: string): Locator {
    return this.page.getByRole("button", { name: label, exact: true });
  }

  async search(query: string) {
    await this.searchInput.fill(query);
  }

  async clearSearch() {
    await this.searchInput.clear();
  }

  async hasDangerBadge(name: string): Promise<boolean> {
    const card = this.getEntryCard(name);
    return await card.getByText("danger").isVisible();
  }

  async clickSetup(name: string) {
    const card = this.getEntryCard(name);
    await card.getByRole("button", { name: "Setup" }).click();
  }

  async clickRun(name: string) {
    const card = this.getEntryCard(name);
    await card.getByRole("button", { name: "Run" }).click();
  }

  getEmptyState(): Locator {
    return this.page.getByText("No entries match your filters");
  }
}
