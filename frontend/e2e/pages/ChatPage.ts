import { Page, Locator } from "@playwright/test";

/**
 * Page Object Model for Chat page
 * Encapsulates selectors and interactions for the chat interface
 */
export class ChatPage {
  readonly page: Page;
  readonly heading: Locator;
  readonly input: Locator;
  readonly sendButton: Locator;
  readonly messageContainer: Locator;

  constructor(page: Page) {
    this.page = page;
    this.heading = page.getByRole("heading", { name: "Chat" });
    this.input = page.getByPlaceholder(
      "Type a message... (Shift+Enter for new line)"
    );
    this.sendButton = page.locator("button.bg-green-600");
    this.messageContainer = page.locator("[data-testid='message-container']");
  }

  async goto() {
    await this.page.goto("/");
  }

  async sendMessage(text: string) {
    await this.input.fill(text);
    await this.sendButton.click();
  }

  async sendMessageWithEnter(text: string) {
    await this.input.fill(text);
    await this.input.press("Enter");
  }

  async getLastMessage() {
    const messages = await this.page
      .locator("div.prose, p.whitespace-pre-wrap")
      .last()
      .textContent();
    return messages;
  }

  async isInputDisabled(): Promise<boolean> {
    return await this.input.isDisabled();
  }

  async waitForResponse() {
    await this.page.waitForResponse(
      (response) =>
        response.url().includes("/api/chat") && response.status() === 200
    );
  }

  async waitForAssistantMessage() {
    await this.page.locator("div.prose").waitFor({ timeout: 10000 });
  }

  async getInputValue(): Promise<string> {
    return await this.input.inputValue();
  }

  async clearInput() {
    await this.input.clear();
  }
}
