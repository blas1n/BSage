import { test, expect } from "./fixtures/index";
import { KnowledgeGraphPage } from "./pages/KnowledgeGraphPage";

test.describe("Knowledge Graph", () => {
  let graphPage: KnowledgeGraphPage;

  test.beforeEach(async ({ page }) => {
    graphPage = new KnowledgeGraphPage(page);
    await graphPage.goto();
  });

  test("renders graph canvas and search input", async () => {
    await expect(graphPage.searchInput).toBeVisible();
    await expect(graphPage.graphCanvas).toBeVisible();
  });

  test("filter buttons are visible with labels", async () => {
    await expect(graphPage.getFilterButton("Ideas & Insights")).toBeVisible();
    await expect(graphPage.getFilterButton("Seeds")).toBeVisible();
    await expect(graphPage.getFilterButton("Actions")).toBeVisible();
    await expect(graphPage.getFilterButton("Other")).toBeVisible();
  });

  test("toggling all filters off shows empty state", async () => {
    // Click all filter buttons to deactivate them
    await graphPage.getFilterButton("Ideas & Insights").click();
    await graphPage.getFilterButton("Seeds").click();
    await graphPage.getFilterButton("Actions").click();
    await graphPage.getFilterButton("Other").click();

    await expect(graphPage.getEmptyState()).toBeVisible();
  });

  test("search with no matches shows empty state", async () => {
    await graphPage.search("nonexistent-node-xyz");
    await expect(graphPage.getEmptyState()).toBeVisible();
  });

  test("empty graph shows empty state", async ({ page }) => {
    await page.unroute("**/api/vault/graph");
    await page.route("**/api/vault/graph", (route) => {
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ nodes: [], links: [], truncated: false }),
      });
    });

    await page.reload();
    await graphPage.getEmptyState().waitFor({ timeout: 15000 });
    await expect(graphPage.getEmptyState()).toBeVisible();
  });
});
