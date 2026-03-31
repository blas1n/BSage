import { test, expect } from "./fixtures";

test.describe("Chat interface", () => {
  test("shows empty state with hub icon and Start a conversation prompt", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByText("Start a conversation")).toBeVisible();
    await expect(page.getByText("Ask anything about your 2nd Brain")).toBeVisible();
  });

  test("shows Chat/Graph tab switcher at the top", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByText("Chat").first()).toBeVisible();
    await expect(page.getByRole("link", { name: "Graph" })).toBeVisible();
  });

  test("shows input bar with textarea placeholder", async ({ page }) => {
    await page.goto("/");
    const textarea = page.getByPlaceholder("Type a message or reference [[Node]]...");
    await expect(textarea).toBeVisible();
  });

  test("shows mode toggle buttons — CHAT and SEARCH", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByRole("button", { name: "CHAT" })).toBeVisible();
    await expect(page.getByRole("button", { name: "SEARCH" })).toBeVisible();
  });

  test("shows send button with aria-label", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByRole("button", { name: "Send" })).toBeVisible();
  });

  test("send button is disabled when input is empty", async ({ page }) => {
    await page.goto("/");
    const sendBtn = page.getByRole("button", { name: "Send" });
    await expect(sendBtn).toBeDisabled();
  });

  test("send button enables when text is entered", async ({ page }) => {
    await page.goto("/");
    const textarea = page.getByPlaceholder("Type a message or reference [[Node]]...");
    await textarea.fill("Hello BSage");
    const sendBtn = page.getByRole("button", { name: "Send" });
    await expect(sendBtn).toBeEnabled();
  });

  test("sending a message renders user bubble and assistant response", async ({ page }) => {
    await page.goto("/");
    const textarea = page.getByPlaceholder("Type a message or reference [[Node]]...");
    await textarea.fill("Hello BSage");
    await page.getByRole("button", { name: "Send" }).click();

    // User message bubble
    const userMsg = page.locator("[data-testid='user-message']");
    await expect(userMsg).toContainText("Hello BSage");

    // Assistant response bubble
    const assistantMsg = page.locator("[data-testid='assistant-message']");
    await expect(assistantMsg).toContainText("Hello! I am BSage");
  });

  test("assistant message with wikilinks shows source citations", async ({ page }) => {
    // Override the chat endpoint to return a response with wikilinks
    await page.route("**/api/chat", (route) => {
      if (route.request().method() === "POST") {
        route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            response: "Based on [[idea-1]] and [[Work]], here is my analysis.",
          }),
        });
      }
    });

    await page.goto("/");
    const textarea = page.getByPlaceholder("Type a message or reference [[Node]]...");
    await textarea.fill("Summarize my ideas");
    await page.getByRole("button", { name: "Send" }).click();

    // Source citations render in the SourceCitation component (font-mono text)
    await expect(page.locator(".font-mono").getByText("idea-1")).toBeVisible();
    await expect(page.locator(".font-mono").getByText("Work")).toBeVisible();
  });

  test("Clear button appears after sending a message", async ({ page }) => {
    await page.goto("/");
    // No clear button initially
    await expect(page.getByRole("button", { name: /Clear/ })).not.toBeVisible();

    const textarea = page.getByPlaceholder("Type a message or reference [[Node]]...");
    await textarea.fill("Test");
    await page.getByRole("button", { name: "Send" }).click();
    await expect(page.locator("[data-testid='user-message']")).toBeVisible();

    // Clear button should now appear
    await expect(page.getByRole("button", { name: /Clear/ })).toBeVisible();
  });

  test("shows encrypted connection footer text", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByText(/end-to-end encrypted/i)).toBeVisible();
  });

  test("mini graph sidebar shows Knowledge Graph label and Expand link", async ({ page }) => {
    await page.goto("/");
    // The MiniGraph sidebar has a "Knowledge Graph" label and Expand link
    const miniGraphSidebar = page.locator(".w-64.shrink-0");
    await expect(miniGraphSidebar.getByText("Knowledge Graph")).toBeVisible();
    await expect(miniGraphSidebar.getByText("Expand")).toBeVisible();
  });
});
