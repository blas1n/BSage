import { test, expect } from "./fixtures";

test.describe("Karpathy Wiki API endpoints", () => {
  test.describe("Knowledge Catalog — GET /api/knowledge/catalog", () => {
    test("returns catalog grouped by note type", async ({ page }) => {
      await page.goto("/");
      await page.waitForLoadState("networkidle");

      const data = await page.evaluate(async () => {
        const res = await fetch("/api/knowledge/catalog");
        return res.json();
      });

      expect(data.total).toBe(3);
      expect(data.categories).toHaveProperty("idea");
      expect(data.categories).toHaveProperty("insight");
      expect(data.categories.idea).toHaveLength(1);
      expect(data.categories.insight).toHaveLength(2);
    });

    test("catalog entries contain title, path, tags, captured_at", async ({ page }) => {
      await page.goto("/");
      await page.waitForLoadState("networkidle");

      const data = await page.evaluate(async () => {
        const res = await fetch("/api/knowledge/catalog");
        return res.json();
      });

      const firstIdea = data.categories.idea[0];
      expect(firstIdea).toHaveProperty("title", "AI Overview");
      expect(firstIdea).toHaveProperty("path", "ideas/ai-overview.md");
      expect(firstIdea).toHaveProperty("tags");
      expect(firstIdea.tags).toContain("ai");
      expect(firstIdea).toHaveProperty("captured_at");
    });
  });

  test.describe("Vault Lint — POST /api/vault/lint", () => {
    test("returns lint report with issues", async ({ page }) => {
      await page.goto("/");
      await page.waitForLoadState("networkidle");

      const data = await page.evaluate(async () => {
        const res = await fetch("/api/vault/lint?stale_days=90", { method: "POST" });
        return res.json();
      });

      expect(data.total_notes_scanned).toBe(10);
      expect(data.issues_count).toBe(2);
      expect(data.issues).toHaveLength(2);
      expect(data).toHaveProperty("timestamp");
    });

    test("lint issues contain check type and severity", async ({ page }) => {
      await page.goto("/");
      await page.waitForLoadState("networkidle");

      const data = await page.evaluate(async () => {
        const res = await fetch("/api/vault/lint?stale_days=90", { method: "POST" });
        return res.json();
      });

      const orphan = data.issues.find((i: { check: string }) => i.check === "orphan");
      expect(orphan).toBeDefined();
      expect(orphan.severity).toBe("warning");
      expect(orphan.path).toContain(".md");

      const stale = data.issues.find((i: { check: string }) => i.check === "stale");
      expect(stale).toBeDefined();
      expect(stale.description).toContain("days ago");
    });
  });

  test.describe("Chat with IngestCompiler promotion", () => {
    test("chat endpoint still returns response when ingest compiler is active", async ({
      page,
    }) => {
      await page.goto("/");
      await page.waitForLoadState("networkidle");

      const data = await page.evaluate(async () => {
        const res = await fetch("/api/chat", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ message: "Tell me about knowledge graphs", history: [] }),
        });
        return res.json();
      });

      expect(data).toHaveProperty("response");
      expect(data.response.length).toBeGreaterThan(0);
    });
  });
});
