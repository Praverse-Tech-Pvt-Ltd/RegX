// A checklist version with no questions is refused at submit (N-2, browser regression
// 2026-11-25); the screen shows the server's real reason, not "Request failed". API mocked with
// page.route; the 400 body is the one the server now sends (DRF envelope, error.code =
// version_has_no_questions).
import { test, expect, type Route } from "@playwright/test";

const TENANT = "alpha";
const API = "http://localhost:8000";
const json = (body: unknown, status = 200) => (route: Route) =>
  route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });

const DRAFT_NO_QUESTIONS = {
  public_id: "ver-e2e-1",
  definition_public_id: "def-e2e-1",
  version_number: 1,
  status: "draft",
  effective_date: "2026-12-01",
  expiry_date: null,
  regulatory_basis: "",
  change_summary: "",
  cloned_from_version_public_id: null,
  return_reason: "",
  sections: [],
  created_at: "2026-01-01T00:00:00Z",
};

const REASON =
  "This checklist version has no questions. Add at least one section with at least one question before submitting for review.";

test("submitting a version with no questions shows the server's reason and stays a draft", async ({ page }) => {
  await page.route(`${API}/api/regx/v1/auth/csrf/`, json({ csrfToken: "e2e-csrf-token" }));
  await page.route(`${API}/api/regx/v1/iig-checklists/versions/ver-e2e-1/`, json(DRAFT_NO_QUESTIONS));
  await page.route(
    `${API}/api/regx/v1/iig-checklists/versions/ver-e2e-1/submit-review/`,
    json({ error: { status: 400, detail: { detail: REASON }, code: "version_has_no_questions" } }, 400),
  );

  await page.goto(`/iig-checklists/versions/ver-e2e-1?tenant=${TENANT}`);
  await page.getByRole("button", { name: "Submit for review" }).click();

  await expect(page.locator("main").getByRole("alert")).toHaveText(REASON);
  await expect(page.getByText("Request failed")).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Submit for review" })).toBeVisible();
});
