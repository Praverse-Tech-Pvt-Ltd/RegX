// Supersede on an approved checklist execution needs a confirmation that names the execution,
// warns that it takes effect at once (only a VP can reinstate it), and a typed reason (owner, 2026-11-26; QA-11 in the 2026-11-25
// browser regression: one click superseded an approved execution). API mocked with page.route.
import { test, expect, type Route } from "@playwright/test";

const TENANT = "alpha";
const API = "http://localhost:8000";
const json = (body: unknown, status = 200) => (route: Route) =>
  route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });

const APPROVED = {
  public_id: "exec-e2e-1",
  status: "approved",
  checklist_version: { public_id: "ver-e2e-1", version_number: 2, status: "active" },
  formulation_version_public_id: "fv-e2e-1",
  created_by_email: "doer@example.com",
  submitted_by_email: "doer@example.com",
  submitted_at: "2026-01-15T10:00:00Z",
  returned_by_email: null,
  returned_at: null,
  return_reason: "",
  approved_by_email: "vp@example.com",
  approved_at: "2026-01-16T12:00:00Z",
  rejected_by_email: null,
  rejected_at: null,
  cancelled_by_email: null,
  cancelled_at: null,
  reviewer_conclusion_note: "Approved.",
  supersede_reason: "",
  available_actions: ["supersede"],
  created_at: "2026-01-15T10:00:00Z",
  updated_at: "2026-01-16T12:00:00Z",
};

async function open(page: import("@playwright/test").Page, posts: unknown[]) {
  await page.route(`${API}/api/regx/v1/auth/csrf/`, json({ csrfToken: "e2e-csrf-token" }));
  await page.route(`${API}/api/regx/v1/iig-checklists/executions/exec-e2e-1/**`, json({ count: 0, next: null, previous: null, results: [] }));
  await page.route(`${API}/api/regx/v1/iig-checklists/executions/exec-e2e-1/supersede/`, async (route) => {
    posts.push(route.request().postDataJSON());
    const reason = (route.request().postDataJSON() as { reason?: string }).reason ?? "";
    return json({ ...APPROVED, status: "superseded", supersede_reason: reason, available_actions: [] })(route);
  });
  await page.route(`${API}/api/regx/v1/iig-checklists/executions/exec-e2e-1/`, json(APPROVED));
  await page.goto(`/iig-checklists/executions/exec-e2e-1?tenant=${TENANT}`);
}

test("Supersede asks for confirmation (names the execution, warns) and a reason", async ({ page }) => {
  const posts: unknown[] = [];
  await open(page, posts);
  await page.getByRole("button", { name: /^Supersede$/ }).click();

  const dialog = page.getByRole("dialog", { name: /supersede this approved execution/i });
  await expect(dialog).toBeVisible();
  await expect(dialog).toContainText("exec-e2e-1");
  await expect(dialog).toContainText("v2");
  await expect(dialog).toContainText("fv-e2e-1");
  await expect(dialog).toContainText(/stops counting as the approved execution at once/i);
  await expect(dialog).toContainText(/only a VP can reinstate it/i);
  expect(posts).toHaveLength(0); // opening the dialog sends nothing

  const confirm = dialog.getByRole("button", { name: /^Supersede execution$/ });
  await expect(confirm).toBeDisabled();
  await dialog.getByLabel(/reason/i).fill("   ");
  await expect(confirm).toBeDisabled();

  await dialog.getByRole("button", { name: /^Cancel$/ }).click();
  await expect(dialog).toHaveCount(0);
  expect(posts).toHaveLength(0);

  await page.getByRole("button", { name: /^Supersede$/ }).click();
  await page.getByRole("dialog").getByLabel(/reason/i).fill("Replaced after a corrected formulation (QA synthetic)");
  await page.getByRole("dialog").getByRole("button", { name: /^Supersede execution$/ }).click();

  await expect(page.getByRole("dialog")).toHaveCount(0);
  expect(posts).toEqual([{ reason: "Replaced after a corrected formulation (QA synthetic)" }]);
  await expect(page.getByText("superseded", { exact: true })).toBeVisible();
  await expect(page.getByText("Replaced after a corrected formulation (QA synthetic)")).toBeVisible();
});
