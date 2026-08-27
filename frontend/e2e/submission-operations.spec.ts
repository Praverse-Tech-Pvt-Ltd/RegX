import { test, expect, type Page, type Route } from "@playwright/test";

/**
 * Submission operations dashboard E2E.
 *
 * API responses are mocked with page.route, as every other spec here does, so
 * the test exercises the UI contract rather than a live backend.
 *
 * Two properties are under test end to end:
 *   - a restricted dimension renders "Unavailable", never `0`, and a hidden
 *     module contributes no link and no row;
 *   - the dashboard reflects the server's state, so resolving a blocker or
 *     completing work changes what the screen says on the next load.
 */

const API = "http://localhost:8000";
const TENANT = "alpha";
const DOSSIER = "11111111-2222-3333-4444-555555555555";
const CASE = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee";

const FULL_OVERVIEW = {
  cases: { open: 2, on_hold: 1, completed: 0, cancelled: 0 },
  dossiers: { open: 3, on_hold: 0, completed: 1, cancelled: 0 },
  sections: {
    required_total: 10,
    required_complete: 4,
    required_blocked: 2,
    required_overdue: 3,
    required_due_soon: 1,
    required_not_started: 5,
  },
  blockers: { open: 2 },
  workflows: { waiting_review: 1, rejected: 1, overdue: 0 },
  documents: { linked: 12 },
  checklists: { incomplete: 0 },
  upgrades: { open: 2, blocked: 1, stale: 1 },
  restricted_modules: [],
  due_soon_days: 7,
  generated_at: "2026-08-27T00:00:00Z",
  semantics: "internal_operational",
};

function attentionRow(over: Record<string, unknown> = {}) {
  return {
    reason_code: "required_section_blocked",
    severity: "blocked",
    resource_type: "dossier_section",
    resource_public_id: "sec-1",
    resource_label: "A.1",
    case_public_id: CASE,
    dossier_public_id: DOSSIER,
    due_date: null,
    operational_state: "blocked",
    ...over,
  };
}

function caseRow(over: Record<string, unknown> = {}) {
  return {
    public_id: CASE,
    case_number: "C-001",
    title: "Synthetic case",
    status: "open",
    target_date: null,
    owner: null,
    last_activity_at: "2026-08-27T00:00:00Z",
    dossiers: { total: 1, open: 1 },
    sections: {
      required_total: 4,
      required_complete: 1,
      blocked: 1,
      overdue: 2,
      due_soon: 0,
    },
    open_blockers: 1,
    internal_readiness: "internally_not_ready",
    workflow_attention: 0,
    upgrade_attention: 0,
    ...over,
  };
}

function dossierRow(over: Record<string, unknown> = {}) {
  return {
    public_id: DOSSIER,
    title: "Synthetic dossier",
    status: "open",
    case_public_id: CASE,
    case_number: "C-001",
    internal_readiness: "internally_not_ready",
    required_total: 4,
    required_complete: 1,
    blocked_sections: 1,
    overdue_sections: 2,
    due_soon_sections: 0,
    open_blockers: 1,
    target_date: null,
    owner: null,
    last_activity_at: "2026-08-27T00:00:00Z",
    upgrade: { open: 1, blocked: 0, stale: 1 },
    ...over,
  };
}

async function json(route: Route, body: unknown, status = 200) {
  await route.fulfill({
    status,
    contentType: "application/json",
    body: JSON.stringify(body),
  });
}

async function stubAuth(page: Page) {
  await page.route(`${API}/api/regx/v1/auth/session/`, (r) =>
    json(r, { user: { public_id: "u1", email: "a@example.test", full_name: "Author" } })
  );
  await page.route(`${API}/api/regx/v1/auth/csrf/`, (r) => json(r, { csrfToken: "e2e" }));
  await page.route(`${API}/api/regx/v1/tenants/**`, (r) =>
    json(r, { results: [{ public_id: "t1", name: "Alpha", slug: TENANT }] })
  );
}

async function stubOps(
  page: Page,
  {
    overview = FULL_OVERVIEW,
    attention = [attentionRow()],
    cases = { count: 1, results: [caseRow()] },
    dossiers = { count: 1, results: [dossierRow()] },
    owners = { count: 0, results: [] },
    activity = { count: 0, results: [] },
    truncated = false,
  }: Record<string, unknown> = {}
) {
  await stubAuth(page);
  const base = `${API}/api/regx/v1/submission-operations`;
  await page.route(new RegExp(`/submission-operations/overview/`), (r) => json(r, overview));
  await page.route(new RegExp(`/submission-operations/attention/`), (r) =>
    json(r, { count: (attention as unknown[]).length, results: attention, truncated })
  );
  await page.route(new RegExp(`/submission-operations/cases/`), (r) => json(r, cases));
  await page.route(new RegExp(`/submission-operations/dossiers/`), (r) => json(r, dossiers));
  await page.route(new RegExp(`/submission-operations/owners/`), (r) => json(r, owners));
  await page.route(new RegExp(`/submission-operations/recent-activity/`), (r) =>
    json(r, activity)
  );
  return base;
}

const URL = `/submission-operations?tenant=${TENANT}`;

test.describe("Submission operations dashboard", () => {
  test("shows the operational summary and the internal-only disclaimer", async ({ page }) => {
    await stubOps(page);
    await page.goto(URL);

    await expect(page.getByTestId("card-open-cases")).toContainText("2");
    await expect(page.getByTestId("card-blocked-sections")).toContainText("2");
    await expect(page.getByTestId("card-overdue-sections")).toContainText("3");
    await expect(page.getByTestId("internal-only-note")).toContainText(
      "internal RegX operational status only"
    );
  });

  test("never claims agency, regulatory or filing status anywhere on the page", async ({
    page,
  }) => {
    await stubOps(page);
    await page.goto(URL);
    await expect(page.getByTestId("summary-cards")).toBeVisible();

    const body = (await page.locator("main").innerText()).toLowerCase();
    for (const banned of [
      "submission ready",
      "agency ready",
      "regulatory compliant",
      "filing ready",
      "fda ready",
      "ema ready",
    ]) {
      expect(body).not.toContain(banned);
    }
    // "Ready" only ever appears qualified as internal.
    expect(body).toContain("internally");
  });

  test("orders the attention queue by severity", async ({ page }) => {
    await stubOps(page, {
      attention: [
        attentionRow({ resource_public_id: "s1", resource_label: "A.1", severity: "blocked" }),
        attentionRow({
          resource_public_id: "s2",
          resource_label: "A.2",
          severity: "overdue",
          reason_code: "overdue_required_section",
          due_date: "2026-08-01",
        }),
        attentionRow({
          resource_public_id: "s3",
          resource_label: "A.3",
          severity: "attention",
          reason_code: "due_soon_required_section",
          due_date: "2026-08-30",
        }),
        attentionRow({
          resource_public_id: "s4",
          resource_label: "A.4",
          severity: "informational",
          reason_code: "stale_upgrade_plan",
        }),
      ],
    });
    await page.goto(URL);

    const badges = page.getByTestId("attention-rows").getByTestId("severity-badge");
    await expect(badges).toHaveCount(4);
    await expect(badges.nth(0)).toHaveAttribute("data-severity", "blocked");
    await expect(badges.nth(1)).toHaveAttribute("data-severity", "overdue");
    await expect(badges.nth(2)).toHaveAttribute("data-severity", "attention");
    await expect(badges.nth(3)).toHaveAttribute("data-severity", "informational");
  });

  test("severity is readable as text, not colour alone", async ({ page }) => {
    await stubOps(page);
    await page.goto(URL);
    const badge = page.getByTestId("attention-rows").getByTestId("severity-badge").first();
    await expect(badge).toHaveText(/\S/);
    await expect(badge).toContainText("Blocked");
  });

  test("a restricted module reads Unavailable and never zero", async ({ page }) => {
    await stubOps(page, {
      overview: {
        ...FULL_OVERVIEW,
        documents: null,
        workflows: null,
        upgrades: null,
        restricted_modules: ["documents", "workflows", "upgrades"],
      },
    });
    await page.goto(URL);

    const waiting = page.getByTestId("card-waiting-review");
    await expect(waiting).toHaveAttribute("data-restricted", "true");
    await expect(waiting).toContainText("Unavailable");
    await expect(waiting).not.toContainText(/\b0\b/);

    const stale = page.getByTestId("card-stale-upgrades");
    await expect(stale).toContainText("Unavailable");
  });

  test("a permitted module with nothing in it shows zero, not Unavailable", async ({ page }) => {
    await stubOps(page, {
      overview: {
        ...FULL_OVERVIEW,
        workflows: { waiting_review: 0, rejected: 0, overdue: 0 },
      },
    });
    await page.goto(URL);
    const waiting = page.getByTestId("card-waiting-review");
    await expect(waiting).toHaveAttribute("data-restricted", "false");
    await expect(waiting).toContainText("0");
    await expect(waiting).not.toContainText("Unavailable");
  });

  test("a hidden module contributes no attention row at all", async ({ page }) => {
    // The server withholds workflow rows entirely; the screen must not hint at
    // how many were withheld.
    await stubOps(page, { attention: [attentionRow()] });
    await page.goto(URL);

    const rows = page.getByTestId("attention-rows");
    await expect(rows).toBeVisible();
    const text = (await rows.innerText()).toLowerCase();
    expect(text).not.toContain("hidden");
    expect(text).not.toContain("withheld");
    expect(text).not.toContain("workflow");
  });

  test("case and dossier rows link to their detail pages", async ({ page }) => {
    await stubOps(page);
    await page.goto(URL);

    await expect(page.getByTestId("case-link").first()).toHaveAttribute(
      "href",
      new RegExp(`/regulatory-cases/${CASE}`)
    );
    await page.getByTestId("tab-dossiers").click();
    await expect(page.getByTestId("dossier-link").first()).toHaveAttribute(
      "href",
      new RegExp(`/submission-dossiers/${DOSSIER}`)
    );
  });

  test("an empty case list and a restricted one are different states", async ({ page }) => {
    await stubOps(page, { cases: { count: 0, results: [] } });
    await page.goto(URL);
    await expect(page.getByTestId("cases-empty")).toHaveAttribute("data-restricted", "false");
    await expect(page.getByTestId("cases-empty")).toContainText("No cases yet.");

    await page.unrouteAll({ behavior: "ignoreErrors" });
    await stubOps(page, { cases: { results: null, count: null, restricted: true } });
    await page.reload();
    await expect(page.getByTestId("cases-empty")).toHaveAttribute("data-restricted", "true");
    await expect(page.getByTestId("cases-empty")).toContainText(/permission to view cases/i);
  });

  test("resolving the blocker changes what the dashboard says", async ({ page }) => {
    await stubOps(page);
    await page.goto(URL);
    await expect(page.getByTestId("card-open-blockers")).toContainText("2");
    await expect(
      page.getByTestId("attention-rows").getByTestId("severity-badge")
    ).toHaveCount(1);

    // The blocker is resolved server-side; the next load reflects it.
    await page.unrouteAll({ behavior: "ignoreErrors" });
    await stubOps(page, {
      overview: {
        ...FULL_OVERVIEW,
        blockers: { open: 0 },
        sections: { ...FULL_OVERVIEW.sections, required_blocked: 0 },
      },
      attention: [],
    });
    await page.reload();

    await expect(page.getByTestId("card-open-blockers")).toContainText("0");
    await expect(page.getByTestId("card-blocked-sections")).toContainText("0");
    await expect(page.getByTestId("attention-empty")).toContainText(/Nothing currently needs/i);
  });

  test("completing the work moves the dossier to internally ready", async ({ page }) => {
    await stubOps(page);
    await page.goto(URL);
    await page.getByTestId("tab-dossiers").click();
    await expect(
      page.getByTestId("dossier-rows").getByTestId("internal-readiness")
    ).toHaveAttribute("data-value", "internally_not_ready");

    await page.unrouteAll({ behavior: "ignoreErrors" });
    await stubOps(page, {
      dossiers: {
        count: 1,
        results: [
          dossierRow({
            internal_readiness: "internally_ready",
            required_complete: 4,
            blocked_sections: 0,
            overdue_sections: 0,
            open_blockers: 0,
          }),
        ],
      },
    });
    await page.reload();
    await page.getByTestId("tab-dossiers").click();

    const badge = page.getByTestId("dossier-rows").getByTestId("internal-readiness");
    await expect(badge).toHaveAttribute("data-value", "internally_ready");
    await expect(badge).toContainText("Internally ready");
  });

  test("the severity filter re-queries the server", async ({ page }) => {
    await stubOps(page);
    const requests: string[] = [];
    page.on("request", (r) => {
      if (r.url().includes("/submission-operations/attention/")) requests.push(r.url());
    });
    await page.goto(URL);
    await expect(page.getByTestId("attention-rows")).toBeVisible();

    await page.getByTestId("severity-filter").selectOption("blocked");
    await expect.poll(() => requests.some((u) => u.includes("severity=blocked"))).toBe(true);
  });

  test("switches between detail panels", async ({ page }) => {
    await stubOps(page, {
      owners: {
        count: 1,
        results: [
          {
            owner: { public_id: "u1", full_name: "Ana Doer" },
            unassigned: false,
            required_total: 3,
            outstanding: 2,
            blocked: 1,
            overdue: 1,
          },
        ],
      },
    });
    await page.goto(URL);

    await page.getByTestId("tab-owners").click();
    await expect(page.getByTestId("owner-rows")).toContainText("Ana Doer");
    await expect(page.getByTestId("tab-owners")).toHaveAttribute("aria-selected", "true");

    await page.getByTestId("tab-activity").click();
    await expect(page.getByTestId("activity-empty")).toBeVisible();
  });

  test("warns when the queue was truncated", async ({ page }) => {
    await stubOps(page, { truncated: true });
    await page.goto(URL);
    await expect(page.getByTestId("attention-truncated")).toContainText(/more exist/i);
  });

  test("tables stay usable at tablet width", async ({ page }) => {
    await stubOps(page);
    await page.setViewportSize({ width: 820, height: 900 });
    await page.goto(URL);

    await expect(page.getByRole("region", { name: "Attention queue table" })).toBeVisible();
    // The page itself must not scroll sideways; the table region does.
    const doc = await page.evaluate(() => ({
      scrollWidth: document.documentElement.scrollWidth,
      clientWidth: document.documentElement.clientWidth,
    }));
    expect(doc.scrollWidth).toBeLessThanOrEqual(doc.clientWidth + 1);
  });

  test("surfaces a failure as an alert rather than an empty screen", async ({ page }) => {
    await stubAuth(page);
    // Every endpoint routed explicitly rather than leaning on which of two
    // overlapping patterns wins -- a catch-all plus a more specific route is a
    // precedence question the test should not be asking.
    for (const path of ["attention", "cases", "dossiers", "owners", "recent-activity"]) {
      await page.route(new RegExp(`/submission-operations/${path}/`), (r) =>
        json(r, { count: 0, results: [], truncated: false })
      );
    }
    await page.route(new RegExp(`/submission-operations/overview/`), (r) =>
      json(r, { detail: "boom" }, 500)
    );
    await page.goto(URL);
    await expect(page.getByTestId("ops-error")).toBeVisible();
  });
});
