import { test as base } from "@playwright/test";
import type { EntryMeta } from "../../src/api/types";

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
  llm_api_base: null,
  disabled_entries: [],
  index_available: false,
};

const MOCK_PLUGINS_RESPONSE: EntryMeta[] = [
  {
    name: "slack-input",
    version: "1.0.0",
    category: "input",
    description: "Collect Slack messages and store as seeds",
    is_dangerous: true,
    has_credentials: true,
    credentials_configured: false,
    enabled: false,
  },
  {
    name: "shell-executor",
    version: "1.0.0",
    category: "process",
    description: "Execute shell commands safely",
    is_dangerous: true,
    has_credentials: false,
    credentials_configured: true,
    enabled: true,
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
};

export const test = base.extend<CustomFixtures>({
  // Auto-use fixture: routes are set up for every test automatically
  mockApiResponses: [
    async ({ page }, use) => {
      // Inject a fake auth token so the app skips the login landing page
      await page.addInitScript(() => {
        localStorage.setItem("bsage_access_token", "e2e-test-token");
      });

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
          try {
            const body = route.request().postDataJSON();
            const updatedConfig = { ...MOCK_CONFIG_RESPONSE, ...body };
            route.fulfill({
              status: 200,
              contentType: "application/json",
              body: JSON.stringify(updatedConfig),
            });
          } catch {
            route.fulfill({ status: 400, body: "Invalid JSON" });
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
      await page.route("**/api/run/**", (route) => {
        const url = new URL(route.request().url());
        const name = url.pathname.split("/api/run/")[1] || "unknown";
        route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({ name, results: [] }),
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

      // Vault file endpoints (query param: ?path=...)
      await page.route("**/api/vault/file**", (route) => {
        route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify(MOCK_VAULT_FILE_RESPONSE),
        });
      });

      // Vault backlinks endpoint
      await page.route("**/api/vault/backlinks**", (route) => {
        route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify([]),
        });
      });

      // Vault tags endpoint
      await page.route("**/api/vault/tags", (route) => {
        route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({ tags: {}, truncated: false }),
        });
      });

      // Vault graph endpoint
      await page.route("**/api/vault/graph", (route) => {
        route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({ nodes: [], links: [], truncated: false }),
        });
      });

      // Vault search endpoint
      await page.route("**/api/vault/search**", (route) => {
        route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify([]),
        });
      });

      // Credential fields endpoint
      await page.route("**/api/entries/*/credentials/fields", (route) => {
        route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            name: "unknown",
            fields: [],
          }),
        });
      });

      await use();

      // Clean up all routes after each test to ensure isolation
      await page.unrouteAll({ behavior: "ignoreErrors" });
    },
    { auto: true },
  ],
});

export { expect } from "@playwright/test";
