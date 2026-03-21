import { test, expect } from "./fixtures/index";
import { ChatPage } from "./pages/ChatPage";

test.describe("Chat", () => {
  let chatPage: ChatPage;

  test.beforeEach(async ({ page }) => {
    chatPage = new ChatPage(page);
    await chatPage.goto();
  });

  test("initial load — input visible, send button present", async ({ page }) => {
    await expect(chatPage.heading).toBeVisible();
    await expect(chatPage.input).toBeVisible();
    await expect(chatPage.sendButton).toBeVisible();
  });

  test("send message — displays response (mock LLM)", async ({}) => {
    await chatPage.sendMessage("Hello!");
    await chatPage.waitForAssistantMessage();

    const response = await chatPage.getLastMessage();
    expect(response).toContain("BSage");
  });

  test("send via Enter key", async ({}) => {
    await chatPage.input.fill("Test message");

    await Promise.all([
      chatPage.waitForResponse(),
      chatPage.input.press("Enter"),
    ]);

    await expect(chatPage.input).toHaveValue("", { timeout: 10000 });
  });

  test("loading state while sending", async ({ page }) => {
    // Mock delayed response to reliably observe disabled state
    await page.unroute("**/api/chat");
    await page.route("**/api/chat", async (route) => {
      // Short delay to simulate slow response so loading state is observable
      await page.waitForTimeout(500);
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          response: "Delayed response",
        }),
      });
    });

    await chatPage.sendMessage("Test");

    // Playwright auto-polls until the assertion passes or times out
    await expect(chatPage.input).toBeDisabled({ timeout: 3000 });

    // Eventually the response arrives and input is re-enabled
    await chatPage.waitForAssistantMessage();
    await expect(chatPage.input).toBeEnabled({ timeout: 10000 });
  });

  test("recovery from API error (500 response)", async ({ page }) => {
    // Mock error response — unroute first to avoid handler collision
    await page.unroute("**/api/chat");
    await page.route("**/api/chat", (route) => {
      route.fulfill({
        status: 500,
        contentType: "application/json",
        body: JSON.stringify({ error: "Internal server error" }),
      });
    });

    await chatPage.sendMessage("Error test");

    // Wait for input to be re-enabled after error handling completes
    await chatPage.input.waitFor({ state: "visible" });
    await expect(chatPage.input).toBeEnabled({ timeout: 10000 });

    // Input should be re-enabled after error
    const isDisabled = await chatPage.isInputDisabled();
    expect(isDisabled).toBeFalsy();
  });
});
