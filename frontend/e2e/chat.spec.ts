import { test, expect } from "./fixtures/index";
import { ChatPage } from "./pages/ChatPage";

test.describe("Chat", () => {
  let chatPage: ChatPage;

  test.beforeEach(async ({ page }) => {
    chatPage = new ChatPage(page);
    await chatPage.goto();
  });

  test("初期ロード — input visible, send button present", async ({ page }) => {
    await expect(chatPage.heading).toBeVisible();
    await expect(chatPage.input).toBeVisible();
    await expect(chatPage.sendButton).toBeVisible();
  });

  test("メッセージ送信 → 応答表示 (mock LLM)", async ({}) => {
    await chatPage.sendMessage("Hello!");
    await chatPage.waitForAssistantMessage();

    const response = await chatPage.getLastMessage();
    expect(response).toContain("Hello");
  });

  test("Enter キー送信", async ({}) => {
    await chatPage.input.fill("Test message");
    await chatPage.input.press("Enter");

    await chatPage.waitForResponse();
    await expect(chatPage.input).toHaveValue("");
  });

  test("送信中 loading state", async ({ page }) => {
    // Mock delayed response to reliably observe disabled state
    await page.route("**/api/chat", (route) => {
      setTimeout(() => {
        route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            response: "Delayed response",
          }),
        });
      }, 2000);
    });

    await chatPage.sendMessage("Test");

    // Playwright auto-polls until the assertion passes or times out
    await expect(chatPage.input).toBeDisabled({ timeout: 3000 });

    // Eventually the response arrives and input is re-enabled
    await chatPage.waitForAssistantMessage();
    await expect(chatPage.input).toBeEnabled({ timeout: 5000 });
  });

  test("API エラー時の復旧 (500 response)", async ({ page }) => {
    // Mock error response
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
    await expect(chatPage.input).toBeEnabled({ timeout: 5000 });

    // Input should be re-enabled after error
    const isDisabled = await chatPage.isInputDisabled();
    expect(isDisabled).toBeFalsy();
  });
});
