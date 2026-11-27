// Small fixes of 2026-11-26 (browser regression 2026-11-25, N-4 / N-5 / N-7 / QA-13 / N-9).
// API mocked with page.route.
import { test, expect, type Route } from "@playwright/test";

const TENANT = "alpha";
const API = "http://localhost:8000";
const json = (body: unknown, status = 200) => (route: Route) =>
  route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });

const VERSION = {
  public_id: "ver-e2e-1",
  definition_public_id: "def-e2e-1",
  scope_type: "tenant",
  version_number: 1,
  status: "under_review",
  effective_date: "2026-12-01",
  expiry_date: null,
  regulatory_basis: "",
  change_summary: "",
  cloned_from_version_public_id: null,
  submitted_by_email: "doer@example.com",
  approved_by_email: null,
  activated_by_email: null,
  sections: [],
  created_at: "2026-01-01T00:00:00Z",
};

async function base(page: import("@playwright/test").Page, me: string) {
  await page.route(`${API}/api/regx/v1/auth/csrf/`, json({ csrfToken: "e2e-csrf-token" }));
  await page.route(`${API}/api/regx/v1/auth/me/`, json({ id: "u1", email: me, full_name: "", is_active: true, mfa_required: false, created_at: "2026-01-01T00:00:00Z" }));
}

test("the submitter sees no Approve, Reject or Return; who submitted is shown (QA-13, N-4)", async ({ page }) => {
  await base(page, "doer@example.com");
  await page.route(`${API}/api/regx/v1/iig-checklists/versions/ver-e2e-1/`, json(VERSION));
  await page.goto(`/iig-checklists/versions/ver-e2e-1?tenant=${TENANT}`);
  await expect(page.getByText(/you submitted this version for review/i)).toBeVisible();
  await expect(page.getByText("doer@example.com")).toBeVisible();
  for (const name of [/^Approve$/, /^Reject$/, /^Return for edits$/]) {
    await expect(page.getByRole("button", { name })).toHaveCount(0);
  }
});

test("another user still gets the review actions", async ({ page }) => {
  await base(page, "vp@example.com");
  await page.route(`${API}/api/regx/v1/iig-checklists/versions/ver-e2e-1/`, json(VERSION));
  await page.goto(`/iig-checklists/versions/ver-e2e-1?tenant=${TENANT}`);
  await expect(page.getByRole("button", { name: /^Approve$/ })).toBeVisible();
  await expect(page.getByRole("button", { name: /^Reject$/ })).toBeVisible();
  await expect(page.getByRole("button", { name: /^Return for edits$/ })).toBeVisible();
});

test("a list-shaped error shows its sentence, not 'Request failed' (N-5)", async ({ page }) => {
  await base(page, "doer@example.com");
  await page.route(`${API}/api/regx/v1/iig-checklists/versions/ver-e2e-1/`, json({ ...VERSION, status: "draft", submitted_by_email: null, effective_date: null }));
  await page.route(
    `${API}/api/regx/v1/iig-checklists/versions/ver-e2e-1/submit-review/`,
    json({ error: { status: 400, detail: ["effective_date is required before submitting for review."] } }, 400),
  );
  await page.goto(`/iig-checklists/versions/ver-e2e-1?tenant=${TENANT}`);
  await page.getByRole("button", { name: "Submit for review" }).click();
  await expect(page.locator("main").getByRole("alert")).toHaveText("effective_date is required before submitting for review.");
  await expect(page.getByText("Request failed")).toHaveCount(0);
});

test("/documents signed out goes to sign-in, with no contradictory messages (N-7)", async ({ page }) => {
  await page.route(`${API}/api/regx/v1/auth/csrf/`, json({ csrfToken: "e2e-csrf-token" }));
  const signedOut = json({ error: { status: 403, code: "not_authenticated", detail: { detail: "Authentication credentials were not provided." } } }, 403);
  await page.route(`${API}/api/regx/v1/**`, signedOut);
  await page.goto(`/documents?tenant=${TENANT}`);
  await expect(page).toHaveURL(/\/signin\?next=%2Fdocuments/);
  await expect(page.getByText(/No documents yet/)).toHaveCount(0);
  await expect(page.getByText(/Failed to load documents/)).toHaveCount(0);
});
