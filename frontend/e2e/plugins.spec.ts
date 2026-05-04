import { test, expect } from "./fixtures";

test.describe("Plugin Manager view", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/#/plugins");
  });

  test("shows Plugins page header", async ({ page }) => {
    await expect(page.getByRole("heading", { name: "Plugins" }).first()).toBeVisible();
    await expect(page.getByText("Extend your kinetic knowledge graph capabilities.")).toBeVisible();
  });

  test("shows Install Plugin button with extension icon", async ({ page }) => {
    await expect(page.getByRole("button", { name: /Install Plugin/ })).toBeVisible();
  });

  test("shows category filter pills — All, Input, Process, Output", async ({ page }) => {
    await expect(page.getByRole("button", { name: "All" }).first()).toBeVisible();
    await expect(page.getByRole("button", { name: "Input" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Process" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Output" })).toBeVisible();
  });

  test("shows type filter pills — All Types, Plugins, Skills", async ({ page }) => {
    await expect(page.getByRole("button", { name: "All Types" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Plugins" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Skills" })).toBeVisible();
  });

  test("shows search input for plugins", async ({ page }) => {
    await expect(page.getByPlaceholder("Search plugins...")).toBeVisible();
  });

  test("renders plugin cards with name, version, and description", async ({ page }) => {
    const cards = page.locator("[data-testid='plugin-card']");
    // Phase 5b adds chatgpt-memory-input to the fixture
    await expect(cards).toHaveCount(3);

    await expect(page.getByText("slack-input")).toBeVisible();
    await expect(page.getByText("v1.0.0").first()).toBeVisible();
    await expect(page.getByText("shell-executor")).toBeVisible();
    await expect(page.getByText("chatgpt-memory-input")).toBeVisible();
  });

  test("shows category badges on plugin cards", async ({ page }) => {
    // Category badges: INPUT, PROCESS
    await expect(page.getByText("input").first()).toBeVisible();
    await expect(page.getByText("process").first()).toBeVisible();
  });

  test("shows Is Dangerous badge on dangerous plugins", async ({ page }) => {
    // Both mock plugins are dangerous
    const dangerBadges = page.getByText("Is Dangerous");
    await expect(dangerBadges.first()).toBeVisible();
  });

  test("shows toggle switch on configured plugins", async ({ page }) => {
    // shell-executor has credentials_configured=true, so it shows a toggle
    const toggles = page.locator("input[type='checkbox']");
    // At least one toggle for shell-executor
    await expect(toggles.first()).toBeVisible();
  });

  test("shows Configure button for plugins needing credential setup", async ({ page }) => {
    // slack-input needs setup (has_credentials=true, credentials_configured=false)
    await expect(page.getByRole("button", { name: "Configure" }).first()).toBeVisible();
  });

  test("shows status dot with Running/Stopped label", async ({ page }) => {
    // shell-executor is enabled -> Running, slack-input is not -> Stopped
    await expect(page.getByText("Running").first()).toBeVisible();
    await expect(page.getByText("Stopped").first()).toBeVisible();
  });

  test("shows trigger type metadata on plugin cards", async ({ page }) => {
    await expect(page.getByText("Trigger Type").first()).toBeVisible();
    await expect(page.getByText("Webhook").first()).toBeVisible();
    await expect(page.getByText("On Demand").first()).toBeVisible();
  });

  test("filtering by Input category shows only input plugins", async ({ page }) => {
    await page.getByRole("button", { name: "Input" }).click();
    // slack-input + chatgpt-memory-input (both category=input)
    await expect(page.getByText("slack-input")).toBeVisible();
    await expect(page.getByText("chatgpt-memory-input")).toBeVisible();
    const cards = page.locator("[data-testid='plugin-card']");
    await expect(cards).toHaveCount(2);
  });

  test("search filters entries by name", async ({ page }) => {
    const searchInput = page.getByPlaceholder("Search plugins...");
    await searchInput.fill("shell");
    await expect(page.getByText("shell-executor")).toBeVisible();
    // slack-input should be filtered out
    await expect(page.getByText("slack-input")).not.toBeVisible();
  });
});

test.describe("Skills section", () => {
  test("shows Skills heading with divider", async ({ page }) => {
    await page.goto("/#/plugins");
    await expect(page.getByRole("heading", { name: "Skills" })).toBeVisible();
  });

  test("renders skill cards with name, description, and Always Safe badge", async ({ page }) => {
    await page.goto("/#/plugins");
    await expect(page.getByText("weekly-digest")).toBeVisible();
    await expect(page.getByText("insight-linker")).toBeVisible();
    await expect(page.getByText("Always Safe").first()).toBeVisible();
  });

  test("skill cards show Run button", async ({ page }) => {
    await page.goto("/#/plugins");
    // Skills section has Run buttons
    const skillSection = page.locator("section").filter({ has: page.getByRole("heading", { name: "Skills" }) });
    await expect(skillSection.getByText("Run").first()).toBeVisible();
  });
});

test.describe("Upload modal wiring (Phase 5b)", () => {
  test("clicking Run on an upload-needing plugin opens the upload modal", async ({ page }) => {
    await page.goto("/#/plugins");

    // chatgpt-memory-input has input_schema with upload_id => Run should
    // open the dropzone modal instead of POSTing /run/{name}.
    const card = page.locator("[data-testid='plugin-card']").filter({
      hasText: "chatgpt-memory-input",
    });
    // Run button is the icon-prefixed accent button; pick the last button
    // in the card footer.
    await card.locator("button").last().click();

    await expect(page.getByText("Import via chatgpt-memory-input")).toBeVisible();
    await expect(page.getByText(/Drop file here or click to choose/)).toBeVisible();
    await expect(page.getByText(/Accepted: \.json/)).toBeVisible();
  });

  test("plain plugin Run still calls /run directly (no modal)", async ({ page }) => {
    await page.goto("/#/plugins");

    let ranDirectly = false;
    await page.route("**/api/run/shell-executor", (route) => {
      ranDirectly = true;
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ name: "shell-executor", results: [] }),
      });
    });

    const card = page.locator("[data-testid='plugin-card']").filter({
      hasText: "shell-executor",
    });
    await card.locator("button").last().click();
    await page.waitForTimeout(500);

    expect(ranDirectly).toBe(true);
    await expect(page.getByText("Import via")).not.toBeVisible();
  });
});
