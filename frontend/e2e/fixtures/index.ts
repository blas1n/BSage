import { test as base } from "@playwright/test";

/**
 * Mock API responses fixture (auto-used)
 * Sets up HTTP request interception for all backend endpoints.
 */

type CustomFixtures = {
  mockApiResponses: void;
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

// Matches VaultTreeEntry[] = {path, dirs, files}[]
const MOCK_VAULT_TREE_RESPONSE = [
  {
    path: "",
    dirs: ["garden", "seeds"],
    files: [],
  },
  {
    path: "garden",
    dirs: [],
    files: ["index.md", "idea-1.md"],
  },
  {
    path: "seeds",
    dirs: ["slack-input"],
    files: [],
  },
  {
    path: "seeds/slack-input",
    dirs: [],
    files: ["messages.md"],
  },
];

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

export const test = base.extend<CustomFixtures>({
  // Auto-use fixture: routes are set up for every test automatically
  mockApiResponses: [
    async ({ page }, use) => {
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
        if (route.request().method() === "GET") {
          route.fulfill({
            status: 200,
            contentType: "application/json",
            body: JSON.stringify(MOCK_PLUGINS_RESPONSE),
          });
        } else {
          route.fulfill({
            status: 200,
            contentType: "application/json",
            body: JSON.stringify({ status: "ok" }),
          });
        }
      });

      // Plugin run endpoint
      await page.route("**/api/plugins/*/run", (route) => {
        route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({ status: "started" }),
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

      // Chat endpoint
      await page.route("**/api/chat", (route) => {
        if (route.request().method() === "POST") {
          route.fulfill({
            status: 200,
            contentType: "application/json",
            body: JSON.stringify(MOCK_CHAT_RESPONSE),
          });
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

      await use();
    },
    { auto: true },
  ],
});

export { expect } from "@playwright/test";
