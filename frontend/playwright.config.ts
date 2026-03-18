import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  expect: { timeout: 10_000 },
  fullyParallel: true,
  retries: process.env.CI ? 2 : 1,
  workers: process.env.CI ? 1 : undefined,
  reporter: process.env.CI ? "github" : "html",

  use: {
    baseURL: "http://localhost:5173",
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
      command:
        "cd .. && BSAGE_VAULT_DIR=/tmp/e2e-vault uv run bsage run",
      url: "http://127.0.0.1:8000/api/health",
      reuseExistingServer: !process.env.CI,
      timeout: 60_000,
    },
    {
      command: "npm run dev",
      url: "http://localhost:5173",
      reuseExistingServer: !process.env.CI,
      timeout: 60_000,
    },
  ],
});
