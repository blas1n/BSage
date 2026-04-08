import { test, expect } from "./fixtures";

test.describe("Chat interface", () => {
  test("shows empty state with hub icon and Start a conversation prompt", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByText("Start a conversation", { exact: true })).toBeVisible();
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

test.describe("Search mode toggle", () => {
  test("CHAT mode is active by default", async ({ page }) => {
    await page.goto("/");
    const chatBtn = page.getByRole("button", { name: "CHAT" });
    await expect(chatBtn).toHaveAttribute("aria-pressed", "true");
    const searchBtn = page.getByRole("button", { name: "SEARCH" });
    await expect(searchBtn).toHaveAttribute("aria-pressed", "false");
  });

  test("clicking SEARCH switches to search mode and changes placeholder", async ({ page }) => {
    await page.goto("/");
    await page.getByRole("button", { name: "SEARCH" }).click();

    // Placeholder changes to search mode
    await expect(page.getByPlaceholder("Search your vault...")).toBeVisible();
    // SEARCH is now active
    const searchBtn = page.getByRole("button", { name: "SEARCH" });
    await expect(searchBtn).toHaveAttribute("aria-pressed", "true");
    const chatBtn = page.getByRole("button", { name: "CHAT" });
    await expect(chatBtn).toHaveAttribute("aria-pressed", "false");
  });

  test("clicking CHAT switches back from search mode", async ({ page }) => {
    await page.goto("/");
    // Switch to search
    await page.getByRole("button", { name: "SEARCH" }).click();
    await expect(page.getByPlaceholder("Search your vault...")).toBeVisible();

    // Switch back to chat
    await page.getByRole("button", { name: "CHAT" }).click();
    await expect(page.getByPlaceholder("Type a message or reference [[Node]]...")).toBeVisible();
  });

  test("search mode sends vault search query and shows results", async ({ page }) => {
    // Override search endpoint with results
    await page.route("**/api/vault/search**", (route) => {
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify([
          { path: "garden/idea-1.md", matches: [{ line: 3, text: "An interesting idea about AI" }] },
        ]),
      });
    });

    await page.goto("/");
    await page.getByRole("button", { name: "SEARCH" }).click();

    const textarea = page.getByPlaceholder("Search your vault...");
    await textarea.fill("AI idea");
    await page.getByRole("button", { name: "Send" }).click();

    // Should show search results in assistant message
    const assistantMsg = page.locator("[data-testid='assistant-message']");
    await expect(assistantMsg).toContainText("garden/idea-1.md");
    await expect(assistantMsg).toContainText("An interesting idea about AI");
  });
});

test.describe("Help panel", () => {
  test("clicking help button opens help panel with overlay", async ({ page }) => {
    await page.goto("/");
    await page.getByRole("button", { name: "Toggle help panel" }).click();
    // Overlay backdrop appears when panel is open
    await expect(page.locator(".bg-black\\/40")).toBeVisible();
    await expect(page.getByText("도움말")).toBeVisible();
  });

  test("help panel can be toggled closed", async ({ page }) => {
    await page.goto("/");
    const toggleBtn = page.getByRole("button", { name: "Toggle help panel" });
    await toggleBtn.click();
    await expect(page.locator(".bg-black\\/40")).toBeVisible();

    // Click the overlay backdrop to close
    await page.locator(".bg-black\\/40").click();
    await expect(page.locator(".bg-black\\/40")).not.toBeAttached();
  });

  test("help panel shows default BSage section", async ({ page }) => {
    await page.goto("/");
    await page.getByRole("button", { name: "Toggle help panel" }).click();
    await expect(page.getByText("BSage는 온톨로지 기반 지식 관리 AI 비서입니다")).toBeVisible();
  });
});

test.describe("Session management", () => {
  test("session list panel is visible", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByTestId("session-list")).toBeVisible();
    await expect(page.getByText("Sessions", { exact: true })).toBeVisible();
  });

  test("shows empty state when no sessions exist", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByText("No sessions yet")).toBeVisible();
  });

  test("sending a message creates a session in the list", async ({ page }) => {
    await page.goto("/");
    const textarea = page.getByPlaceholder("Type a message or reference [[Node]]...");
    await textarea.fill("My first question");
    await page.getByRole("button", { name: "Send" }).click();

    // Wait for assistant response
    await expect(page.locator("[data-testid='assistant-message']")).toBeVisible();

    // Session should appear in the session list with title derived from first message
    const sessionList = page.getByTestId("session-list");
    await expect(sessionList.getByText("My first question")).toBeVisible();
    // "No sessions yet" should be gone
    await expect(sessionList.getByText("No sessions yet")).not.toBeVisible();
  });

  test("new session button creates a fresh session", async ({ page }) => {
    await page.goto("/");
    // Send a message first to create a session
    const textarea = page.getByPlaceholder("Type a message or reference [[Node]]...");
    await textarea.fill("First session message");
    await page.getByRole("button", { name: "Send" }).click();
    await expect(page.locator("[data-testid='assistant-message']")).toBeVisible();

    // Click new session button in session list
    await page.getByRole("button", { name: "New session" }).click();

    // Messages should be cleared (new empty session)
    await expect(page.getByText("Start a conversation")).toBeVisible();
  });

  test("clicking a previous session loads its messages", async ({ page }) => {
    await page.goto("/");

    // Create first session
    const textarea = page.getByPlaceholder("Type a message or reference [[Node]]...");
    await textarea.fill("Question one");
    await page.getByRole("button", { name: "Send" }).click();
    await expect(page.locator("[data-testid='assistant-message']")).toBeVisible();

    // Create second session
    await page.getByRole("button", { name: "New session" }).click();
    await expect(page.getByText("Start a conversation")).toBeVisible();

    const textarea2 = page.getByPlaceholder("Type a message or reference [[Node]]...");
    await textarea2.fill("Question two");
    await page.getByRole("button", { name: "Send" }).click();
    await expect(page.locator("[data-testid='assistant-message']")).toBeVisible();

    // Click back to first session
    await page.getByText("Question one").click();

    // Should see first session's messages
    await expect(page.locator("[data-testid='user-message']")).toContainText("Question one");
  });

  test("session shows message count", async ({ page }) => {
    await page.goto("/");
    const textarea = page.getByPlaceholder("Type a message or reference [[Node]]...");
    await textarea.fill("Hello");
    await page.getByRole("button", { name: "Send" }).click();
    await expect(page.locator("[data-testid='assistant-message']")).toBeVisible();

    // Session list item should show message count
    await expect(page.getByText(/2 messages/)).toBeVisible();
  });
});
