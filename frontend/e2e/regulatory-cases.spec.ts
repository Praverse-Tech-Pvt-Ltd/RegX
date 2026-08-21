import { test, expect, type Page, type Route } from "@playwright/test";

/**
 * Regulatory case workspace E2E.
 *
 * API responses are mocked with page.route, as every other spec in this suite
 * does, so the test exercises the UI contract rather than a live backend.
 *
 * The property under test is the one that matters for security posture: the UI
 * renders what the API projects. A link the server marked `restricted` shows a
 * marker and no detail; a control the server withheld is not offered. Hiding a
 * control is presentation only -- the backend re-checks every call.
 */

const API = "http://localhost:8000";
const TENANT = "alpha";
const CASE_ID = "22222222-3333-4444-5555-666666666666";

const PERMS = {
  can_edit: true,
  can_manage_links: true,
  can_complete: true,
  can_cancel: true,
  can_create: true,
};

function caseRow(over: Record<string, unknown> = {}) {
  return {
    public_id: CASE_ID,
    case_number: "RC-000001",
    title: "Stability data package",
    product_name: "Synthetic Product X",
    product_code: "SPX-1",
    market: "Synthetic Market",
    authority: "Synthetic Authority",
    submission_type: "Synthetic Submission",
    status: "open",
    owner: { public_id: "u-1", full_name: "Case Owner" },
    target_date: "2026-06-01",
    description: "Synthetic description",
    created_by: { public_id: "u-1", full_name: "Case Owner" },
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    is_terminal: false,
    ...over,
  };
}

function detail(over: Record<string, unknown> = {}) {
  return {
    case: caseRow(),
    workflows: [],
    documents: [],
    checklists: [],
    summary: {
      documents: 0,
      workflows: 0,
      checklists: 0,
      workflows_open: 0,
      workflows_completed: 0,
      evidence_links: 0,
    },
    permissions: PERMS,
    ...over,
  };
}

function jsonRoute(body: unknown, status = 200) {
  return async (route: Route) =>
    route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
}

async function mockCsrf(page: Page) {
  await page.route(`${API}/api/regx/v1/auth/csrf/`, jsonRoute({ csrfToken: "e2e-csrf-token" }));
}

async function mockList(page: Page, results: unknown[], permissions = PERMS) {
  await page.route(
    /\/api\/regx\/v1\/regulatory-cases\/(\?.*)?$/,
    jsonRoute({ results, permissions })
  );
}

async function mockDetail(page: Page, body: unknown) {
  await page.route(new RegExp(`/api/regx/v1/regulatory-cases/${CASE_ID}/$`), jsonRoute(body));
}

test.describe("Regulatory case list", () => {
  test("lists cases with number, product and status", async ({ page }) => {
    await mockCsrf(page);
    await mockList(page, [
      caseRow(),
      caseRow({
        public_id: "99999999-3333-4444-5555-666666666666",
        case_number: "RC-000002",
        title: "Second case",
        status: "completed",
        is_terminal: true,
      }),
    ]);

    await page.goto(`/regulatory-cases?tenant=${TENANT}`);

    await expect(page.getByTestId("cases-table")).toBeVisible();
    await expect(page.getByRole("link", { name: "RC-000001" })).toBeVisible();
    const badges = page.getByTestId("case-status-badge");
    await expect(badges.first()).toHaveAttribute("data-status", "open");
    await expect(badges.nth(1)).toHaveAttribute("data-status", "completed");
  });

  test("shows an empty state when the tenant has no cases", async ({ page }) => {
    await mockCsrf(page);
    await mockList(page, []);
    await page.goto(`/regulatory-cases?tenant=${TENANT}`);
    await expect(page.getByTestId("cases-empty")).toBeVisible();
  });

  test("offers no create control when the API withholds it", async ({ page }) => {
    await mockCsrf(page);
    await mockList(page, [], { ...PERMS, can_create: false });
    await page.goto(`/regulatory-cases?tenant=${TENANT}`);
    await expect(page.getByTestId("cases-empty")).toBeVisible();
    await expect(page.getByTestId("new-case")).toHaveCount(0);
  });

  test("creates a case and lands on its workspace", async ({ page }) => {
    await mockCsrf(page);
    await mockList(page, []);
    await mockDetail(page, detail());

    let posted: string | null = null;
    await page.route(/\/api\/regx\/v1\/regulatory-cases\/$/, async (route) => {
      if (route.request().method() !== "POST") {
        return route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({ results: [], permissions: PERMS }),
        });
      }
      posted = route.request().postData();
      return route.fulfill({
        status: 201,
        contentType: "application/json",
        body: JSON.stringify(caseRow()),
      });
    });

    await page.goto(`/regulatory-cases?tenant=${TENANT}`);
    await page.getByTestId("new-case").click();

    await page.getByTestId("case-title").fill("Stability data package");
    await page.getByTestId("case-product_name").fill("Synthetic Product X");
    await page.getByTestId("case-market").fill("Synthetic Market");
    await page.getByTestId("case-submission_type").fill("Synthetic Submission");
    await page.getByTestId("create-case-submit").click();

    await expect.poll(() => posted).toContain("Stability data package");
    await expect(page).toHaveURL(new RegExp(`/regulatory-cases/${CASE_ID}`));
  });

  test("submit stays disabled until the required fields are filled", async ({ page }) => {
    await mockCsrf(page);
    await mockList(page, []);
    await page.goto(`/regulatory-cases?tenant=${TENANT}`);
    await page.getByTestId("new-case").click();
    await expect(page.getByTestId("create-case-submit")).toBeDisabled();
    await page.getByTestId("case-title").fill("T");
    await page.getByTestId("case-product_name").fill("P");
    await page.getByTestId("case-market").fill("M");
    await page.getByTestId("case-submission_type").fill("S");
    await expect(page.getByTestId("create-case-submit")).toBeEnabled();
  });
});

test.describe("Regulatory case workspace", () => {
  test("opens a case and shows its header and counts", async ({ page }) => {
    await mockCsrf(page);
    await mockDetail(
      page,
      detail({
        summary: {
          documents: 2,
          workflows: 3,
          checklists: 1,
          workflows_open: 2,
          workflows_completed: 1,
          evidence_links: 5,
        },
      })
    );

    await page.goto(`/regulatory-cases/${CASE_ID}?tenant=${TENANT}`);

    await expect(page.getByText("RC-000001")).toBeVisible();
    await expect(page.getByRole("heading", { name: "Stability data package" })).toBeVisible();
    await expect(page.getByTestId("stat-documents")).toContainText("2");
    await expect(page.getByTestId("stat-evidence")).toContainText("5");
  });

  test("links a document and reloads the workspace", async ({ page }) => {
    await mockCsrf(page);
    let linked = false;
    await page.route(new RegExp(`/api/regx/v1/regulatory-cases/${CASE_ID}/documents/$`), async (route) => {
      if (route.request().method() === "POST") {
        linked = true;
        return route.fulfill({ status: 201, contentType: "application/json", body: "{}" });
      }
      return route.fulfill({ status: 200, contentType: "application/json", body: "[]" });
    });
    await mockDetail(page, detail());

    await page.goto(`/regulatory-cases/${CASE_ID}?tenant=${TENANT}`);
    await page.getByTestId("tab-documents").click();
    await page.getByTestId("link-target-input").fill("11111111-1111-1111-1111-111111111111");
    await page.getByTestId("link-submit").click();

    await expect.poll(() => linked).toBe(true);
  });

  test("a restricted link shows a marker and no resource detail", async ({ page }) => {
    await mockCsrf(page);
    await mockDetail(
      page,
      detail({
        documents: [
          {
            public_id: "link-1",
            label: "",
            linked_at: "2026-02-01T00:00:00Z",
            linked_by: { full_name: "Doer" },
            document_public_id: "doc-1",
            restricted: true,
          },
        ],
        summary: { ...detail().summary, documents: 1 },
      })
    );

    await page.goto(`/regulatory-cases/${CASE_ID}?tenant=${TENANT}`);
    await page.getByTestId("tab-documents").click();

    await expect(page.getByTestId("link-restricted")).toBeVisible();
    // Nothing that would identify the document is rendered.
    await expect(page.getByTestId("documents-table")).not.toContainText("Protocol");
  });

  test("completing a case removes the structural controls", async ({ page }) => {
    await mockCsrf(page);
    let completed = false;

    await page.route(new RegExp(`/api/regx/v1/regulatory-cases/${CASE_ID}/$`), async (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(
          completed
            ? detail({ case: caseRow({ status: "completed", is_terminal: true }) })
            : detail()
        ),
      })
    );
    await page.route(
      new RegExp(`/api/regx/v1/regulatory-cases/${CASE_ID}/complete/$`),
      async (route) => {
        completed = true;
        return route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify(caseRow({ status: "completed", is_terminal: true })),
        });
      }
    );

    await page.goto(`/regulatory-cases/${CASE_ID}?tenant=${TENANT}`);
    await page.getByTestId("complete-case").click();

    await expect(page.getByTestId("case-terminal-note")).toBeVisible();
    await expect(page.getByTestId("complete-case")).toHaveCount(0);

    // A completed case offers no way to change its structure.
    await page.getByTestId("tab-documents").click();
    await expect(page.getByTestId("link-form")).toHaveCount(0);
  });

  test("a completed case states it is not a regulatory approval", async ({ page }) => {
    await mockCsrf(page);
    await mockDetail(page, detail({ case: caseRow({ status: "completed", is_terminal: true }) }));
    await page.goto(`/regulatory-cases/${CASE_ID}?tenant=${TENANT}`);
    await expect(page.getByTestId("case-terminal-note")).toContainText(
      /not a regulatory approval/i
    );
  });

  test("a 409 surfaces and stays visible after the reload", async ({ page }) => {
    await mockCsrf(page);
    await mockDetail(page, detail());
    await page.route(
      new RegExp(`/api/regx/v1/regulatory-cases/${CASE_ID}/complete/$`),
      jsonRoute({ detail: "already completed", current_status: "completed" }, 409)
    );

    await page.goto(`/regulatory-cases/${CASE_ID}?tenant=${TENANT}`);
    await page.getByTestId("complete-case").click();

    // Not getByRole("alert"): Next.js injects its own route announcer, so the
    // role alone matches two elements and trips strict mode.
    await expect(page.getByTestId("case-error")).toContainText(/already been completed/i);
  });

  test("evidence is presented as belonging to workflows, not the case", async ({ page }) => {
    await mockCsrf(page);
    await mockDetail(page, detail());
    await page.goto(`/regulatory-cases/${CASE_ID}?tenant=${TENANT}`);
    await page.getByTestId("tab-evidence").click();
    await expect(page.getByTestId("tab-panel-evidence")).toContainText(
      /recorded against workflow items/i
    );
  });

  test("a missing case shows a not-found state", async ({ page }) => {
    await mockCsrf(page);
    await page.route(
      new RegExp(`/api/regx/v1/regulatory-cases/${CASE_ID}/$`),
      jsonRoute({ detail: "Case not found." }, 404)
    );
    await page.goto(`/regulatory-cases/${CASE_ID}?tenant=${TENANT}`);
    await expect(page.getByTestId("case-not-found")).toBeVisible();
  });
});
