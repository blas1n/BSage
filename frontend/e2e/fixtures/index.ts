import { test as base, Page } from "@playwright/test";

/**
 * Mock API responses fixture
 * Sets up HTTP request interception for all backend endpoints.
 * LLM API calls are mocked to return deterministic responses.
 */

export type MockContext = {
  mockApiResponses: () => Promise<void>;
};

const MOCK_HEALTH_RESPONSE = {
  status: "ok",
};

const MOCK_CONFIG_RESPONSE = {
  safe_mode: false,
  has_llm_api_key: true,
  llm_model: "claude-opus-4-5",
  vault_path: "/tmp/vault",
};

const MOCK_PLUGINS_RESPONSE = [
  {
    name: "slack-input",
    version: "1.0.0",
    category: "input",
    description: "Collect Slack messages and store as seeds",
    is_dangerous: true,
    trigger: { type: "cron", schedule: "*/5 * * * *" },
    needs_setup: true,
  },
  {
    name: "shell-executor",
    version: "1.0.0",
    category: "process",
    description: "Execute shell commands safely",
    is_dangerous: true,
    trigger: null,
    needs_setup: false,
  },
];

const MOCK_SKILLS_RESPONSE: unknown[] = [];

const MOCK_CHAT_RESPONSE = {
  response: "Hello! I am BSage, your AI assistant. How can I help you today?",
};

const MOCK_VAULT_TREE_RESPONSE = {
  name: "vault",
  type: "directory",
  children: [
    {
      name: "garden",
      type: "directory",
      children: [
        { name: "index.md", type: "file" },
        { name: "idea-1.md", type: "file" },
      ],
    },
    {
      name: "seeds",
      type: "directory",
      children: [
        {
          name: "slack-input",
          type: "directory",
          children: [{ name: "messages.md", type: "file" }],
        },
      ],
    },
  ],
};

const MOCK_VAULT_FILE_RESPONSE = {
  path: "garden/index.md",
  name: "index.md",
  type: "note",
  content: `---
type: index
status: active
---

# BSage Vault

Welcome to your personal AI agent's vault.

## Recent Ideas
- [[idea-1]]
- [[idea-2]]

## Topics
- [[Work]]
- [[Learning]]
`,
  frontmatter: {
    type: "index",
    status: "active",
  },
};

export const test = base.extend<MockContext>({
  mockApiResponses: async ({ page }, use) => {
    /**
     * Set up HTTP request interception.
     * Mock responses are returned before they reach the real backend.
     */

    // Health check
    await page.route("**/api/health", (route) => {
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(MOCK_HEALTH_RESPONSE),
      });
    });

    // Config endpoints
    await page.route("**/api/config", (route) => {
      if (route.request().method() === "GET") {
        route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify(MOCK_CONFIG_RESPONSE),
        });
      } else if (route.request().method() === "PATCH") {
        // Parse request body
        const postData = route.request().postData();
        if (postData) {
          const body = JSON.parse(postData);
          const updatedConfig = { ...MOCK_CONFIG_RESPONSE, ...body };
          route.fulfill({
            status: 200,
            contentType: "application/json",
            body: JSON.stringify(updatedConfig),
          });
        }
      }
    });

    // Plugins endpoint
    await page.route("**/api/plugins", (route) => {
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(MOCK_PLUGINS_RESPONSE),
      });
    });

    // Skills endpoint
    await page.route("**/api/skills", (route) => {
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(MOCK_SKILLS_RESPONSE),
      });
    });

    // Chat endpoint (POST)
    await page.route("**/api/chat", (route) => {
      if (route.request().method() === "POST") {
        // Simulate response delay
        setTimeout(() => {
          route.fulfill({
            status: 200,
            contentType: "application/json",
            body: JSON.stringify(MOCK_CHAT_RESPONSE),
          });
        }, 100);
      }
    });

    // Vault tree endpoint
    await page.route("**/api/vault/tree", (route) => {
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(MOCK_VAULT_TREE_RESPONSE),
      });
    });

    // Vault file endpoints
    await page.route("**/api/vault/file/**", (route) => {
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(MOCK_VAULT_FILE_RESPONSE),
      });
    });

    // WebSocket endpoint (not fully mocked, just allow connection)
    // Playwright doesn't intercept WebSockets with page.route(), so we leave this as-is

    await use(async () => {
      // This is the actual function body - just a no-op
      // The routes are already set up above
    });
  },
});

export { expect } from "@playwright/test";
