/**
 * The main user flows, end to end, in a real browser on the real stack.
 *
 * Doer: create a product and a formulation version with two components, run an
 * IID preview on public FDA IID data, start the IIG checklist on that version and
 * submit it for review, upload a PDF. VP: approve the checklist execution.
 *
 * Needs: a seeded demo tenant, an ACTIVE FDA IID release with approved route /
 * dosage-form mappings (see scripts/real_stack_smoke.sh), REAL_STACK_PASSWORD,
 * and REAL_STACK_MFA_FILE for the VP's TOTP secret. Every step is recorded in
 * `$REAL_STACK_OUT/flows.jsonl` with a screenshot.
 */
import { expect, test, type Page } from "@playwright/test";
import { join } from "node:path";
import { OUT, TENANT, record, signIn } from "./helpers";

test.describe.configure({ mode: "serial" });

test.setTimeout(3 * 60 * 1000);

const RUN = Date.now().toString(36).toUpperCase();
const state: { versionUrl?: string; executionUrl?: string } = {};

async function step(page: Page, name: string, body: () => Promise<void>): Promise<void> {
  const shot = join(OUT, "screenshots", `flow__${name.replace(/[^a-z0-9]+/gi, "_")}.png`);
  const errors: string[] = [];
  const onResponse = (r: { url(): string; status(): number; request(): { method(): string } }) => {
    if (r.url().includes("/api/") && r.status() >= 400)
      errors.push(`${r.request().method()} ${new URL(r.url()).pathname} -> ${r.status()}`);
  };
  page.on("response", onResponse);
  try {
    await body();
    await page.screenshot({ path: shot, fullPage: true });
    record("flows.jsonl", { step: name, ok: true, failedApi: errors, screenshot: shot });
  } catch (e) {
    await page.screenshot({ path: shot, fullPage: true }).catch(() => undefined);
    record("flows.jsonl", { step: name, ok: false, error: String(e).slice(0, 500), failedApi: errors, screenshot: shot });
    throw e;
  } finally {
    page.off("response", onResponse);
  }
}

const PDF = Buffer.from(
  "%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n" +
    "3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]/Contents 4 0 R/Resources<<>>>>endobj\n" +
    "4 0 obj<</Length 44>>stream\nBT /F1 12 Tf 20 100 Td (Synthetic test) Tj ET\nendstream endobj\n" +
    "xref\n0 5\n0000000000 65535 f \ntrailer<</Size 5/Root 1 0 R>>\nstartxref\n0\n%%EOF\n",
);

test("Doer: product, formulation version, two components", async ({ page }) => {
  await signIn(page, "doer");
  await step(page, "create product", async () => {
    await page.goto(`/formulations/new?tenant=${TENANT}`);
    await page.getByLabel("Product code").fill(`RS-${RUN}`);
    await page.getByLabel("Proposed product name").fill("Real-stack synthetic tablet");
    await page.getByLabel("Active ingredient").fill("SYNTHETIC ACTIVE");
    await page.getByRole("button", { name: "Create" }).click();
    await expect(page).toHaveURL(/\/formulations\/[0-9a-f-]{36}\?tenant=/);
  });
  await step(page, "create formulation version", async () => {
    await page.getByRole("button", { name: "Create formulation version" }).click();
    await page.getByLabel("Total dosage-unit weight").fill("250");
    await page.getByLabel("Unit", { exact: true }).fill("mg");
    await page.getByLabel("Maximum dosage units/day").fill("4");
    await page.getByRole("button", { name: "Create version" }).click();
    // The app opens the new version straight away.
    await expect(page).toHaveURL(/\/versions\/[0-9a-f-]{36}/);
    await expect(page.getByRole("heading", { name: "Formulation Version 1" })).toBeVisible();
    state.versionUrl = page.url();
  });
  for (const [name, qty] of [
    ["MAGNESIUM STEARATE", "2.5"],
    ["LACTOSE MONOHYDRATE", "120"],
  ] as const) {
    await step(page, `add component ${name}`, async () => {
      await page.getByRole("button", { name: "Add component" }).click();
      await page.getByLabel("Ingredient name").fill(name);
      await page.getByLabel("Quantity per dosage unit").fill(qty);
      // QA-02: the component unit is chosen from a list (it was free text).
      await page.getByLabel("Unit", { exact: true }).selectOption("mg");
      await page.getByRole("button", { name: "Add", exact: true }).click();
      await expect(page.getByRole("cell", { name })).toBeVisible();
    });
  }
});

test("Doer: IID preview on public FDA IID data", async ({ page }) => {
  await signIn(page, "doer");
  await step(page, "iid preview", async () => {
    await page.goto(state.versionUrl!);
    await page.getByRole("link", { name: /Run IID assessment preview/ }).click();
    await expect(page.getByLabel(/Active FDA release ID/)).not.toHaveValue("");
    await page.getByLabel(/Ingredient name/).fill("MAGNESIUM STEARATE");
    await page.getByLabel(/^Route code/).fill("ORAL");
    await page.getByLabel(/Dosage form code/).fill("TABLET");
    await page.getByLabel("Proposed quantity per unit").fill("2.5");
    await page.getByLabel("Total dosage-unit weight").fill("250");
    await page.getByRole("button", { name: "Run preview" }).click();
    const result = page.getByRole("region", { name: "Assessment result" });
    await expect(result).toBeVisible();
    await expect(result.getByText(/Match status/)).toBeVisible();
    await expect(result.getByText("Like-for-like comparison")).toBeVisible();
    // The page's own error line (not the result's "Not comparable" box).
    await expect(page.getByRole("alert").filter({ hasText: /failed|error|could not/i })).toHaveCount(0);
  });
});

test("Doer: submit the new formulation version for review", async ({ page }) => {
  await signIn(page, "doer");
  await step(page, "doer submits the new version for review", async () => {
    await page.goto(state.versionUrl!);
    const review = page.getByTestId("formulation-review");
    await expect(review.getByTestId("version-status")).toHaveText("Draft");
    await review.getByRole("button", { name: "Submit for review" }).click();
    await page.getByRole("dialog").getByRole("button", { name: "Submit for review" }).click();
    await expect(review.getByTestId("version-status")).toHaveText("Under review");
    // The Doer is offered no approval action, and the version is frozen.
    await expect(review.getByRole("button", { name: "Approve" })).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Add component" })).toHaveCount(0);
  });
});

test("VP: approve the new formulation version", async ({ page }) => {
  await signIn(page, "vp");
  await step(page, "vp approves the new version (with a note, after confirming)", async () => {
    await page.goto(state.versionUrl!);
    const review = page.getByTestId("formulation-review");
    await expect(review.getByTestId("version-status")).toHaveText("Under review");
    await review.getByRole("button", { name: "Approve" }).click();
    const dialog = page.getByRole("dialog");
    await expect(dialog.getByRole("button", { name: "Approve" })).toBeDisabled(); // a note is required
    await dialog.getByLabel(/Approval note/).fill("Real-stack test: synthetic formulation reviewed (internal).");
    await dialog.getByRole("button", { name: "Approve" }).click();
    await expect(review.getByTestId("version-status")).toHaveText("Approved (internal)");
    await expect(review.getByRole("table", { name: "Version history" })).toContainText("approved (internal)");
  });
});

test("Doer: run the IIG checklist and submit it for review", async ({ page }) => {
  await signIn(page, "doer");
  // QA-01 closed by Option A: the version created above is now approved, so the
  // IIG checklist runs on it. This step used to be recorded as BLOCKED.
  await step(page, "the newly created, approved formulation runs the IIG checklist", async () => {
    await page.goto(state.versionUrl!);
    await page.getByRole("link", { name: /Run IIG checklist on this version/ }).click();
    const optionState = () =>
      page.evaluate((code) => {
        const option = [...document.querySelectorAll("option")].find((o) => o.textContent?.includes(code));
        return option ? { text: option.textContent, disabled: option.disabled } : null;
      }, `RS-${RUN}`);
    await expect.poll(optionState).toMatchObject({ disabled: false });
    const selects = page.locator("main select");
    await selects.first().selectOption({ index: 1 }); // the active demo checklist version
    await page.getByRole("button", { name: "Create execution" }).click();
    await expect(page).toHaveURL(/\/iig-checklists\/executions\/[0-9a-f-]{36}/);
    await expect(page.getByText("draft").first()).toBeVisible();
  });
  // The demo seed's approved formulation version has a draft execution on the
  // active demo checklist; run that one through review.
  await step(page, "open the draft checklist execution", async () => {
    await page.goto(`/iig-checklists/executions?tenant=${TENANT}`);
    const row = page.getByRole("row").filter({ hasText: /^draft|draft/ }).first();
    await row.getByRole("link", { name: "View" }).click();
    await expect(page).toHaveURL(/\/iig-checklists\/executions\/[0-9a-f-]{36}/);
    state.executionUrl = page.url();
  });
  await step(page, "answer the checklist questions", async () => {
    // Submission is refused until every required question has a response.
    const items = page.locator('[data-testid^="response-"]').filter({ has: page.locator('[aria-label^="Answer for "]') });
    await expect(items.first()).toBeVisible();
    const count = await items.count();
    for (let i = 0; i < count; i++) {
      const item = items.nth(i);
      const control = item.locator('[aria-label^="Answer for "]');
      if ((await control.evaluate((el) => el.tagName)) === "SELECT") {
        await control.selectOption({ index: 1 });
      } else {
        await control.fill("Synthetic answer for the real-stack test");
      }
      await item.getByRole("button", { name: "Save" }).click();
      await expect(page.getByText(/Saved\./).first()).toBeVisible();
    }
  });
  await step(page, "submit execution for review", async () => {
    await page.getByRole("button", { name: "Submit for review" }).click();
    await expect(page.getByText("submitted_for_review").first()).toBeVisible();
  });
});

test("Doer: upload a PDF document", async ({ page }) => {
  await signIn(page, "doer");
  await step(page, "upload document", async () => {
    await page.goto(`/documents?tenant=${TENANT}`);
    await page.getByRole("button", { name: "Upload document" }).click();
    await page.getByLabel("Title").fill(`Real-stack synthetic PDF ${RUN}`);
    await page.getByLabel("Document type").selectOption("pdf");
    await page.getByLabel("File").setInputFiles({ name: "synthetic.pdf", mimeType: "application/pdf", buffer: PDF });
    await page.getByRole("button", { name: "Upload", exact: true }).click();
    await expect(page.getByText(`Real-stack synthetic PDF ${RUN}`)).toBeVisible();
  });
});

test("VP: approve the checklist execution", async ({ page }) => {
  await signIn(page, "vp");
  await step(page, "vp approves execution", async () => {
    await page.goto(state.executionUrl!);
    await page.getByLabel(/Reviewer conclusion note/).fill("Real-stack test: synthetic data reviewed.");
    await page.getByRole("button", { name: "Approve" }).click();
    await expect(page.getByText(/^approved$/).first()).toBeVisible();
  });
});
