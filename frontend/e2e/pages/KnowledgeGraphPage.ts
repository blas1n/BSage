import { Page, Locator } from "@playwright/test";

export class KnowledgeGraphPage {
  readonly page: Page;
  readonly searchInput: Locator;
  readonly graphCanvas: Locator;

  constructor(page: Page) {
    this.page = page;
    this.searchInput = page.getByPlaceholder("Search nodes...");
    this.graphCanvas = page.locator("canvas").first();
  }

  async goto() {
    await this.page.goto("/#/graph");
    // Wait for loading to finish — either canvas appears or empty state
    await this.page
      .locator("canvas")
      .or(this.page.getByText("No notes to graph"))
      .or(this.page.getByText("No nodes match"))
      .first()
      .waitFor({ timeout: 15000 });
  }

  getFilterButton(label: string): Locator {
    return this.page.getByRole("button", { name: label });
  }

  async search(query: string) {
    await this.searchInput.fill(query);
  }

  async clearSearch() {
    // Click the X clear button next to search
    const clearBtn = this.page.locator("button").filter({ has: this.page.locator("svg") }).filter({ hasText: "" });
    await this.searchInput.clear();
  }

  getEmptyState(): Locator {
    return this.page.getByText(/No nodes match|No notes to graph/);
  }

  getSidebar(): Locator {
    return this.page.locator(".w-80");
  }

  getSidebarTitle(): Locator {
    return this.getSidebar().locator("span.text-sm.font-medium");
  }

  getSidebarCloseButton(): Locator {
    return this.getSidebar().locator("button").first();
  }
}
