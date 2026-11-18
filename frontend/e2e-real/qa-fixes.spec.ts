/**
 * QA-02, QA-03, QA-05, QA-06, QA-07 and QA-13 from
 * docs/QA_BROWSER_TEST_2026-11-18.md, in a real browser on the real stack.
 *
 * Needs what flows.spec.ts needs (seeded demo tenant, an ACTIVE FDA IID release
 * from the public July 2026 file with approved route/dosage-form mappings; the
 * 67 IID rows whose dosage form is plain "DROPS" stay unmapped), plus
 * REAL_STACK_PASSWORD and REAL_STACK_MFA_FILE. Runs after flows.spec.ts.
 * Every step is recorded in `$REAL_STACK_OUT/qa-fixes.jsonl` with a screenshot.
 */
import { expect, test, type Page } from "@playwright/test";
import { join } from "node:path";
import { OUT, TENANT, api, record, signIn } from "./helpers";

test.describe.configure({ mode: "serial" });
test.setTimeout(3 * 60 * 1000);

const RUN = Date.now().toString(36).toUpperCase();
const state: { versionUrl?: string; versionId?: string } = {};

async function step(page: Page, name: string, body: () => Promise<void>): Promise<void> {
  const shot = join(OUT, "screenshots", `qa__${name.replace(/[^a-z0-9]+/gi, "_")}.png`);
  try {
    await body();
    await page.screenshot({ path: shot, fullPage: true });
    record("qa-fixes.jsonl", { step: name, ok: true, screenshot: shot });
  } catch (e) {
    await page.screenshot({ path: shot, fullPage: true }).catch(() => undefined);
    record("qa-fixes.jsonl", { step: name, ok: false, error: String(e).slice(0, 500), screenshot: shot });
    throw e;
  }
}

test("Doer: formulation inputs are checked (QA-02, QA-03)", async ({ page }) => {
  await signIn(page, "doer");
  await step(page, "product with a solid dosage form", async () => {
    await page.goto(`/formulations/new?tenant=${TENANT}`);
    await page.getByLabel("Product code").fill(`QA-${RUN}`);
    await page.getByLabel("Proposed product name").fill("QA synthetic tablet");
    await page.getByLabel("Active ingredient").fill("SYNTHETIC ACTIVE");
    await page.getByLabel("Intended dosage form (optional)").fill("TABLET");
    await page.getByRole("button", { name: "Create" }).click();
    await expect(page).toHaveURL(/\/formulations\/[0-9a-f-]{36}\?tenant=/);
  });
  await step(page, "negative maximum dosage units per day is refused", async () => {
    await page.getByRole("button", { name: "Create formulation version" }).click();
    await page.getByLabel("Total dosage-unit weight").fill("250");
    await page.getByLabel("Unit", { exact: true }).fill("mg");
    await page.getByLabel("Maximum dosage units/day").fill("-5");
    await page.getByRole("button", { name: "Create version" }).click();
    await expect(page.getByText(/must be greater than zero/)).toBeVisible();
    await page.getByLabel("Maximum dosage units/day").fill("4");
    await page.getByRole("button", { name: "Create version" }).click();
    await expect(page).toHaveURL(/\/versions\/[0-9a-f-]{36}/);
    state.versionUrl = page.url();
    state.versionId = page.url().match(/versions\/([0-9a-f-]{36})/)![1];
  });
  await step(page, "the unit is chosen from a list", async () => {
    await page.getByRole("button", { name: "Add component" }).click();
    const options = await page.getByTestId("component-unit").locator("option").allTextContents();
    expect(options.map((o) => o.split(" ")[0])).toEqual(["mg", "g", "kg", "µg", "mL", "L", "%"]);
  });
  await step(page, "the API refuses an unknown unit and an over-100 percentage in any spelling", async () => {
    const url = `formulations/versions/${state.versionId}/components/`;
    const base = { component_type: "inactive", ingredient_name: "QA STARCH", quantity_per_dosage_unit: "150" };
    expect((await api(page, "POST", url, { ...base, quantity_unit: "furlongs" })).status).toBe(400);
    for (const unit of ["% w/w", "%w/v", "percent"]) {
      const res = await api(page, "POST", url, { ...base, quantity_unit: unit });
      expect(res.status).toBe(400);
      expect(JSON.stringify(res.json)).toContain("A percentage cannot be more than 100.");
    }
  });
  await step(page, "a per-volume meaning is refused on a tablet", async () => {
    await page.getByLabel("Ingredient name").fill("QA SUCROSE");
    await page.getByLabel("Quantity per dosage unit").fill("100");
    await page.getByLabel(/What the quantity means/).selectOption({ label: "mg/5mL" });
    await page.getByRole("button", { name: "Add", exact: true }).click();
    await expect(page.getByText(/is an amount per volume, but this product's dosage form is TABLET/)).toBeVisible();
  });
  await step(page, "a valid mg component is added", async () => {
    await page.getByLabel(/What the quantity means/).selectOption({ index: 0 });
    await page.getByTestId("component-unit").selectOption("mg");
    await page.getByLabel("Quantity per dosage unit").fill("2.5");
    await page.getByRole("button", { name: "Add", exact: true }).click();
    await expect(page.getByRole("cell", { name: "QA SUCROSE" })).toBeVisible();
  });
});

test("Doer: the IID preview never keeps a stale result (QA-05)", async ({ page }) => {
  await signIn(page, "doer");
  await step(page, "a valid preview shows a result", async () => {
    await page.goto(`/iid-assessments/preview?tenant=${TENANT}`);
    await expect(page.getByLabel(/Active FDA release ID/)).not.toHaveValue("");
    await page.getByLabel(/Ingredient name/).fill("ACACIA");
    await page.getByLabel(/^Route code/).fill("ORAL");
    await page.getByLabel(/Dosage form code/).fill("TABLET");
    await page.getByLabel("Proposed quantity per unit").fill("77");
    await page.getByLabel("Total dosage-unit weight").fill("250");
    await page.getByRole("button", { name: "Run preview" }).click();
    await expect(page.getByRole("region", { name: "Assessment result" })).toContainText("above the IID value");
  });
  await step(page, "changing an input clears the result at once", async () => {
    await page.getByLabel("Proposed quantity per unit").fill("0");
    await expect(page.getByRole("region", { name: "Assessment result" })).toHaveCount(0);
  });
  await step(page, "an invalid run shows the error and no result", async () => {
    await page.getByRole("button", { name: "Run preview" }).click();
    await expect(page.getByText("The amount must be greater than zero.")).toBeVisible();
    await expect(page.getByRole("region", { name: "Assessment result" })).toHaveCount(0);
    await expect(page.getByText(/Proposed 77/)).toHaveCount(0);
  });
});

test("Doer: honest reasons and release health in the preview (QA-06, QA-07)", async ({ page }) => {
  await signIn(page, "doer");
  const run = async (ingredient: string, route: string, form: string) => {
    await page.goto(`/iid-assessments/preview?tenant=${TENANT}`);
    await expect(page.getByLabel(/Active FDA release ID/)).not.toHaveValue("");
    await page.getByLabel(/Ingredient name/).fill(ingredient);
    await page.getByLabel(/^Route code/).fill(route);
    await page.getByLabel(/Dosage form code/).fill(form);
    await page.getByLabel("Proposed quantity per unit").fill("1");
    await page.getByLabel("Total dosage-unit weight").fill("250");
    await page.getByRole("button", { name: "Run preview" }).click();
    return page.getByRole("region", { name: "Assessment result" });
  };
  await step(page, "ingredient not in the IID", async () => {
    const result = await run("SYNTHETIC UNKNOWN EXCIPIENT 123", "ORAL", "TABLET");
    await expect(result.getByTestId("match-heading")).toHaveText("Ingredient not found in the active IID release");
    await expect(result).toContainText("was not found in the active IID release");
    await expect(result).not.toContainText("synonym mapping requires reviewer confirmation");
  });
  await step(page, "dosage form listed in the IID but not mapped (DROPS)", async () => {
    const result = await run("ALCOHOL", "ORAL", "DROPS");
    await expect(result.getByTestId("match-heading")).toHaveText("Dosage form not yet mapped by a reviewer");
    await expect(result).toContainText("no reviewer has mapped this dosage form");
    await expect(result).not.toContainText("must match exactly");
  });
  await step(page, "route not recognised", async () => {
    const result = await run("ACACIA", "PER OS", "TABLET");
    await expect(result.getByTestId("match-heading")).toHaveText("Route not recognised");
  });
  await step(page, "the preview says how many IID records are not linked", async () => {
    const result = await run("ACACIA", "ORAL", "TABLET");
    await expect(result.getByTestId("preview-release-health")).toContainText(/records have no route or dosage-form link/);
  });
  await step(page, "the releases page explains its counts", async () => {
    await page.goto(`/fda-data/releases?tenant=${TENANT}`);
    await expect(page.getByTestId("record-counts").first()).toContainText("rows read");
    await expect(page.getByText(/^0\/\d+$/)).toHaveCount(0);
    await expect(page.getByTestId("release-link-health").first()).toContainText("What to do:");
  });
});

test("Buttons follow what the user may do (QA-13)", async ({ page }) => {
  await signIn(page, "doer");
  await step(page, "doer sees New product record", async () => {
    await page.goto(`/formulations?tenant=${TENANT}`);
    await expect(page.getByRole("link", { name: "New product record" })).toBeVisible();
  });
  const approved = await api(page, "GET", "iig-checklists/executions/?status=approved");
  const execution = ((approved.json as { results?: { public_id: string; status: string }[] })?.results ?? []).find(
    (e) => e.status === "approved",
  );
  await step(page, "doer is not offered Supersede on an approved checklist", async () => {
    test.skip(!execution, "no approved execution on this stack (flows.spec.ts approves one)");
    await page.goto(`/iig-checklists/executions/${execution!.public_id}?tenant=${TENANT}`);
    await expect(page.getByTestId("no-actions")).toBeVisible();
    await expect(page.getByRole("button", { name: "Supersede" })).toHaveCount(0);
  });
  await page.context().clearCookies();
  await signIn(page, "vp");
  await step(page, "vp is not offered New product record", async () => {
    await page.goto(`/formulations?tenant=${TENANT}`);
    await expect(page.getByRole("heading", { name: "Product Development Records" })).toBeVisible();
    await expect(page.getByRole("link", { name: "New product record" })).toHaveCount(0);
  });
});
