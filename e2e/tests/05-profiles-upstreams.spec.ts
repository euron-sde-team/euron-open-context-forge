import { expect, test } from "@playwright/test";

import { adminApi, asOwner, RUN } from "../helpers";
import { supportThread } from "../fixtures";

test("editing a profile changes how the budget is split", async ({ page, request }) => {
  await asOwner(page, "/profiles");
  const card = page.locator("section", { hasText: "Source passages, citations" });
  await card.getByRole("button", { name: "Edit" }).click();
  await page.locator("#w-documents").fill("0.9");
  await page.getByRole("button", { name: "Save" }).click();
  await expect(card.getByText("Edited")).toBeVisible();

  const resp = await request.post("/api/v1/playground/optimize", {
    headers: await adminApi(request),
    data: { model: "gpt-4o", messages: supportThread(), options: { max_input_tokens: 400, profile: "research" } },
  });
  const body = await resp.json();
  const docs = body.allocation.find((a: { category: string }) => a.category === "documents");
  expect(docs.weight).toBeGreaterThan(0.6);

  await card.getByRole("button", { name: "Reset" }).click();
  await page.getByRole("button", { name: "Reset profile" }).click();
  await expect(card.getByText("Built in")).toBeVisible();
});

test("an upstream added in the dashboard serves the OpenAI-compatible proxy", async ({ page, request }) => {
  const name = `e2e-${RUN}`;
  await asOwner(page, "/upstreams");
  await page.getByRole("button", { name: "Add upstream" }).click();
  await page.locator("#u-name").fill(name);
  await page.locator("#u-url").fill("http://mock-llm:4350/v1");
  await page.locator("#u-budget").fill("900");
  await page.getByRole("button", { name: "Add upstream" }).last().click();
  await expect(page.locator("tr", { hasText: name })).toBeVisible();

  const key = await request.post("/api/v1/keys", { headers: await adminApi(request), data: { name: `proxy-${RUN}` } });
  const secret = (await key.json()).key as string;
  const resp = await request.post("/v1/chat/completions", {
    headers: { authorization: `Bearer ${secret}`, "x-contextforge-upstream": name },
    data: { model: "gpt-4o", messages: supportThread() },
  });
  expect(resp.status()).toBe(200);
  expect(Number(resp.headers()["x-contextforge-optimized-tokens"])).toBeLessThanOrEqual(900);
  expect((await resp.json()).choices[0].message.content).toMatch(/^Mock answer/);

  await page.locator("tr", { hasText: name }).getByRole("button", { name: `Remove ${name}` }).click();
  await page.getByRole("button", { name: "Remove upstream" }).click();
  await expect(page.locator("tr", { hasText: name })).toBeHidden();
});
