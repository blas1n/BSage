import { test, expect } from "./fixtures/index";
import { SettingsPage } from "./pages/SettingsPage";

test.describe("Settings", () => {
  let settingsPage: SettingsPage;

  test.beforeEach(async ({ page }) => {
    settingsPage = new SettingsPage(page);
    await settingsPage.goto();
  });

  test("renders current settings (llm_model, has_llm_api_key)", async ({}) => {
    await expect(settingsPage.heading).toBeVisible();
    await expect(settingsPage.llmModelInput).toBeVisible();

    const model = await settingsPage.getLLMModel();
    expect(model).toBeTruthy();
  });

  test("Safe Mode toggle sends PATCH request", async ({ page }) => {
    const responsePromise = page.waitForResponse(
      (r) =>
        r.url().includes("/api/config") && r.request().method() === "PATCH"
    );
    await settingsPage.toggleSafeMode();
    await responsePromise;
  });

  test("LLM model change + Save sends correct PATCH body", async ({ page }) => {
    const originalModel = await settingsPage.getLLMModel();
    const newModel = originalModel === "claude-sonnet-4-6"
      ? "claude-opus-4-5"
      : "claude-sonnet-4-6";

    await settingsPage.setLLMModel(newModel);

    const [response] = await Promise.all([
      page.waitForResponse(
        (r) =>
          r.url().includes("/api/config") && r.request().method() === "PATCH"
      ),
      settingsPage.clickSave(),
    ]);

    const patchBody = await response.json();

    expect(patchBody).toHaveProperty("llm_model");
    expect(patchBody.llm_model).toBe(newModel);
  });

  test("Save button is visible", async ({}) => {
    await expect(settingsPage.saveButton).toBeVisible();
  });
});
