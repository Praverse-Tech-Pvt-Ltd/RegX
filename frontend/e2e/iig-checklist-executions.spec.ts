// IIG checklist EXECUTION Playwright suite -- Milestone 4D-2.
//
// All backend responses are deterministic Playwright route mocks (page.route).
// Server-side enforcement (permissions, lifecycle, tenant isolation, history
// immutability) is covered by the backend pytest suite. This suite proves
// that the frontend pages render correctly and react to the API contracts:
// list, create, detail, and lifecycle action buttons.
// Fixtures are synthetic and non-confidential.
import { test, expect, type Route } from "@playwright/test";

const TENANT = "alpha";
const API = "http://localhost:8000";

function jsonRoute(body: unknown, status = 200) {
  return (route: Route) =>
    route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
}

function paginate(results: unknown[]) {
  return { count: results.length, next: null, previous: null, results };
}

async function mockCsrf(page: import("@playwright/test").Page) {
  await page.route(`${API}/api/regx/v1/auth/csrf/`, jsonRoute({ csrfToken: "e2e-csrf-token" }));
}

function executionFixture(overrides: Record<string, unknown> = {}) {
  return {
    public_id: "exec-e2e-1",
    status: "draft",
    checklist_version: {
      public_id: "ver-e2e-1",
      version_number: 1,
      status: "active",
    },
    formulation_version_public_id: "fv-e2e-1",
    created_by_email: "doer@example.com",
    submitted_by_email: null,
    submitted_at: null,
    returned_by_email: null,
    returned_at: null,
    return_reason: "",
    approved_by_email: null,
    approved_at: null,
    rejected_by_email: null,
    rejected_at: null,
    cancelled_by_email: null,
    cancelled_at: null,
    reviewer_conclusion_note: "",
    created_at: "2026-01-15T10:00:00Z",
    updated_at: "2026-01-15T10:00:00Z",
    ...overrides,
  };
}

function responseFixture(overrides: Record<string, unknown> = {}) {
  return {
    public_id: "resp-e2e-1",
    question_public_id: "q-e2e-1",
    data_source_type_snapshot: "user_required",
    raw_value: null,
    is_not_applicable: false,
    not_applicable_reason: null,
    entered_by_email: null,
    entered_at: null,
    confirmed_by_email: null,
    confirmed_at: null,
    override_reason: "",
    system_derived_value: null,
    version: 1,
    ...overrides,
  };
}

// ---------------------------------------------------------------------------
// Execution list page
// ---------------------------------------------------------------------------

test("execution list page renders empty state", async ({ page }) => {
  await mockCsrf(page);
  await page.route(
    `${API}/api/regx/v1/iig-checklists/executions/**`,
    jsonRoute(paginate([]))
  );

  await page.goto(`/iig-checklists/executions?tenant=${TENANT}`);
  await expect(page.getByText("Checklist Executions")).toBeVisible();
  await expect(page.getByText("No executions found.")).toBeVisible();
  await expect(page.getByText("New execution")).toBeVisible();
});

test("execution list page renders execution rows", async ({ page }) => {
  await mockCsrf(page);
  await page.route(
    `${API}/api/regx/v1/iig-checklists/executions/**`,
    jsonRoute(paginate([executionFixture(), executionFixture({ public_id: "exec-e2e-2", status: "approved" })]))
  );

  await page.goto(`/iig-checklists/executions?tenant=${TENANT}`);
  await expect(page.getByText("draft")).toBeVisible();
  await expect(page.getByText("approved")).toBeVisible();
  const viewLinks = page.getByRole("link", { name: "View" });
  await expect(viewLinks).toHaveCount(2);
});

test("execution list page shows 403 inline (no redirect)", async ({ page }) => {
  await mockCsrf(page);
  await page.route(
    `${API}/api/regx/v1/iig-checklists/executions/**`,
    jsonRoute({ detail: "Forbidden" }, 403)
  );

  await page.goto(`/iig-checklists/executions?tenant=${TENANT}`);
  await expect(page.getByText(/permission|Forbidden/i)).toBeVisible();
  // Must NOT redirect to /signin
  await expect(page).not.toHaveURL(/signin/);
});

test("execution list page redirects to signin on 401", async ({ page }) => {
  await mockCsrf(page);
  await page.route(
    `${API}/api/regx/v1/iig-checklists/executions/**`,
    jsonRoute({ detail: "Unauthorized" }, 401)
  );

  await page.goto(`/iig-checklists/executions?tenant=${TENANT}`);
  await expect(page).toHaveURL(/signin/);
});

// ---------------------------------------------------------------------------
// New execution page
// ---------------------------------------------------------------------------

test("new execution page renders form", async ({ page }) => {
  await mockCsrf(page);
  await page.goto(`/iig-checklists/executions/new?tenant=${TENANT}`);
  await expect(page.getByText("New Checklist Execution")).toBeVisible();
  await expect(page.getByLabel(/Checklist Version Public ID/i)).toBeVisible();
  await expect(page.getByLabel(/Formulation Version Public ID/i)).toBeVisible();
  await expect(page.getByRole("button", { name: /Create execution/i })).toBeVisible();
});

test("new execution page submits and redirects on 201", async ({ page }) => {
  await mockCsrf(page);
  await page.route(`${API}/api/regx/v1/iig-checklists/executions/`, (route) => {
    if (route.request().method() === "POST") {
      route.fulfill({
        status: 201,
        contentType: "application/json",
        body: JSON.stringify(executionFixture()),
      });
    } else {
      route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(paginate([])) });
    }
  });
  // Mock the detail page load after redirect
  await page.route(
    `${API}/api/regx/v1/iig-checklists/executions/exec-e2e-1/`,
    jsonRoute(executionFixture())
  );

  await page.goto(`/iig-checklists/executions/new?tenant=${TENANT}`);
  await page.getByLabel(/Checklist Version Public ID/i).fill("ver-e2e-1");
  await page.getByLabel(/Formulation Version Public ID/i).fill("fv-e2e-1");
  await page.getByRole("button", { name: /Create execution/i }).click();

  await expect(page).toHaveURL(/executions\/exec-e2e-1/);
});

test("new execution page shows 409 conflict inline", async ({ page }) => {
  await mockCsrf(page);
  await page.route(`${API}/api/regx/v1/iig-checklists/executions/`, (route) => {
    if (route.request().method() === "POST") {
      route.fulfill({ status: 409, contentType: "application/json", body: JSON.stringify({}) });
    } else {
      route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(paginate([])) });
    }
  });

  await page.goto(`/iig-checklists/executions/new?tenant=${TENANT}`);
  await page.getByLabel(/Checklist Version Public ID/i).fill("ver-e2e-1");
  await page.getByLabel(/Formulation Version Public ID/i).fill("fv-e2e-1");
  await page.getByRole("button", { name: /Create execution/i }).click();

  await expect(
    page.getByText(/An active execution already exists/i)
  ).toBeVisible();
});

test("new execution page shows 403 inline", async ({ page }) => {
  await mockCsrf(page);
  await page.route(`${API}/api/regx/v1/iig-checklists/executions/`, (route) => {
    if (route.request().method() === "POST") {
      route.fulfill({ status: 403, contentType: "application/json", body: JSON.stringify({}) });
    } else {
      route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(paginate([])) });
    }
  });

  await page.goto(`/iig-checklists/executions/new?tenant=${TENANT}`);
  await page.getByLabel(/Checklist Version Public ID/i).fill("ver-e2e-1");
  await page.getByLabel(/Formulation Version Public ID/i).fill("fv-e2e-1");
  await page.getByRole("button", { name: /Create execution/i }).click();

  await expect(page.getByText(/permission/i)).toBeVisible();
  await expect(page).not.toHaveURL(/signin/);
});

// ---------------------------------------------------------------------------
// Execution detail page
// ---------------------------------------------------------------------------

test("execution detail page renders draft execution with submit/cancel buttons", async ({ page }) => {
  await mockCsrf(page);
  await page.route(
    `${API}/api/regx/v1/iig-checklists/executions/exec-e2e-1/`,
    jsonRoute(executionFixture({ status: "draft" }))
  );
  await page.route(`${API}/api/regx/v1/iig-checklists/executions/exec-e2e-1/**`, jsonRoute({}));

  await page.goto(`/iig-checklists/executions/exec-e2e-1?tenant=${TENANT}`);
  await expect(page.getByText("Checklist Execution")).toBeVisible();
  await expect(page.getByText("draft")).toBeVisible();
  await expect(page.getByRole("button", { name: /Submit for review/i })).toBeVisible();
  await expect(page.getByRole("button", { name: /Cancel/i })).toBeVisible();
});

test("execution detail page renders submitted_for_review state with approve/return/reject", async ({ page }) => {
  await mockCsrf(page);
  await page.route(
    `${API}/api/regx/v1/iig-checklists/executions/exec-e2e-1/`,
    jsonRoute(executionFixture({ status: "submitted_for_review" }))
  );
  await page.route(`${API}/api/regx/v1/iig-checklists/executions/exec-e2e-1/**`, jsonRoute({}));

  await page.goto(`/iig-checklists/executions/exec-e2e-1?tenant=${TENANT}`);
  await expect(page.getByRole("button", { name: /Approve/i })).toBeVisible();
  await expect(page.getByRole("button", { name: /Return/i })).toBeVisible();
  await expect(page.getByRole("button", { name: /Reject/i })).toBeVisible();
  // Approve button disabled until reviewer_conclusion_note filled in
  await expect(page.getByRole("button", { name: /Approve/i })).toBeDisabled();
});

test("approve button enabled only when reviewer conclusion note is filled", async ({ page }) => {
  await mockCsrf(page);
  await page.route(
    `${API}/api/regx/v1/iig-checklists/executions/exec-e2e-1/`,
    jsonRoute(executionFixture({ status: "submitted_for_review" }))
  );
  await page.route(`${API}/api/regx/v1/iig-checklists/executions/exec-e2e-1/**`, jsonRoute({}));

  await page.goto(`/iig-checklists/executions/exec-e2e-1?tenant=${TENANT}`);
  const approveBtn = page.getByRole("button", { name: /Approve/i });
  await expect(approveBtn).toBeDisabled();

  await page.getByLabel(/Reviewer conclusion note/i).fill("Conclusion text here");
  await expect(approveBtn).toBeEnabled();
});

test("execution detail page renders approved state with supersede button only", async ({ page }) => {
  await mockCsrf(page);
  await page.route(
    `${API}/api/regx/v1/iig-checklists/executions/exec-e2e-1/`,
    jsonRoute(
      executionFixture({
        status: "approved",
        approved_by_email: "vp@example.com",
        approved_at: "2026-01-16T12:00:00Z",
        reviewer_conclusion_note: "Approved.",
      })
    )
  );
  await page.route(`${API}/api/regx/v1/iig-checklists/executions/exec-e2e-1/**`, jsonRoute({}));

  await page.goto(`/iig-checklists/executions/exec-e2e-1?tenant=${TENANT}`);
  await expect(page.getByRole("button", { name: /Supersede/i })).toBeVisible();
  await expect(page.getByRole("button", { name: /Submit for review/i })).not.toBeVisible();
  await expect(page.getByRole("button", { name: /Approve/i })).not.toBeVisible();
  await expect(page.getByText("vp@example.com")).toBeVisible();
});

test("execution detail page shows no action buttons for terminal statuses", async ({ page }) => {
  for (const status of ["rejected", "cancelled", "superseded"]) {
    await mockCsrf(page);
    await page.route(
      `${API}/api/regx/v1/iig-checklists/executions/exec-e2e-1/`,
      jsonRoute(executionFixture({ status }))
    );
    await page.route(`${API}/api/regx/v1/iig-checklists/executions/exec-e2e-1/**`, jsonRoute({}));

    await page.goto(`/iig-checklists/executions/exec-e2e-1?tenant=${TENANT}`);
    await expect(page.getByRole("button", { name: /Submit for review/i })).not.toBeVisible();
    await expect(page.getByRole("button", { name: /Approve/i })).not.toBeVisible();
    await expect(page.getByRole("button", { name: /Cancel/i })).not.toBeVisible();
  }
});

test("execution detail page shows 403 action error inline (no redirect to signin)", async ({ page }) => {
  await mockCsrf(page);
  await page.route(
    `${API}/api/regx/v1/iig-checklists/executions/exec-e2e-1/`,
    jsonRoute(executionFixture({ status: "draft" }))
  );
  await page.route(
    `${API}/api/regx/v1/iig-checklists/executions/exec-e2e-1/cancel/`,
    jsonRoute({ detail: "Forbidden" }, 403)
  );
  await page.route(`${API}/api/regx/v1/iig-checklists/executions/exec-e2e-1/**`, jsonRoute({}));

  await page.goto(`/iig-checklists/executions/exec-e2e-1?tenant=${TENANT}`);
  await page.getByRole("button", { name: /Cancel/i }).click();

  await expect(page.getByText(/permission/i)).toBeVisible();
  await expect(page).not.toHaveURL(/signin/);
});

test("execution detail page shows returned state with submit/cancel buttons", async ({ page }) => {
  await mockCsrf(page);
  await page.route(
    `${API}/api/regx/v1/iig-checklists/executions/exec-e2e-1/`,
    jsonRoute(
      executionFixture({
        status: "returned",
        returned_by_email: "reviewer@example.com",
        returned_at: "2026-01-17T09:00:00Z",
        return_reason: "Please fix Q3.",
      })
    )
  );
  await page.route(`${API}/api/regx/v1/iig-checklists/executions/exec-e2e-1/**`, jsonRoute({}));

  await page.goto(`/iig-checklists/executions/exec-e2e-1?tenant=${TENANT}`);
  await expect(page.getByText("returned")).toBeVisible();
  await expect(page.getByText("Please fix Q3.")).toBeVisible();
  await expect(page.getByRole("button", { name: /Submit for review/i })).toBeVisible();
  await expect(page.getByRole("button", { name: /Cancel/i })).toBeVisible();
});
