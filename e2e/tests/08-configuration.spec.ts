import { expect, test } from "@playwright/test";

import { adminApi, asOwner, RUN } from "../helpers";

test("a custom profile is created, used and deleted", async ({ page, request }) => {
  const name = `incident-${RUN}`;
  await asOwner(page, "/profiles");
  await page.getByRole("button", { name: "New profile" }).click();
  await page.locator("#p-name").fill(name);
  await page.locator("#p-desc").fill("Incident reviews: keep tool output and errors");
  await page.getByRole("button", { name: "Create profile" }).click();
  const card = page.locator("section.surface", { hasText: name });
  await expect(card).toBeVisible();

  const resp = await request.post("/api/v1/playground/optimize", {
    headers: await adminApi(request),
    data: { model: "gpt-4o", messages: [{ role: "user", content: "hello" }], options: { profile: name } },
  });
  expect(resp.status()).toBe(200);
  expect((await resp.json()).profile).toBe(name);

  await card.getByRole("button", { name: `Delete ${name}` }).click();
  await page.getByRole("button", { name: "Delete profile" }).click();
  await expect(page.locator("section.surface", { hasText: name })).toBeHidden();
});

test("a key is edited in place: name, limit and expiry", async ({ page }) => {
  const name = `edit-${RUN}`;
  await asOwner(page, "/keys");
  await page.getByRole("button", { name: "New key" }).click();
  await page.locator("#key-name").fill(name);
  await page.getByRole("button", { name: "Create key" }).click();
  await page.getByRole("button", { name: "I have copied the key" }).click();

  await page.locator("tr", { hasText: name }).getByRole("button", { name: `Edit ${name}` }).click();
  await page.locator("#key-name").fill(`${name}-renamed`);
  await page.locator("#key-rpm").fill("120");
  await page.locator("#key-expires").fill("2099-12-31");
  await page.getByRole("button", { name: "Save changes" }).click();
  await expect(page.getByText(`Key "${name}-renamed" updated.`)).toBeVisible();
  const row = page.locator("tr", { hasText: `${name}-renamed` });
  await expect(row).toBeVisible();
  await row.getByRole("button", { name: `Revoke ${name}-renamed` }).click();
  await page.getByRole("button", { name: "Revoke key" }).click();
});

test("an upstream is edited, and a host change asks for the key again", async ({ page, request }) => {
  const name = `edit-up-${RUN}`;
  const created = await request.post("/api/v1/upstreams", {
    headers: await adminApi(request),
    data: { name, kind: "openai", base_url: "http://mock-llm:4350/v1", api_key: "sk-test-upstream-0000" },
  });
  expect(created.status()).toBe(201);

  await asOwner(page, "/upstreams");
  const row = page.locator("tr", { hasText: name });
  await row.getByRole("button", { name: `Edit ${name}` }).click();
  await page.locator("#u-budget").fill("1500");
  await page.locator("#u-url").fill("http://other-host.example.test/v1");
  await page.getByRole("button", { name: "Save" }).click();
  await expect(page.getByText(/enter the API key for the new host/)).toBeVisible();
  await page.locator("#u-url").fill("http://mock-llm:4350/v1");
  await page.getByRole("button", { name: "Save" }).click();
  await expect(page.getByText("Upstream saved.")).toBeVisible();
  await expect(row.getByText("1,500")).toBeVisible();

  await row.getByRole("button", { name: `Remove ${name}` }).click();
  await page.getByRole("button", { name: "Remove upstream" }).click();
  await expect(page.locator("tr", { hasText: name })).toBeHidden();
});

test("integrations show copy-ready snippets for this install", async ({ page }) => {
  await asOwner(page, "/integrations");
  const origin = new URL(page.url()).origin;
  await expect(page.getByText(`${origin}/v1`).first()).toBeVisible();
  await expect(page.getByText(/TokenShield/).first()).toBeVisible();
  await expect(page.getByText(/SmartRouter/).first()).toBeVisible();
});

test("a finished benchmark's report downloads as Markdown", async ({ page }) => {
  await asOwner(page, "/benchmarks");
  await expect(page.getByText("ContextForge, balanced").first()).toBeVisible();
  const [download] = await Promise.all([
    page.waitForEvent("download"),
    page.getByRole("button", { name: "Download report" }).first().click(),
  ]);
  expect(download.suggestedFilename()).toMatch(/^contextforge-benchmark-.*\.md$/);
  const path = await download.path();
  const { readFile } = await import("node:fs/promises");
  expect(await readFile(path!, "utf8")).toMatch(/Truncate oldest|truncate-oldest/);
});
