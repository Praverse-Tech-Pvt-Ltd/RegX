// P7 -- the Gap Analysis panel on an execution detail page.
//
// All backend responses are deterministic Playwright route mocks. Server-side
// enforcement (permissions, immutability, tenant isolation, the classification
// rules themselves) is covered by the backend pytest suite; this suite proves
// the page renders the contract and reacts to it.
//
// The overclaim assertions are the ones worth keeping honest: no governed
// scoring formula exists in RegX, so a percentage here would be an unapproved
// number presented as a product feature, and readiness or compliance wording
// would be a regulatory conclusion the platform has not reached.
// Fixtures are synthetic and non-confidential.
import { test, expect, type Route } from "@playwright/test";

const TENANT = "alpha";
const API = "http://localhost:8000";
const EXEC = "exec-gap-1";
const ANALYSIS = "analysis-gap-1";
const OLDER = "analysis-gap-0";

function jsonRoute(body: unknown, status = 200) {
  return (route: Route) =>
    route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
}

function executionFixture() {
  return {
    public_id: EXEC,
    status: "draft",
    checklist_version: { public_id: "cv-gap-1", version_number: 3, status: "active" },
    formulation_version: { public_id: "fv-gap-1", version_number: 1 },
    created_at: "2026-09-01T09:00:00Z",
    updated_at: "2026-09-01T09:00:00Z",
  };
}

function item(overrides: Record<string, unknown> = {}) {
  return {
    question_public_id: "q-1",
    question_code: "Q-NO",
    question_text: "Is the dissolution method validated?",
    answer_type: "yes_no",
    section_code: "SEC-B",
    section_title: "Shared title",
    section_display_order: 2,
    display_order: 1,
    status: "gap",
    reason_code: "ANSWER_NO",
    configured_criticality: "critical",
    ...overrides,
  };
}

function header(overrides: Record<string, unknown> = {}) {
  return {
    public_id: ANALYSIS,
    execution_public_id: EXEC,
    checklist_version_public_id: "cv-gap-1",
    checklist_version_number: 3,
    checklist_version_status: "active",
    input_hash: "a".repeat(64),
    algorithm_version: 1,
    generated_by_email: "doer@example.test",
    generated_at: "2026-09-15T10:30:00Z",
    counts: {
      total_questions: 4,
      applicable: 3,
      gap: 1,
      no_gap: 1,
      unanswered: 0,
      review_required: 1,
      not_applicable: 1,
    },
    ...overrides,
  };
}

const ITEMS = [
  item(),
  item({
    question_public_id: "q-2",
    question_code: "Q-REVIEW",
    question_text: "Does the excipient exceed the IID limit?",
    status: "review_required",
    reason_code: "APPLICABILITY_REVIEW_REQUIRED",
    display_order: 2,
  }),
  item({
    question_public_id: "q-3",
    question_code: "Q-YES",
    question_text: "Is the batch record complete?",
    status: "no_gap",
    reason_code: "ANSWER_YES",
    display_order: 3,
  }),
  // Authored first, in a section that shares the other one's title.
  item({
    question_public_id: "q-4",
    question_code: "Q-OTHER",
    question_text: "Is the container closure qualified?",
    section_code: "SEC-A",
    section_display_order: 1,
    status: "not_applicable",
    reason_code: "APPLICABILITY_NOT_APPLICABLE",
    configured_criticality: "low",
    display_order: 1,
  }),
];

async function mockExecution(page: import("@playwright/test").Page) {
  await page.route(`${API}/api/regx/v1/auth/csrf/`, jsonRoute({ csrfToken: "e2e-csrf-token" }));
  // Wildcard first (lower priority); exact routes registered after win.
  await page.route(`${API}/api/regx/v1/iig-checklists/executions/${EXEC}/**`, jsonRoute({}));
  await page.route(
    `${API}/api/regx/v1/iig-checklists/executions/${EXEC}/`,
    jsonRoute(executionFixture())
  );
}

async function mockAnalyses(
  page: import("@playwright/test").Page,
  {
    results = [header()],
    latestIsCurrent = true,
    detail = { ...header(), items: ITEMS },
  }: { results?: unknown[]; latestIsCurrent?: boolean; detail?: unknown } = {}
) {
  await page.route(
    `${API}/api/regx/v1/iig-checklists/executions/${EXEC}/gap-analyses/`,
    jsonRoute({ current_input_hash: "a".repeat(64), latest_is_current: latestIsCurrent, results })
  );
  await page.route(
    `${API}/api/regx/v1/iig-checklists/executions/${EXEC}/gap-analyses/${ANALYSIS}/`,
    jsonRoute(detail)
  );
}

test("renders the summary counts and the source of the analysis", async ({ page }) => {
  await mockExecution(page);
  await mockAnalyses(page);

  await page.goto(`/iig-checklists/executions/${EXEC}?tenant=${TENANT}`);
  const panel = page.getByRole("region", { name: /Gap analysis/i });

  await expect(panel.getByText(/Checklist gap: 1/)).toBeVisible();
  await expect(panel.getByText(/Review required: 1/)).toBeVisible();
  await expect(panel.getByText(/Applicable: 3 of 4/)).toBeVisible();
  await expect(panel.getByText(/doer@example\.test/)).toBeVisible();
  await expect(panel.getByText(/Version 3/)).toBeVisible();
});

test("groups by section code and keeps authored order when titles collide", async ({ page }) => {
  await mockExecution(page);
  await mockAnalyses(page);

  await page.goto(`/iig-checklists/executions/${EXEC}?tenant=${TENANT}`);
  const panel = page.getByRole("region", { name: /Gap analysis/i });
  // "Needs attention" hides the N/A row, so show everything first.
  await panel.getByLabel("Filter by status").selectOption("all");

  const headings = panel.getByRole("heading", { level: 3 });
  await expect(headings).toHaveCount(2);
  await expect(headings.nth(0)).toContainText("SEC-A");
  await expect(headings.nth(1)).toContainText("SEC-B");
});

test("shows review required as its own row status", async ({ page }) => {
  await mockExecution(page);
  await mockAnalyses(page);

  await page.goto(`/iig-checklists/executions/${EXEC}?tenant=${TENANT}`);
  const panel = page.getByRole("region", { name: /Gap analysis/i });
  const row = panel.getByRole("row").filter({ hasText: "Q-REVIEW" });
  await expect(row).toContainText("Review required");
  await expect(row).toContainText("Applicability could not be determined automatically");
});

test("filters to a single section", async ({ page }) => {
  await mockExecution(page);
  await mockAnalyses(page);

  await page.goto(`/iig-checklists/executions/${EXEC}?tenant=${TENANT}`);
  const panel = page.getByRole("region", { name: /Gap analysis/i });
  await panel.getByLabel("Filter by status").selectOption("all");
  await panel.getByLabel("Filter by section").selectOption("SEC-A");

  await expect(panel.getByRole("heading", { name: /SEC-A/ })).toBeVisible();
  await expect(panel.getByRole("heading", { name: /SEC-B/ })).toHaveCount(0);
});

test("reports a superseded checklist version as information, not as invalid", async ({ page }) => {
  await mockExecution(page);
  await mockAnalyses(page, {
    results: [header({ checklist_version_status: "superseded" })],
    detail: { ...header({ checklist_version_status: "superseded" }), items: ITEMS },
  });

  await page.goto(`/iig-checklists/executions/${EXEC}?tenant=${TENANT}`);
  const panel = page.getByRole("region", { name: /Gap analysis/i });
  await expect(panel.getByText(/this version is no longer current/i)).toBeVisible();
  await expect(panel.getByText(/remains a valid record/i)).toBeVisible();
  await expect(panel.getByText(/invalid/i)).toHaveCount(0);
});

test("says when answers have changed since the latest analysis", async ({ page }) => {
  await mockExecution(page);
  await mockAnalyses(page, { latestIsCurrent: false });

  await page.goto(`/iig-checklists/executions/${EXEC}?tenant=${TENANT}`);
  await expect(
    page.getByText(/Answers have changed since the latest analysis was generated/)
  ).toBeVisible();
});

test("lets an older snapshot be selected", async ({ page }) => {
  await mockExecution(page);
  await mockAnalyses(page, {
    results: [header(), header({ public_id: OLDER, generated_at: "2026-09-01T09:00:00Z" })],
  });
  await page.route(
    `${API}/api/regx/v1/iig-checklists/executions/${EXEC}/gap-analyses/${OLDER}/`,
    jsonRoute({
      ...header({ public_id: OLDER, generated_by_email: "reviewer@example.test" }),
      items: ITEMS,
    })
  );

  await page.goto(`/iig-checklists/executions/${EXEC}?tenant=${TENANT}`);
  const panel = page.getByRole("region", { name: /Gap analysis/i });
  await panel.getByLabel("Select gap analysis snapshot").selectOption(OLDER);
  await expect(panel.getByText(/reviewer@example\.test/)).toBeVisible();
});

test("explains an empty history instead of rendering nothing", async ({ page }) => {
  await mockExecution(page);
  await mockAnalyses(page, { results: [] });

  await page.goto(`/iig-checklists/executions/${EXEC}?tenant=${TENANT}`);
  await expect(
    page.getByText(/No gap analysis has been generated for this execution yet/)
  ).toBeVisible();
});

test("generates a snapshot on request", async ({ page }) => {
  await mockExecution(page);
  await mockAnalyses(page, { results: [] });
  await page.route(`${API}/api/regx/v1/iig-checklists/executions/${EXEC}/gap-analyses/`, (route) => {
    if (route.request().method() === "POST") {
      return jsonRoute({ ...header(), items: ITEMS }, 201)(route);
    }
    return jsonRoute({
      current_input_hash: "a".repeat(64),
      latest_is_current: true,
      results: [header()],
    })(route);
  });

  await page.goto(`/iig-checklists/executions/${EXEC}?tenant=${TENANT}`);
  const panel = page.getByRole("region", { name: /Gap analysis/i });
  await panel.getByRole("button", { name: /Generate analysis/ }).click();
  await expect(panel.getByRole("heading", { name: /SEC-B/ })).toBeVisible();
});

test("hides the generate control when the server refuses it", async ({ page }) => {
  await mockExecution(page);
  await page.route(`${API}/api/regx/v1/iig-checklists/executions/${EXEC}/gap-analyses/`, (route) => {
    if (route.request().method() === "POST") {
      return jsonRoute({ detail: "forbidden" }, 403)(route);
    }
    return jsonRoute({
      current_input_hash: "a".repeat(64),
      latest_is_current: false,
      results: [],
    })(route);
  });

  await page.goto(`/iig-checklists/executions/${EXEC}?tenant=${TENANT}`);
  const panel = page.getByRole("region", { name: /Gap analysis/i });
  await panel.getByRole("button", { name: /Generate analysis/ }).click();

  await expect(panel.getByRole("button", { name: /Generate analysis/ })).toHaveCount(0);
  await expect(panel.getByRole("alert")).toContainText(/do not have permission to generate/i);
});

test("renders no score and no readiness or compliance claim", async ({ page }) => {
  await mockExecution(page);
  await mockAnalyses(page);

  await page.goto(`/iig-checklists/executions/${EXEC}?tenant=${TENANT}`);
  const panel = page.getByRole("region", { name: /Gap analysis/i });
  await panel.getByLabel("Filter by status").selectOption("all");

  const text = (await panel.textContent()) ?? "";
  expect(text).not.toMatch(/\d\s*%/);
  expect(text).not.toMatch(/score/i);
  for (const forbidden of [
    /fda[- ]ready/i,
    /submission[- ]ready/i,
    /agency[- ]ready/i,
    /\bcompliant\b/i,
    /\bcertified\b/i,
  ]) {
    expect(text).not.toMatch(forbidden);
  }
  await expect(panel.getByText(/not a regulatory assessment/i)).toBeVisible();
});

test("survives a malformed gap-analysis response without taking the page down", async ({
  page,
}) => {
  await mockExecution(page);
  // The wildcard mock answers `{}` -- no `results` key at all. The panel must
  // degrade, because it is a section of the execution page rather than the
  // point of it.
  await page.goto(`/iig-checklists/executions/${EXEC}?tenant=${TENANT}`);

  await expect(page.getByText("Checklist Execution")).toBeVisible();
  await expect(page.getByRole("region", { name: /Gap analysis/i })).toBeVisible();
});
