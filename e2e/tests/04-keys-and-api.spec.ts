import { expect, test } from "@playwright/test";

import { asOwner, RUN } from "../helpers";
import { supportThread } from "../fixtures";

test("a key created in the dashboard optimizes over the API until revoked", async ({ page, request }) => {
  const name = `e2e-${RUN}`;
  await asOwner(page, "/keys");
  await page.getByRole("button", { name: "New key" }).click();
  await page.locator("#key-name").fill(name);
  await page.getByRole("button", { name: "Create key" }).click();
  const key = (await page.getByTestId("new-key").textContent())?.trim() ?? "";
  expect(key).toMatch(/^cfk_/);
  await page.getByRole("button", { name: "I have copied the key" }).click();

  const resp = await request.post("/v1/context/optimize", {
    headers: { authorization: `Bearer ${key}` },
    data: { model: "gpt-4o", messages: supportThread(), options: { max_input_tokens: 700 } },
  });
  expect(resp.status()).toBe(200);
  const body = await resp.json();
  expect(body.stats.budget_met).toBe(true);
  expect(body.stats.optimized_tokens).toBeLessThan(body.stats.original_tokens);

  await page.goto(`/runs?run=${body.run_id}`);
  await expect(page.getByRole("dialog").getByText(name)).toBeVisible();

  await page.goto("/keys");
  const row = page.locator("tr", { hasText: name });
  await row.getByRole("button", { name: "Revoke" }).click();
  await page.getByRole("button", { name: "Revoke key" }).click();
  await expect(page.locator("tr", { hasText: name })).toBeHidden();
  const after = await request.post("/v1/context/count-tokens", {
    headers: { authorization: `Bearer ${key}` },
    data: { model: "gpt-4o", text: "hello" },
  });
  expect(after.status()).toBe(401);
});
