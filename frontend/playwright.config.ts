import { defineConfig, devices } from "@playwright/test";

const frontendHost = process.env.BSAGE_TEST_FRONTEND_HOST || "localhost";
const frontendPort = Number(process.env.BSAGE_TEST_FRONTEND_PORT || 5173);

export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  expect: { timeout: process.env.CI ? 30_000 : 10_000 },
  fullyParallel: true,
  retries: process.env.CI ? 2 : 1,
  workers: process.env.CI ? 1 : undefined,
  reporter: process.env.CI ? "github" : "line",

  use: {
    baseURL: `http://${frontendHost}:${frontendPort}`,
    trace: "on-first-retry",
    screenshot: "only-on-failure",
  },

  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
    // Phase B Batch 2: mobile viewport coverage. Pixel 5 (Mobile Chrome) +
    // iPhone 13 (Mobile Chromium engine — Playwright bundled WebKit
    // page-launch hangs on macOS 26 with DEPENDENCIES_VALIDATED stuck;
    // the viewport / userAgent / isMobile flag still match iPhone 13).
    // See Shared Library Roadmap §B3.
    {
      name: "pixel-5",
      use: { ...devices["Pixel 5"] },
    },
    {
      name: "iphone-13",
      use: {
        browserName: "chromium",
        ...devices["iPhone 13"],
        defaultBrowserType: "chromium",
      },
    },
  ],

  webServer: {
    command: `next dev -p ${frontendPort}`,
    url: `http://${frontendHost}:${frontendPort}`,
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
});
