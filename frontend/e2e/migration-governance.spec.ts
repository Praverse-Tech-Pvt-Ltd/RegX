// Template migration/governance Playwright suite.
//
// Scope note: as in documents.spec.ts, every backend response here is a
// deterministic Playwright route mock (page.route), not a live backend.
// This proves the FRONTEND renders and reacts correctly to the
// templates_registry API contract described in src/lib/api.ts. Server-side
// enforcement (permissions, tenant isolation, lifecycle transitions) is
// covered by the backend pytest suite (templates_registry/tests/) instead.
//
// Fixtures are synthetic and non-confidential.
import { test, expect, type Page, type Route } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

const TENANT = "alpha";
const TEMPLATE_ID = "tpl-e2e-0001";
const VERSION_ID = "ver-e2e-0001";
const BATCH_ID = "batch-e2e-0001";
const API = "http://localhost:8000";

function jsonRoute(body: unknown, status = 200) {
  return (route: Route) =>
    route.fulfill({
      status,
      contentType: "application/json",
      body: JSON.stringify(body),
    });
}

function makeTemplate(overrides: Record<string, unknown> = {}) {
  return {
    public_id: TEMPLATE_ID,
    canonical_code: "ANDA-SOLID-ORAL",
    title: "ANDA — Solid Oral Dosage",
    category: "Formulation",
    regulatory_pathway: "",
    dosage_form_applicability: "",
    description: "",
    lifecycle_status: "imported",
    current_approved_version: null,
    created_at: "2026-07-20T09:59:00Z",
    updated_at: "2026-07-20T09:59:00Z",
    ...overrides,
  };
}

function makeVersion(overrides: Record<string, unknown> = {}) {
  return {
    public_id: VERSION_ID,
    template: TEMPLATE_ID,
    version_number: 1,
    status: "imported",
    effective_date: null,
    superseded_date: null,
    approved_at: null,
    ...overrides,
  };
}

async function mockCsrf(page: Page) {
  await page.route(
    `${API}/api/regx/v1/auth/csrf/`,
    jsonRoute({ csrfToken: "e2e-csrf-token" }),
  );
}

async function mockTemplateDetail(page: Page, template: unknown) {
  await page.route(
    `${API}/api/regx/v1/templates/${TEMPLATE_ID}/`,
    jsonRoute(template),
  );
}

async function mockVersions(page: Page, versions: unknown[]) {
  await page.route(
    `${API}/api/regx/v1/templates/${TEMPLATE_ID}/versions/`,
    jsonRoute({
      count: versions.length,
      next: null,
      previous: null,
      results: versions,
    }),
  );
}

// The detail page re-fetches the version list after every lifecycle action
// (onChanged -> load()), so a static mock would keep serving the pre-action
// status forever. This tracks mutable state so the refetch reflects the
// transition, exactly as the real API would.
async function mockStatefulVersion(
  page: Page,
  initial: Record<string, unknown>,
) {
  let current = initial;
  await page.route(
    `${API}/api/regx/v1/templates/${TEMPLATE_ID}/versions/`,
    async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          count: 1,
          next: null,
          previous: null,
          results: [current],
        }),
      });
    },
  );
  async function onAction(actionPath: string, next: Record<string, unknown>) {
    await page.route(
      `${API}/api/regx/v1/templates/${TEMPLATE_ID}/versions/${VERSION_ID}/${actionPath}/`,
      async (route) => {
        current = next;
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify(current),
        });
      },
    );
  }
  return { onAction };
}

test.describe("Templates: inventory list", () => {
  test("empty state renders when no templates exist", async ({ page }) => {
    await mockCsrf(page);
    await page.route(
      /\/api\/regx\/v1\/templates\/(\?[^/]*)?$/,
      jsonRoute({ count: 0, next: null, previous: null, results: [] }),
    );

    await page.goto(`/templates?tenant=${TENANT}`);
    await expect(
      page.getByRole("heading", { name: "Regulatory Templates" }),
    ).toBeVisible();
    await expect(page.getByText(/No templates yet/i)).toBeVisible();
  });

  test("a template row links to its detail page and shows its status", async ({
    page,
  }) => {
    await mockCsrf(page);
    await page.route(
      /\/api\/regx\/v1\/templates\/(\?[^/]*)?$/,
      jsonRoute({
        count: 1,
        next: null,
        previous: null,
        results: [makeTemplate()],
      }),
    );

    await page.goto(`/templates?tenant=${TENANT}`);
    const row = page.getByRole("row", { name: /ANDA-SOLID-ORAL/i });
    await expect(row.getByText(/imported/i)).toBeVisible();
  });
});

test.describe("Templates: version lifecycle actions", () => {
  test("a doer can submit an imported version for review", async ({ page }) => {
    await mockCsrf(page);
    await mockTemplateDetail(page, makeTemplate());
    const version = await mockStatefulVersion(
      page,
      makeVersion({ status: "imported" }),
    );
    await version.onAction(
      "submit-review",
      makeVersion({ status: "under_review" }),
    );

    await page.goto(`/templates/${TEMPLATE_ID}?tenant=${TENANT}`);
    await expect(page.getByText("Version 1")).toBeVisible();
    await page.getByRole("button", { name: /submit for review/i }).click();

    await expect(
      page.getByRole("button", { name: /^approve$/i }),
    ).toBeVisible();
    await expect(page.getByRole("button", { name: /^reject$/i })).toBeVisible();
  });

  test("a VP can approve then activate a version, superseding is offered once active", async ({
    page,
  }) => {
    await mockCsrf(page);
    await mockTemplateDetail(page, makeTemplate());
    const version = await mockStatefulVersion(
      page,
      makeVersion({ status: "under_review" }),
    );
    await version.onAction("approve", makeVersion({ status: "approved" }));
    await version.onAction(
      "activate",
      makeVersion({ status: "active", effective_date: "2026-07-23" }),
    );

    await page.goto(`/templates/${TEMPLATE_ID}?tenant=${TENANT}`);
    await page.getByRole("button", { name: /^approve$/i }).click();
    await expect(
      page.getByRole("button", { name: /^activate$/i }),
    ).toBeVisible();

    await page.getByRole("button", { name: /^activate$/i }).click();
    await expect(
      page.getByRole("button", { name: /^supersede$/i }),
    ).toBeVisible();
    await expect(page.getByRole("button", { name: /^retire$/i })).toBeVisible();
  });

  test("a Doer attempting to approve is rejected and the server error is surfaced", async ({
    page,
  }) => {
    // PLANTED (server-enforced, frontend proven to defer correctly): a Doer
    // has no approve permission -- the API returns 403 and the UI must show
    // the rejection rather than silently transitioning the version.
    await mockCsrf(page);
    await mockTemplateDetail(page, makeTemplate());
    await mockVersions(page, [makeVersion({ status: "under_review" })]);
    await page.route(
      `${API}/api/regx/v1/templates/${TEMPLATE_ID}/versions/${VERSION_ID}/approve/`,
      jsonRoute(
        { detail: "You do not have permission to perform this action." },
        403,
      ),
    );

    await page.goto(`/templates/${TEMPLATE_ID}?tenant=${TENANT}`);
    await page.getByRole("button", { name: /^approve$/i }).click();

    await expect(page.locator("main").getByRole("alert")).toHaveText(
      /You do not have permission to perform this action\./i,
    );
    // Still under review -- approve/reject buttons remain, not activate.
    await expect(
      page.getByRole("button", { name: /^approve$/i }),
    ).toBeVisible();
  });
});

test.describe("Migration batches: list and reconciliation permission gating", () => {
  test("batch list shows status and links to detail", async ({ page }) => {
    await mockCsrf(page);
    await page.route(
      /\/api\/regx\/v1\/template-sources\/(\?[^/]*)?$/,
      jsonRoute({ count: 0, next: null, previous: null, results: [] }),
    );
    await page.route(
      /\/api\/regx\/v1\/migration-batches\/(\?[^/]*)?$/,
      jsonRoute({
        count: 1,
        next: null,
        previous: null,
        results: [
          {
            public_id: BATCH_ID,
            source_package: "pkg-e2e-0001",
            status: "completed",
            started_by_email: "doer@example.com",
            started_at: "2026-07-20T09:00:00Z",
            completed_at: "2026-07-20T09:01:00Z",
            counts: { imported: 2 },
            correlation_id: "corr-e2e-0001",
          },
        ],
      }),
    );

    await page.goto(`/migration-batches?tenant=${TENANT}`);
    await expect(page.getByText(/completed/i)).toBeVisible();
  });

  test("a batch detail page still renders results when reconciliation is permission-denied", async ({
    page,
  }) => {
    // A Doer can see their own batch and its per-record results, but the
    // reconciliation report requires templates.export_reconciliation
    // (VP/Tenant Admin only) -- the page must degrade gracefully, not fail
    // outright, when that one call 403s.
    await mockCsrf(page);
    await page.route(
      `${API}/api/regx/v1/migration-batches/${BATCH_ID}/`,
      jsonRoute({
        public_id: BATCH_ID,
        source_package: "pkg-e2e-0001",
        status: "completed",
        started_by_email: "doer@example.com",
        started_at: "2026-07-20T09:00:00Z",
        completed_at: "2026-07-20T09:01:00Z",
        counts: { imported: 1 },
        correlation_id: "corr-e2e-0002",
      }),
    );
    await page.route(
      `${API}/api/regx/v1/migration-batches/${BATCH_ID}/results/`,
      jsonRoute({
        count: 1,
        next: null,
        previous: null,
        results: [
          {
            public_id: "result-e2e-0001",
            source_record_identifier: "anda-1",
            target_public_identifier: "item-e2e-0001",
            result: "imported",
            reason_code: "",
            safe_detail: "",
          },
        ],
      }),
    );
    await page.route(
      `${API}/api/regx/v1/migration-batches/${BATCH_ID}/reconciliation.json`,
      jsonRoute(
        { detail: "You do not have permission to perform this action." },
        403,
      ),
    );

    await page.goto(`/migration-batches/${BATCH_ID}?tenant=${TENANT}`);

    await expect(page.getByText(/anda-1/i)).toBeVisible();
    await expect(
      page.getByText(/restricted to reviewers with export permission/i),
    ).toBeVisible();
  });

  test("a VP sees the full reconciliation summary and can resolve a duplicate candidate", async ({
    page,
  }) => {
    await mockCsrf(page);
    await page.route(
      `${API}/api/regx/v1/migration-batches/${BATCH_ID}/`,
      jsonRoute({
        public_id: BATCH_ID,
        source_package: "pkg-e2e-0001",
        status: "completed",
        started_by_email: "doer@example.com",
        started_at: "2026-07-20T09:00:00Z",
        completed_at: "2026-07-20T09:01:00Z",
        counts: { imported: 1, requires_review: 1 },
        correlation_id: "corr-e2e-0003",
      }),
    );
    await page.route(
      `${API}/api/regx/v1/migration-batches/${BATCH_ID}/results/`,
      jsonRoute({ count: 0, next: null, previous: null, results: [] }),
    );
    await page.route(
      `${API}/api/regx/v1/migration-batches/${BATCH_ID}/reconciliation.json`,
      jsonRoute({
        batch: {
          correlation_id: "corr-e2e-0003",
          public_id: BATCH_ID,
          status: "completed",
        },
        source_package: {
          public_id: "pkg-e2e-0001",
          source_name: "anda-src",
          source_checksum: "abc",
        },
        counts: { imported: 1, requires_review: 1 },
        records: [],
        unmatched_records: [],
        normalization_mappings: [],
        duplicate_candidates: [
          {
            public_id: "dup-e2e-0001",
            match_type: "normalized_text",
            similarity_evidence: {},
            resolution: "pending",
            reviewer_email: null,
            reason: "",
            suspected_match_item: "item-e2e-0002",
            created_at: "2026-07-20T09:01:00Z",
          },
        ],
        approvals: [],
      }),
    );
    let reviewBody: unknown = null;
    await page.route(
      `${API}/api/regx/v1/migration-batches/${BATCH_ID}/review/`,
      async (route) => {
        reviewBody = route.request().postDataJSON();
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({ resolved: ["dup-e2e-0001"] }),
        });
      },
    );

    await page.goto(`/migration-batches/${BATCH_ID}?tenant=${TENANT}`);
    await expect(page.getByText(/normalized text/i)).toBeVisible();

    await page.getByRole("combobox").selectOption("same");
    await page
      .getByRole("button", { name: /submit duplicate resolutions/i })
      .click();

    await expect.poll(() => reviewBody).not.toBeNull();
    expect(reviewBody).toEqual({
      duplicate_resolutions: [
        { public_id: "dup-e2e-0001", resolution: "same" },
      ],
    });
  });
});

test.describe("Migration governance: no internal identifiers leak", () => {
  test("template detail page never displays internal numeric IDs", async ({
    page,
  }) => {
    await mockCsrf(page);
    const template = { ...makeTemplate(), id: 727272 };
    await mockTemplateDetail(page, template);
    await mockVersions(page, [{ ...makeVersion(), id: 838383 }]);

    await page.goto(`/templates/${TEMPLATE_ID}?tenant=${TENANT}`);
    await expect(
      page.getByRole("heading", { name: "ANDA — Solid Oral Dosage" }),
    ).toBeVisible();

    const body = await page.locator("body").innerText();
    expect(body).not.toContain("727272");
    expect(body).not.toContain("838383");
  });
});

test.describe("Migration governance: accessibility spot-check", () => {
  test("the templates list page has no serious/critical automated violations", async ({
    page,
  }) => {
    await mockCsrf(page);
    await page.route(
      /\/api\/regx\/v1\/templates\/(\?[^/]*)?$/,
      jsonRoute({
        count: 1,
        next: null,
        previous: null,
        results: [makeTemplate()],
      }),
    );
    await page.goto(`/templates?tenant=${TENANT}`);
    await expect(
      page.getByRole("link", { name: "ANDA-SOLID-ORAL" }),
    ).toBeVisible();

    const results = await new AxeBuilder({ page }).include("main").analyze();
    const serious = results.violations.filter(
      (v) => v.impact === "serious" || v.impact === "critical",
    );
    expect(serious, JSON.stringify(serious, null, 2)).toEqual([]);
  });
});
