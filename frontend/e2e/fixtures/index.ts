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
    trigger: { type: "webhook" },
    entry_type: "plugin",
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
    trigger: { type: "on_demand" },
    entry_type: "plugin",
  },
  {
    name: "chatgpt-memory-input",
    version: "1.0.0",
    category: "input",
    description: "Import ChatGPT conversation export",
    is_dangerous: false,
    has_credentials: false,
    credentials_configured: true,
    enabled: true,
    trigger: { type: "on_demand" },
    entry_type: "plugin",
    input_schema: {
      type: "object",
      properties: { upload_id: { type: "string" }, path: { type: "string" } },
    },
    mcp_exposed: true,
  },
];

const MOCK_SKILLS_RESPONSE: EntryMeta[] = [
  {
    name: "weekly-digest",
    version: "1.0.0",
    category: "process",
    description: "Generate a weekly digest from recent garden notes",
    is_dangerous: false,
    has_credentials: false,
    credentials_configured: true,
    enabled: true,
    trigger: { type: "cron", schedule: "0 9 * * MON" },
    entry_type: "skill",
  },
  {
    name: "insight-linker",
    version: "1.0.0",
    category: "process",
    description: "Link related insights across vault notes",
    is_dangerous: false,
    has_credentials: false,
    credentials_configured: true,
    enabled: false,
    trigger: { type: "on_demand" },
    entry_type: "skill",
  },
];

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

// Build a fake JWT for e2e authenticated sessions
const E2E_JWT_HEADER = btoa(JSON.stringify({ alg: "none" }));
const E2E_JWT_PAYLOAD = btoa(
  JSON.stringify({
    sub: "e2e-user",
    email: "e2e@bsvibe.dev",
    exp: 4102444800,
    app_metadata: { tenant_id: "e2e-tenant", role: "admin" },
  }),
);
const E2E_FAKE_JWT = `${E2E_JWT_HEADER}.${E2E_JWT_PAYLOAD}.fake`;

// Phase B: full SessionEnvelope shape — `@bsvibe/auth`'s useAuth requires
// a `user` field. The legacy 3-field shape was rejected and triggered a
// redirect to /login, breaking protected-page e2e.
const MOCK_SESSION_RESPONSE = {
  user: {
    id: "user-123",
    email: "test@example.com",
    name: "Test User",
  },
  tenants: [
    {
      id: "tenant-1",
      name: "Test Tenant",
      slug: "test",
      plan: "team",
      type: "company",
      role: "member",
    },
  ],
  active_tenant_id: "tenant-1",
  access_token: E2E_FAKE_JWT,
  refresh_token: "fake-refresh",
  expires_in: 3600,
};

export const test = base.extend<CustomFixtures>({
  // Auto-use fixture: routes are set up for every test automatically
  mockApiResponses: [
    async ({ page }, use) => {
      // Inject a fake JWT into localStorage so the BSage SPA's `useAuth`
      // (called with `probeRemoteSession: false`) treats the test session
      // as authenticated. The cookie-SSO route mock below is still kept
      // for tests that exercise re-probe paths.
      await page.addInitScript(
        ({ token, expiresAt }: { token: string; expiresAt: number }) => {
          localStorage.removeItem("bsage_chat_sessions");
          localStorage.removeItem("bsage_active_session");
          localStorage.setItem("bsage_access_token", token);
          localStorage.setItem("bsage_refresh_token", "fake-refresh");
          localStorage.setItem("bsage_expires_at", String(expiresAt));
        },
        { token: E2E_FAKE_JWT, expiresAt: 4102444800_000 },
      );

      // Intercept auth.bsvibe.dev/api/session → return a valid session (authenticated)
      await page.route("**/auth.bsvibe.dev/api/session", (route) => {
        route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify(MOCK_SESSION_RESPONSE),
        });
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
          body: JSON.stringify({
            nodes: [
              { id: "garden/index.md", name: "index", group: "garden" },
              { id: "garden/idea-1.md", name: "idea-1", group: "garden" },
              { id: "seeds/slack-input/messages.md", name: "messages", group: "seeds" },
            ],
            links: [
              { source: "garden/index.md", target: "garden/idea-1.md" },
            ],
            truncated: false,
          }),
        });
      });

      // Config — LLM test endpoint
      await page.route("**/api/config/test-llm", (route) => {
        route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            ok: true,
            model: "claude-opus-4-5",
            latency_ms: 42,
            reply: "pong",
          }),
        });
      });

      // Vault communities endpoint (Phase 1)
      await page.route("**/api/vault/communities**", (route) => {
        route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            communities: [
              {
                id: 0,
                label: "index (garden)",
                size: 2,
                cohesion: 1.0,
                members: ["garden/index.md", "garden/idea-1.md"],
                color: "#4edea3",
              },
            ],
            algorithm: "louvain",
            total: 1,
          }),
        });
      });

      // Vault analytics endpoint (Phase 6)
      await page.route("**/api/vault/analytics**", (route) => {
        route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            stats: {
              num_nodes: 3,
              num_edges: 1,
              num_components: 2,
              density: 0.17,
              avg_degree: 0.67,
              isolated_nodes: ["seeds/slack-input/messages.md"],
            },
            centrality: [],
            god_nodes: [],
            gaps: { isolated: [], thin: [], small_components: [] },
          }),
        });
      });

      // Knowledge catalog endpoint (Karpathy Wiki feature)
      await page.route("**/api/knowledge/catalog", (route) => {
        route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            total: 3,
            categories: {
              idea: [
                { title: "AI Overview", path: "ideas/ai-overview.md", tags: ["ai"], captured_at: "2026-04-07" },
              ],
              insight: [
                { title: "Neural Networks", path: "insights/neural-networks.md", tags: ["ml", "deep-learning"], captured_at: "2026-04-06" },
                { title: "Knowledge Graphs", path: "insights/knowledge-graphs.md", tags: ["graph"], captured_at: "2026-04-05" },
              ],
            },
          }),
        });
      });

      // Vault lint endpoint (Karpathy Wiki feature)
      await page.route("**/api/vault/lint**", (route) => {
        route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            total_notes_scanned: 10,
            issues_count: 2,
            issues: [
              { check: "orphan", severity: "warning", path: "ideas/lonely.md", description: "'Lonely' has no related links (orphan page)" },
              { check: "stale", severity: "warning", path: "facts/old-fact.md", description: "'Old Fact' captured 120 days ago (threshold: 90 days)" },
            ],
            timestamp: "2026-04-07T12:00:00+00:00",
          }),
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

      // Toggle entry endpoint
      await page.route("**/api/entries/*/toggle", (route) => {
        const url = new URL(route.request().url());
        const name = url.pathname.split("/api/entries/")[1]?.split("/toggle")[0] || "unknown";
        route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({ name, enabled: true }),
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
