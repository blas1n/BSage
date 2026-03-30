import { defineConfig, devices } from "@playwright/test";

const frontendHost = process.env.BSAGE_TEST_FRONTEND_HOST || "localhost";

export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  expect: { timeout: process.env.CI ? 30_000 : 10_000 },
  fullyParallel: true,
  retries: process.env.CI ? 2 : 1,
  workers: process.env.CI ? 1 : undefined,
  reporter: process.env.CI ? "github" : "line",

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

  webServer: {
    command: "npm run dev",
    url: `http://${frontendHost}:5173`,
    reuseExistingServer: !process.env.CI,
    timeout: 60_000,
  },
});
