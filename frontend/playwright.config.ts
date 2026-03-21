import { tmpdir } from "node:os";
import { defineConfig, devices } from "@playwright/test";

const e2eVaultDir = process.env.E2E_VAULT_DIR || `${tmpdir()}/e2e-vault-${process.pid}`;
const backendHost = process.env.BSAGE_TEST_HOST || "127.0.0.1";
const frontendHost = process.env.BSAGE_TEST_FRONTEND_HOST || "localhost";

export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  expect: { timeout: process.env.CI ? 30_000 : 10_000 },
  fullyParallel: true,
  retries: process.env.CI ? 2 : 1,
  workers: process.env.CI ? 1 : undefined,
  reporter: process.env.CI ? "github" : "html",

  use: {
    baseURL: `http://${frontendHost}:5173`,
    trace: "on-first-retry",
    screenshot: "only-on-failure",
  },

  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],

  webServer: [
    {
      command: `cd .. && BSAGE_VAULT_DIR=${e2eVaultDir} uv run bsage run`,
      url: `http://${backendHost}:8000/api/health`,
      reuseExistingServer: !process.env.CI,
      timeout: 60_000,
    },
    {
      command: "npm run dev",
      url: `http://${frontendHost}:5173`,
      reuseExistingServer: !process.env.CI,
      timeout: 60_000,
    },
  ],
});
