import { expect, test } from "@playwright/test";

import { asOwner } from "../helpers";

test("the overview shows savings and fact retention from real runs", async ({ page }) => {
  await asOwner(page, "/");
  await expect(page.getByText("Tokens saved")).toBeVisible();
  await expect(page.getByText("Fact retention")).toBeVisible();
  await expect(page.getByText("Tokens received vs sent on")).toBeVisible();
  await expect(page.getByText("By workload")).toBeVisible();
  await page.getByRole("radio", { name: "7d" }).click();
  await expect(page.getByText("vs previous 7 days").first()).toBeVisible();
});

test("a run opens with its trace and allocation", async ({ page }) => {
  await asOwner(page, "/runs");
  await page.locator("table tbody tr").first().click();
  const drawer = page.getByRole("dialog");
  await expect(drawer.getByText(/^Run \d+$/)).toBeVisible();
  await expect(drawer.getByText("Pipeline trace")).toBeVisible();
  await expect(drawer.getByText("Budget allocation")).toBeVisible();
  await expect(page).toHaveURL(/run=\d+/);
});

test("filters narrow the runs list", async ({ page }) => {
  await asOwner(page, "/runs");
  await page.getByLabel("Only runs that missed the budget").click();
  await expect(page.getByRole("button", { name: "Clear filters" })).toBeVisible();
  await expect(page.locator("table tbody tr").first()).toBeVisible();
});

test("background jobs from the demo succeeded", async ({ page }) => {
  await asOwner(page, "/jobs");
  await expect(page.getByText("Succeeded").first()).toBeVisible();
  await expect(page.getByRole("link", { name: /^Run \d+$/ }).first()).toBeVisible();
});
