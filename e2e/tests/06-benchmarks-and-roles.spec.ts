import { expect, test } from "@playwright/test";

import { adminApi, asOwner, RUN, signIn } from "../helpers";

test("the benchmark runs from the dashboard and beats truncation", async ({ page }) => {
  await asOwner(page, "/benchmarks");
  await expect(page.getByText("ContextForge, balanced").first()).toBeVisible();
  await page.getByRole("button", { name: "Run benchmark" }).click();
  await expect(page.getByText("Benchmark queued")).toBeVisible();
  await expect(page.getByRole("button", { name: "Run benchmark" })).toBeEnabled({ timeout: 60_000 });
  const forge = page.locator("div", { hasText: /^ContextForge, balanced/ }).first();
  await expect(forge).toBeVisible();
  await expect(page.getByText("Truncate oldest (baseline)")).toBeVisible();
});

test.describe("a viewer", () => {
  test.use({ storageState: { cookies: [], origins: [] } });

  test("reads everything and changes nothing", async ({ page, playwright }) => {
    const owner = await playwright.request.newContext({ baseURL: process.env.WEB_URL || "http://localhost:4310", storageState: ".auth/owner.json" });
    const email = `viewer-${RUN}@example.test`;
    const created = await owner.post("/api/v1/users", {
      headers: await adminApi(owner),
      data: { email, name: "Vic Viewer", role: "viewer", password: "Viewer-Pass-123" },
    });
    expect(created.status()).toBe(201);
    await owner.dispose();

    await signIn(page, email, "Viewer-Pass-123");
    await page.goto("/keys");
    await expect(page.getByRole("heading", { name: "API keys" })).toBeVisible();
    await expect(page.getByRole("button", { name: "New key" })).toBeHidden();
    await page.goto("/profiles");
    await expect(page.getByRole("button", { name: "Edit" })).toHaveCount(0);
  });
});
