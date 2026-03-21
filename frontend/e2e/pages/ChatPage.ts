import { Page, Locator } from "@playwright/test";

export class ChatPage {
  readonly page: Page;
  readonly heading: Locator;
  readonly input: Locator;
  readonly sendButton: Locator;
  readonly chatArea: Locator;

  constructor(page: Page) {
    this.page = page;
    this.heading = page.locator("[data-testid='chat-heading'], h2 >> text=Chat").first();
    this.input = page.getByPlaceholder(
      "Type a message... (Shift+Enter for new line)"
    );
    this.sendButton = page.getByRole("button", { name: /send/i });
    this.chatArea = page.locator("[data-testid='chat-messages'], [role='log']").first();
  }

  async goto() {
    await this.page.goto("/#/");
    await this.heading.waitFor({ timeout: 10000 });
  }

  async sendMessage(text: string) {
    await this.input.fill(text);
    await this.sendButton.waitFor({ state: "visible" });
    await this.sendButton.click();
  }

  async getLastAssistantMessage() {
    const locator = this.chatArea.locator(
      "[data-testid='assistant-message'], div.prose"
    );
    const msg = locator.last();
    await msg.waitFor({ timeout: 10000 });
    return await msg.textContent();
  }

  // Alias kept for backwards compatibility with specs
  async getLastMessage() {
    return this.getLastAssistantMessage();
  }

  async waitForAssistantMessage() {
    await this.chatArea
      .locator("[data-testid='assistant-message'], div.prose")
      .first()
      .waitFor({ timeout: 10000 });
  }

  async waitForResponse() {
    await this.page.waitForResponse(
      (response) =>
        response.url().includes("/api/chat") && response.status() === 200
    );
  }

  async isInputDisabled(): Promise<boolean> {
    return await this.input.isDisabled();
  }

  async getInputValue(): Promise<string> {
    return await this.input.inputValue();
  }
}
