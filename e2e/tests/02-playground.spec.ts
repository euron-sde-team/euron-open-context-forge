import { expect, test } from "@playwright/test";

import { asOwner, choose } from "../helpers";

test("a coding agent trace is optimized with every fact kept", async ({ page }) => {
  await asOwner(page, "/playground");
  await choose(page, "sample", /^Coding agent, 8 attempts/);
  await expect(page.locator("#budget")).toHaveValue("4000");
  await page.getByRole("button", { name: "Optimize", exact: true }).click();
  const headline = page.locator("[aria-live=polite]");
  await expect(headline.getByText(/^Fits 4,000$/)).toBeVisible();
  await expect(headline.getByText(/facts kept/)).toHaveText(/(\d+)\/\1 facts kept/);
  await expect(headline.getByText("Exact: o200k_base")).toBeVisible();
  await expect(page.getByText("removed").first()).toBeVisible();
  await page.getByRole("tab", { name: "Trace" }).click();
  for (const stage of ["Protect", "Clean", "Rank", "Compress", "Validate"]) {
    await expect(page.getByText(stage, { exact: true })).toBeVisible();
  }
  await page.getByRole("tab", { name: "Warnings" }).click();
  await expect(page.getByText(/No warnings|Escalated to aggressive/)).toBeVisible();
});

test("a noisy retrieval keeps every citation resolvable", async ({ page }) => {
  await asOwner(page, "/playground");
  await choose(page, "sample", /^RAG, 108 retrieved chunks/);
  await page.getByRole("button", { name: "Optimize", exact: true }).click();
  await expect(page.getByText("Documents 108 to 3")).toBeVisible();
  await page.getByRole("tab", { name: "Documents" }).click();
  await expect(page.getByText("kept", { exact: true }).first()).toBeVisible();
  await expect(page.getByText("merged", { exact: true }).first()).toBeVisible();
  await expect(page.getByText("no overlap with the query").first()).toBeVisible();
});

test("input that is not JSON is caught before the request", async ({ page }) => {
  await asOwner(page, "/playground");
  await page.locator("#raw").fill("{ not json");
  await page.getByRole("button", { name: "Optimize", exact: true }).click();
  await expect(page.getByText(/The input is not valid JSON/)).toBeVisible();
});
