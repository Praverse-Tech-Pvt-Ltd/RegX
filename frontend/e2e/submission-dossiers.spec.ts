import { test, expect, type Page, type Route } from "@playwright/test";

/**
 * Submission dossier workspace E2E.
 *
 * API responses are mocked with page.route, as every other spec here does, so
 * the test exercises the UI contract rather than a live backend.
 *
 * The property under test is that the UI renders what the API projects: a link
 * the server marked `restricted` shows a marker and no detail, a withheld count
 * renders as an em dash rather than zero, and a control the server withheld is
 * not offered. Hiding a control is presentation only -- the backend re-checks.
 */

const API = "http://localhost:8000";
const TENANT = "alpha";
const DOSSIER = "44444444-5555-6666-7777-888888888888";
const S1 = "11111111-1111-1111-1111-111111111111";
const S2 = "22222222-2222-2222-2222-222222222222";

const PERMS = {
  can_create: true,
  can_edit: true,
  can_manage_sections: true,
  can_manage_links: true,
  can_manage_blockers: true,
  can_complete: true,
  can_cancel: true,
};

function section(over: Record<string, unknown> = {}) {
  return {
    public_id: S1,
    parent_public_id: null,
    section_code: "1",
    title: "Quality overall summary",
    description: "Synthetic description",
    notes: "",
    sequence: 0,
    required: true,
    status: "not_started",
    readiness: "not_ready",
    readiness_reason: "no_supporting_work",
    owner: null,
    due_date: null,
    is_retired: false,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...over,
  };
}

function detail(over: Record<string, unknown> = {}) {
  return {
    dossier: {
      public_id: DOSSIER,
      regulatory_case_public_id: "case-1",
      title: "Initial submission",
      description: "",
      status: "open",
      owner: null,
      target_date: null,
      created_by: null,
      created_at: "2026-01-01T00:00:00Z",
      updated_at: "2026-01-01T00:00:00Z",
      is_terminal: false,
    },
    sections: [section()],
    summary: {
      total_sections: 1,
      required_sections: 1,
      ready: 0,
      partially_ready: 0,
      not_ready: 1,
      not_applicable: 0,
      open_blockers: 0,
      overall_readiness: "not_ready",
      overall_reason: "no_supporting_work",
    },
    module_counts: { workflow_evidence_links: 0 },
    permissions: PERMS,
    ...over,
  };
}

function sectionDetail(over: Record<string, unknown> = {}) {
  return {
    section: section(),
    children: [],
    documents: [],
    workflows: [],
    checklists: [],
    blockers: [],
    module_counts: { workflow_evidence_links: 0 },
    permissions: PERMS,
    ...over,
  };
}

function jsonRoute(body: unknown, status = 200) {
  return async (route: Route) =>
    route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
}

async function mockBase(page: Page, body: unknown, sectionBody?: unknown) {
  await page.route(`${API}/api/regx/v1/auth/csrf/`, jsonRoute({ csrfToken: "e2e" }));
  await page.route(new RegExp(`/api/regx/v1/submission-dossiers/${DOSSIER}/$`), jsonRoute(body));
  await page.route(
    /\/api\/regx\/v1\/dossier-sections\/[0-9a-f-]+\/$/,
    jsonRoute(sectionBody ?? sectionDetail())
  );
}

const URL_ = (id = DOSSIER) => `/submission-dossiers/${id}?tenant=${TENANT}`;

test.describe("Dossier workspace", () => {
  test("opens a dossier and shows internal readiness with counts", async ({ page }) => {
    await mockBase(page, detail());
    await page.goto(URL_());

    await expect(page.getByRole("heading", { name: "Initial submission" })).toBeVisible();
    await expect(page.getByText(/internal readiness/i)).toBeVisible();
    await expect(page.getByTestId("stat-total")).toContainText("1");
  });

  test("renders the outline as a tree with levels", async ({ page }) => {
    await mockBase(
      page,
      detail({
        sections: [
          section(),
          section({ public_id: S2, section_code: "1.1", title: "Child", parent_public_id: S1 }),
        ],
      })
    );
    await page.goto(URL_());

    const rows = page.getByTestId("section-row");
    await expect(rows).toHaveCount(2);
    await expect(rows.first()).toHaveAttribute("aria-level", "1");
    await expect(rows.nth(1)).toHaveAttribute("aria-level", "2");
  });

  test("collapsing a parent hides its children", async ({ page }) => {
    await mockBase(
      page,
      detail({
        sections: [
          section(),
          section({ public_id: S2, section_code: "1.1", title: "Child", parent_public_id: S1 }),
        ],
      })
    );
    await page.goto(URL_());
    await expect(page.getByTestId("section-row")).toHaveCount(2);

    await page.getByTestId(`toggle-${S1}`).click();
    await expect(page.getByTestId("section-row")).toHaveCount(1);
  });

  test("searching filters the outline", async ({ page }) => {
    await mockBase(
      page,
      detail({
        sections: [
          section(),
          section({ public_id: S2, section_code: "2", title: "Nonclinical", parent_public_id: null, sequence: 10 }),
        ],
      })
    );
    await page.goto(URL_());
    await page.getByTestId("section-search").fill("Nonclinical");
    await expect(page.getByTestId("section-row")).toHaveCount(1);
  });

  test("creates a section", async ({ page }) => {
    await mockBase(page, detail({ sections: [] }));
    let posted: string | null = null;
    await page.route(
      new RegExp(`/api/regx/v1/submission-dossiers/${DOSSIER}/sections/$`),
      async (route) => {
        posted = route.request().postData();
        return route.fulfill({
          status: 201,
          contentType: "application/json",
          body: JSON.stringify(section()),
        });
      }
    );

    await page.goto(URL_());
    await page.getByTestId("add-section").click();
    await page.getByTestId("new-section-code").fill("3.2.S.1");
    await page.getByTestId("new-section-title").fill("General information");
    await page.getByTestId("new-section-submit").click();

    await expect.poll(() => posted).toContain("3.2.S.1");
  });

  test("selecting a section opens its detail panel", async ({ page }) => {
    await mockBase(page, detail());
    await page.goto(URL_());
    await expect(page.getByTestId("section-panel-empty")).toBeVisible();

    await page.getByTestId(`select-${S1}`).click();
    await expect(page.getByTestId("section-panel")).toBeVisible();
  });

  test("a restricted linked resource shows a marker and no detail", async ({ page }) => {
    await mockBase(
      page,
      detail(),
      sectionDetail({
        documents: [
          {
            public_id: "link-1",
            purpose: "",
            linked_at: "2026-02-01T00:00:00Z",
            linked_by: null,
            document_public_id: "doc-1",
            restricted: true,
          },
        ],
      })
    );
    await page.goto(URL_());
    await page.getByTestId(`select-${S1}`).click();
    await page.getByTestId("section-tab-documents").click();

    await expect(page.getByTestId("link-restricted")).toContainText(/access restricted/i);
    // A real zero state would be a lie: the resource exists, it is just hidden.
    await expect(page.getByTestId("section-documents-empty")).toHaveCount(0);
  });

  test("a withheld module count renders as a dash, not zero", async ({ page }) => {
    await mockBase(page, detail({ module_counts: { workflow_evidence_links: null } }));
    await page.goto(URL_());
    const stat = page.getByTestId("stat-evidence");
    await expect(stat).toContainText("—");
    await expect(stat).not.toContainText("0");
  });

  test("links a document to a section", async ({ page }) => {
    await mockBase(page, detail());
    let linked = false;
    await page.route(/\/api\/regx\/v1\/dossier-sections\/[0-9a-f-]+\/documents\/$/, async (route) => {
      if (route.request().method() === "POST") {
        linked = true;
        return route.fulfill({ status: 201, contentType: "application/json", body: "{}" });
      }
      return route.fulfill({ status: 200, contentType: "application/json", body: "[]" });
    });

    await page.goto(URL_());
    await page.getByTestId(`select-${S1}`).click();
    await page.getByTestId("section-tab-documents").click();
    await page.getByTestId("section-link-input").fill("aaaaaaaa-1111-2222-3333-444444444444");
    await page.getByTestId("section-link-submit").click();

    await expect.poll(() => linked).toBe(true);
  });

  test("creates and resolves a blocker", async ({ page }) => {
    let created = false;
    let resolved = false;
    await mockBase(page, detail());
    await page.route(/\/api\/regx\/v1\/dossier-sections\/[0-9a-f-]+\/blockers\/$/, async (route) => {
      if (route.request().method() === "POST") {
        created = true;
        return route.fulfill({ status: 201, contentType: "application/json", body: "{}" });
      }
      return route.fulfill({ status: 200, contentType: "application/json", body: "[]" });
    });
    await page.route(/\/api\/regx\/v1\/section-blockers\/[0-9a-f-]+\/resolve\/$/, async (route) => {
      resolved = true;
      return route.fulfill({ status: 200, contentType: "application/json", body: "{}" });
    });

    await page.goto(URL_());
    await page.getByTestId(`select-${S1}`).click();
    await page.getByTestId("section-tab-blockers").click();
    await page.getByTestId("blocker-title-input").fill("Awaiting stability data");
    await page.getByTestId("blocker-submit").click();
    await expect.poll(() => created).toBe(true);

    // Now render one open blocker and resolve it.
    await page.route(
      /\/api\/regx\/v1\/dossier-sections\/[0-9a-f-]+\/$/,
      jsonRoute(
        sectionDetail({
          blockers: [
            {
              public_id: "b-1",
              section_public_id: S1,
              title: "Awaiting stability data",
              description: "",
              severity: "medium",
              status: "open",
              created_by: null,
              created_at: "2026-02-01T00:00:00Z",
              resolved_by: null,
              resolved_at: null,
            },
          ],
        })
      )
    );
    await page.reload();
    await page.getByTestId(`select-${S1}`).click();
    await page.getByTestId("section-tab-blockers").click();
    await page.getByTestId("resolve-b-1").click();
    await expect.poll(() => resolved).toBe(true);
  });

  test("marks a section complete", async ({ page }) => {
    await mockBase(page, detail());
    let patched: string | null = null;
    await page.route(/\/api\/regx\/v1\/dossier-sections\/[0-9a-f-]+\/$/, async (route) => {
      if (route.request().method() === "PATCH") {
        patched = route.request().postData();
        return route.fulfill({ status: 200, contentType: "application/json", body: "{}" });
      }
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(sectionDetail()),
      });
    });

    await page.goto(URL_());
    await page.getByTestId(`select-${S1}`).click();
    await page.getByTestId("mark-complete").click();
    await expect.poll(() => patched).toContain("complete");
  });

  test("readiness updates are reflected from the server, not computed locally", async ({ page }) => {
    await mockBase(
      page,
      detail({
        sections: [section({ status: "complete", readiness: "ready", readiness_reason: "ready" })],
        summary: { ...detail().summary, ready: 1, not_ready: 0, overall_readiness: "ready" },
      })
    );
    await page.goto(URL_());
    await expect(page.getByTestId("readiness-badge").first()).toHaveAttribute(
      "data-readiness",
      "ready"
    );
  });

  test("a terminal dossier blocks structural mutation and says it is not an approval", async ({
    page,
  }) => {
    await mockBase(
      page,
      detail({ dossier: { ...detail().dossier, status: "completed", is_terminal: true } })
    );
    await page.goto(URL_());

    await expect(page.getByTestId("dossier-terminal-note")).toContainText(
      /not a regulatory approval/i
    );
    await expect(page.getByTestId("add-section")).toHaveCount(0);
    await expect(page.getByTestId("complete-dossier")).toHaveCount(0);
  });

  test("completion refused while not ready surfaces a safe message", async ({ page }) => {
    await mockBase(page, detail());
    await page.route(
      new RegExp(`/api/regx/v1/submission-dossiers/${DOSSIER}/complete/$`),
      jsonRoute({ detail: "Required sections are not internally ready.", reason_code: "section_not_complete" }, 409)
    );

    await page.goto(URL_());
    await page.getByTestId("complete-dossier").click();

    // Not getByRole("alert"): Next.js injects its own route announcer, so the
    // role alone matches two elements and trips strict mode.
    await expect(page.getByTestId("dossier-error")).toContainText(/not internally ready/i);
  });

  test("a missing dossier shows a not-found state", async ({ page }) => {
    await page.route(`${API}/api/regx/v1/auth/csrf/`, jsonRoute({ csrfToken: "e2e" }));
    await page.route(
      new RegExp(`/api/regx/v1/submission-dossiers/${DOSSIER}/$`),
      jsonRoute({ detail: "Dossier not found." }, 404)
    );
    await page.goto(URL_());
    await expect(page.getByTestId("dossier-not-found")).toBeVisible();
  });

  test("controls the API withholds are not offered", async ({ page }) => {
    await mockBase(
      page,
      detail({
        permissions: { ...PERMS, can_manage_sections: false, can_complete: false, can_cancel: false },
      })
    );
    await page.goto(URL_());
    await expect(page.getByTestId("add-section")).toHaveCount(0);
    await expect(page.getByTestId("complete-dossier")).toHaveCount(0);
    await expect(page.getByTestId("cancel-dossier")).toHaveCount(0);
  });
});
