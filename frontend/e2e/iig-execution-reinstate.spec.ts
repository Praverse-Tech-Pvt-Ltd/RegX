// Reinstate a superseded checklist execution (owner, 2026-11-27; follow-up to #167):
// VP only (the server lists "reinstate" in available_actions for a VP alone), a confirmation
// that names the execution, a typed reason, and the history (supersede reason) kept on screen.
// API mocked with page.route.
import { test, expect, type Route, type Page } from "@playwright/test";

const TENANT = "alpha";
const API = "http://localhost:8000";
const json = (body: unknown, status = 200) => (route: Route) =>
  route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });

const SUPERSEDE_REASON = "Replaced while the formulation was corrected (QA synthetic)";
const REINSTATE_REASON = "The correction was withdrawn; the earlier approval stands (QA synthetic)";

const SUPERSEDED = {
  public_id: "exec-e2e-2",
  status: "superseded",
  checklist_version: { public_id: "ver-e2e-2", version_number: 3, status: "active" },
  formulation_version_public_id: "fv-e2e-2",
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
  supersede_reason: SUPERSEDE_REASON,
  reinstated_by_email: null,
  reinstated_at: null,
  reinstate_reason: "",
  available_actions: ["reinstate"],
  created_at: "2026-01-15T10:00:00Z",
  updated_at: "2026-01-17T09:00:00Z",
};

async function open(page: Page, detail: object, onReinstate?: (route: Route) => Promise<void>) {
  await page.route(`${API}/api/regx/v1/auth/csrf/`, json({ csrfToken: "e2e-csrf-token" }));
  await page.route(`${API}/api/regx/v1/iig-checklists/executions/exec-e2e-2/**`, json({ count: 0, next: null, previous: null, results: [] }));
  if (onReinstate) {
    await page.route(`${API}/api/regx/v1/iig-checklists/executions/exec-e2e-2/reinstate/`, onReinstate);
  }
  await page.route(`${API}/api/regx/v1/iig-checklists/executions/exec-e2e-2/`, json(detail));
  await page.goto(`/iig-checklists/executions/exec-e2e-2?tenant=${TENANT}`);
  await expect(page.getByRole("heading", { name: "Checklist Execution" })).toBeVisible();
}

test("a VP reinstates a superseded execution after a confirmation with a typed reason", async ({ page }) => {
  const posts: unknown[] = [];
  await open(page, SUPERSEDED, async (route) => {
    const body = route.request().postDataJSON() as { reason?: string };
    posts.push(body);
    return json({
      ...SUPERSEDED,
      status: "approved",
      reinstated_by_email: "vp@example.com",
      reinstated_at: "2026-01-18T08:00:00Z",
      reinstate_reason: body.reason ?? "",
      available_actions: ["supersede"],
    })(route);
  });
  await expect(page.getByText(SUPERSEDE_REASON)).toBeVisible();

  await page.getByRole("button", { name: /^Reinstate$/ }).click();
  const dialog = page.getByRole("dialog", { name: /reinstate this superseded execution/i });
  await expect(dialog).toBeVisible();
  await expect(dialog).toContainText("exec-e2e-2");
  await expect(dialog).toContainText("v3");
  await expect(dialog).toContainText("fv-e2e-2");
  await expect(dialog).toContainText(SUPERSEDE_REASON);
  await expect(dialog).toContainText(/both stay on record/i);
  expect(posts).toHaveLength(0);

  const confirm = dialog.getByRole("button", { name: /^Reinstate execution$/ });
  await expect(confirm).toBeDisabled();
  await dialog.getByLabel(/reason/i).fill("   ");
  await expect(confirm).toBeDisabled();
  await dialog.getByRole("button", { name: /^Cancel$/ }).click();
  await expect(dialog).toHaveCount(0);
  expect(posts).toHaveLength(0);

  await page.getByRole("button", { name: /^Reinstate$/ }).click();
  await page.getByRole("dialog").getByLabel(/reason/i).fill(REINSTATE_REASON);
  await page.getByRole("dialog").getByRole("button", { name: /^Reinstate execution$/ }).click();

  await expect(page.getByRole("dialog")).toHaveCount(0);
  expect(posts).toEqual([{ reason: REINSTATE_REASON }]);
  await expect(page.getByText("approved", { exact: true })).toBeVisible();
  await expect(page.getByText(REINSTATE_REASON)).toBeVisible();
  await expect(page.getByText(SUPERSEDE_REASON)).toBeVisible(); // history kept on screen
  await expect(page.getByRole("row", { name: /Reinstated by/ })).toContainText("vp@example.com");
});

test("no Reinstate button unless the server offers it (not a VP, or no action list)", async ({ page }) => {
  await open(page, { ...SUPERSEDED, available_actions: [] });
  await expect(page.getByText(SUPERSEDE_REASON)).toBeVisible();
  await expect(page.getByRole("button", { name: /^Reinstate$/ })).toHaveCount(0);

  const { available_actions: _unused, ...withoutList } = SUPERSEDED;
  await page.unrouteAll({ behavior: "ignoreErrors" });
  await open(page, withoutList);
  await expect(page.getByText(SUPERSEDE_REASON)).toBeVisible();
  await expect(page.getByRole("button", { name: /^Reinstate$/ })).toHaveCount(0);
});

test("a refusal because another execution is live is shown, and nothing changes", async ({ page }) => {
  const detail =
    "Another execution for the same checklist version and formulation version is in progress or approved (exec-other). Close it before reinstating this one.";
  await open(page, SUPERSEDED, json({ error_code: "another_execution_active", detail }, 409));
  await page.getByRole("button", { name: /^Reinstate$/ }).click();
  await page.getByRole("dialog").getByLabel(/reason/i).fill(REINSTATE_REASON);
  await page.getByRole("dialog").getByRole("button", { name: /^Reinstate execution$/ }).click();
  await expect(page.getByText(detail)).toBeVisible();
  await expect(page.getByText("superseded", { exact: true })).toBeVisible();
});
