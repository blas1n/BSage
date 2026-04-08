import { test, expect } from "./fixtures";
import { test as base } from "@playwright/test";

/**
 * Auth tests — login page (LandingPage) and auth redirect behavior.
 * Uses the base test (no auto-injected JWT) to test unauthenticated state.
 */

base.describe("LandingPage (unauthenticated)", () => {
  base.beforeEach(async ({ page }) => {
    // Ensure no session and skip SSO redirect
    await page.addInitScript(() => {
      localStorage.removeItem("bsvibe_user");
      (window as unknown as Record<string, unknown>).__E2E_SKIP_SSO__ = true;
    });

    // Mock API routes so no real backend is needed
    await page.route("**/api/health", (route) =>
      route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ status: "ok" }) }),
    );
    await page.route("**/api/config", (route) =>
      route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ safe_mode: false, has_llm_api_key: true, llm_model: "test", llm_api_base: null, disabled_entries: [], index_available: false }) }),
    );

    await page.goto("/");
  });

  base("shows BSage branding and tagline", async ({ page }) => {
    await expect(page.getByRole("heading", { name: "BSage" })).toBeVisible();
    await expect(page.getByText("Your AI-powered second brain.")).toBeVisible();
  });

  base("shows feature highlights — Knowledge Graph, Smart Search, Plugin Ecosystem", async ({ page }) => {
    await expect(page.getByText("Knowledge Graph")).toBeVisible();
    await expect(page.getByText("Smart Search")).toBeVisible();
    await expect(page.getByText("Plugin Ecosystem")).toBeVisible();
  });

  base("shows Sign in with BSVibe button", async ({ page }) => {
    const signInBtn = page.getByRole("button", { name: "Sign in with BSVibe" });
    await expect(signInBtn).toBeVisible();
  });

  base("shows Powered by BSVibe footer", async ({ page }) => {
    await expect(page.getByText("Powered by")).toBeVisible();
    await expect(page.getByText("BSVibe").last()).toBeVisible();
  });
});

test.describe("Auth redirect (authenticated)", () => {
  test("authenticated user sees main layout, not landing page", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByRole("button", { name: "Sign in with BSVibe" })).not.toBeVisible();
    await expect(page.getByText("Current Chat")).toBeVisible();
  });
});
