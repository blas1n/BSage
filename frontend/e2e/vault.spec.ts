import { test, expect } from "./fixtures";

test.describe("Vault Browser view", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/#/vault");
  });

  test("shows Vault Explorer header", async ({ page }) => {
    await expect(page.getByRole("heading", { name: "Vault Explorer" })).toBeVisible();
  });

  test("shows file tree sidebar with search input", async ({ page }) => {
    const fileTree = page.locator("[data-testid='vault-file-tree']");
    await expect(fileTree).toBeVisible();
    await expect(fileTree.getByPlaceholder("Search vault...").first()).toBeVisible();
  });

  test("shows sidebar category buttons — Knowledge, Inbox, Log", async ({ page }) => {
    const fileTree = page.locator("[data-testid='vault-file-tree']");
    // Category buttons are in .px-2.space-y-1 container
    const categoryNav = fileTree.locator(".px-2.space-y-1");
    await expect(categoryNav.getByRole("button", { name: /Knowledge/ })).toBeVisible();
    await expect(categoryNav.getByRole("button", { name: /Inbox/ })).toBeVisible();
    await expect(categoryNav.getByRole("button", { name: /Log/ })).toBeVisible();
  });

  test("shows directory tree with vault folders", async ({ page }) => {
    const fileTree = page.locator("[data-testid='vault-file-tree']");
    // Directory tree is in the overflow-y-auto section (font-mono)
    const dirTree = fileTree.locator(".overflow-y-auto.font-mono");
    await expect(dirTree.getByText("garden").first()).toBeVisible();
    await expect(dirTree.getByText("seeds").first()).toBeVisible();
  });

  test("shows New Note button at the bottom of file tree", async ({ page }) => {
    await expect(page.getByRole("button", { name: "New Note" })).toBeVisible();
  });

  test("shows empty state when no file is selected", async ({ page }) => {
    await expect(page.getByText("Select a file to view its contents")).toBeVisible();
  });

  test("shows Create Seed FAB button", async ({ page }) => {
    await expect(page.getByText("Create Seed")).toBeVisible();
  });
});

test.describe("Note viewer", () => {
  test("clicking a file in tree shows note content with breadcrumbs", async ({ page }) => {
    await page.goto("/#/vault");

    // Click on a file in the directory tree (index.md under garden)
    await page.getByText("index.md").click();

    // Breadcrumb should show path parts
    await expect(page.getByText("Vault").first()).toBeVisible();

    // File content area should be visible
    const contentArea = page.locator("[data-testid='vault-file-content']");
    await expect(contentArea).toBeVisible();
  });

  test("note viewer shows title derived from filename", async ({ page }) => {
    await page.goto("/#/vault");
    await page.getByText("index.md").click();

    // Title is derived from the filename (index)
    await expect(page.getByRole("heading", { name: "index" })).toBeVisible();
  });

  test("shows metadata panel with YAML frontmatter", async ({ page }) => {
    await page.goto("/#/vault");
    await page.getByText("index.md").click();

    // Metadata section shows "Metadata (YAML)" label
    await expect(page.getByText("Metadata (YAML)")).toBeVisible();
  });

  test("shows raw/rendered toggle button", async ({ page }) => {
    await page.goto("/#/vault");
    await page.getByText("index.md").click();

    // Raw button should be visible
    await expect(page.getByText("Raw")).toBeVisible();
  });

  test("toggling to raw mode shows raw markdown content", async ({ page }) => {
    await page.goto("/#/vault");
    await page.getByText("index.md").click();

    // Click raw toggle
    await page.getByText("Raw").click();

    // Raw content should show the markdown source
    const rawContent = page.locator("[data-testid='vault-raw-content']");
    await expect(rawContent).toBeVisible();
    await expect(rawContent).toContainText("---");
  });

  test("shows footer metadata bar with key-value pairs", async ({ page }) => {
    await page.goto("/#/vault");
    await page.getByText("index.md").click();

    // Footer shows metadata from frontmatter
    const footer = page.locator("footer");
    await expect(footer).toBeVisible();
    await expect(footer.getByText("type:")).toBeVisible();
  });

  test("shows Synced status indicator in breadcrumb bar", async ({ page }) => {
    await page.goto("/#/vault");
    await page.getByText("index.md").click();

    await expect(page.getByText("Synced")).toBeVisible();
  });
});
