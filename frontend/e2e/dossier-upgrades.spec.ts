import { test, expect, type Page, type Route } from "@playwright/test";

/**
 * Blueprint upgrade E2E.
 *
 * API responses are mocked with page.route, as every other spec here does, so
 * the test exercises the UI contract rather than a live backend.
 *
 * The property under test is that **nothing applies until the user says so**:
 * generating shows a diff and changes nothing, accepting records a decision and
 * changes nothing, and Apply asks for confirmation before it sends anything.
 * The dossier's own section list is served separately and only changes when the
 * server says it did.
 */

const API = "http://localhost:8000";
const TENANT = "alpha";
const DOSSIER = "11111111-2222-3333-4444-555555555555";
const PLAN = "66666666-7777-8888-9999-000000000000";

const DOSSIER_PERMS = {
  can_create: true,
  can_edit: true,
  can_manage_sections: true,
  can_manage_links: true,
  can_manage_blockers: true,
  can_complete: true,
  can_cancel: true,
};

const UPGRADE_PERMS = {
  can_view: true,
  can_generate: true,
  can_review: true,
  can_apply: true,
  can_cancel: true,
};

function dossierSection(over: Record<string, unknown> = {}) {
  return {
    public_id: "sec-a",
    parent_public_id: null,
    section_code: "A",
    title: "Section A",
    description: "",
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

function planItem(over: Record<string, unknown> = {}) {
  return {
    public_id: "item-title",
    change_type: "update_title",
    status: "proposed",
    section_code: "A",
    field_name: "title",
    before_value: "Section A",
    after_value: "Section A, revised",
    blocking_reason: "",
    requires_manual_review: false,
    dossier_section_public_id: "sec-a",
    target_section_public_id: "bp-a",
    sequence: 0,
    ...over,
  };
}

function planSummary(over: Record<string, unknown> = {}) {
  return {
    public_id: PLAN,
    dossier_public_id: DOSSIER,
    status: "draft",
    notes: "",
    is_stale: false,
    source_version: { public_id: "v1", version_number: 1, status: "retired" },
    target_version: { public_id: "v2", version_number: 2, status: "active" },
    total_items: 2,
    actionable_items: 2,
    conflict_items: 0,
    accepted_items: 0,
    rejected_items: 0,
    blocked_items: 0,
    created_by: { public_id: "u1", full_name: "Author" },
    created_at: "2026-01-01T00:00:00Z",
    reviewed_at: null,
    applied_at: null,
    cancelled_at: null,
    ...over,
  };
}

async function json(route: Route, body: unknown, status = 200) {
  await route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
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

/** The dossier itself, which the upgrade panel never writes to directly. */
async function stubDossier(page: Page, sections = [dossierSection()]) {
  await page.route(new RegExp(`/api/regx/v1/submission-dossiers/${DOSSIER}/$`), (r) =>
    json(r, {
      dossier: {
        public_id: DOSSIER,
        regulatory_case_public_id: "case-1",
        title: "Dossier from v1",
        description: "",
        status: "open",
        owner: null,
        target_date: null,
        is_terminal: false,
        created_at: "2026-01-01T00:00:00Z",
        updated_at: "2026-01-01T00:00:00Z",
      },
      sections,
      summary: {
        total_sections: sections.length,
        required_sections: sections.length,
        ready: 0,
        partially_ready: 0,
        not_ready: sections.length,
        not_applicable: 0,
        open_blockers: 0,
        overall_readiness: "not_ready",
        overall_reason: "no_supporting_work",
      },
      blocker_counts: {},
      module_counts: { workflow_evidence_links: null },
      permissions: DOSSIER_PERMS,
    })
  );
  await page.route(
    new RegExp(`/api/regx/v1/submission-dossiers/${DOSSIER}/blueprint-provenance/$`),
    (r) => json(r, { instantiated_from_blueprint: true, version_number: 1, restricted: true })
  );
}

async function stubPlans(page: Page, listBody: unknown, detailBody?: unknown) {
  await page.route(
    new RegExp(`/api/regx/v1/submission-dossiers/${DOSSIER}/upgrade-plans/$`),
    (r) => json(r, listBody)
  );
  if (detailBody) {
    await page.route(new RegExp(`/api/regx/v1/dossier-upgrade-plans/${PLAN}/$`), (r) =>
      json(r, detailBody)
    );
  }
}

const EMPTY_LIST = {
  results: [],
  current_version: { public_id: "v1", version_number: 1, status: "retired" },
  available_targets: [{ public_id: "v2", version_number: 2, status: "active" }],
  permissions: UPGRADE_PERMS,
};

test.describe("Blueprint upgrade panel", () => {
  test.beforeEach(async ({ page }) => {
    await stubAuth(page);
    await stubDossier(page);
  });

  test("states that a newer version never changes the dossier by itself", async ({ page }) => {
    await stubPlans(page, EMPTY_LIST);
    await page.goto(`/submission-dossiers/${DOSSIER}?tenant=${TENANT}`);
    await expect(page.getByTestId("tab-panel-upgrade")).toContainText(
      /never changes this dossier on its own/i
    );
    await expect(page.getByTestId("ready-meaning-note")).toContainText(
      /not a regulatory, QA or agency approval/i
    );
  });

  test("offers a comparison and shows the dossier's current version", async ({ page }) => {
    await stubPlans(page, EMPTY_LIST);
    await page.goto(`/submission-dossiers/${DOSSIER}?tenant=${TENANT}`);
    await expect(page.getByTestId("current-version")).toContainText("version 1");
    await expect(page.getByTestId("generate-plan")).toBeVisible();
  });

  test("says so when there is nothing newer", async ({ page }) => {
    await stubPlans(page, { ...EMPTY_LIST, available_targets: [] });
    await page.goto(`/submission-dossiers/${DOSSIER}?tenant=${TENANT}`);
    await expect(page.getByTestId("no-targets")).toBeVisible();
    await expect(page.getByTestId("generate-plan")).toHaveCount(0);
  });

  test("generating a plan shows a diff and does not change the dossier", async ({ page }) => {
    let generated = false;
    await page.route(
      new RegExp(`/api/regx/v1/submission-dossiers/${DOSSIER}/upgrade-plans/$`),
      (r) => {
        if (r.request().method() === "POST") {
          generated = true;
          return json(r, planSummary(), 201);
        }
        return json(r, generated ? { ...EMPTY_LIST, results: [planSummary()] } : EMPTY_LIST);
      }
    );
    await page.route(new RegExp(`/api/regx/v1/dossier-upgrade-plans/${PLAN}/$`), (r) =>
      json(r, {
        ...planSummary(),
        items: [planItem(), planItem({ public_id: "item-add", change_type: "add_section", section_code: "C", before_value: "", after_value: "Section C" })],
        permissions: UPGRADE_PERMS,
      })
    );

    await page.goto(`/submission-dossiers/${DOSSIER}?tenant=${TENANT}`);
    await page.getByTestId("upgrade-target").selectOption("v2");
    await page.getByTestId("generate-plan").click();

    await expect(page.getByTestId("upgrade-diff")).toBeVisible();
    await expect(page.getByTestId("upgrade-row")).toHaveCount(2);
    // The dossier's own outline is unchanged: one section, as the server says.
    await expect(page.getByTestId("section-row")).toHaveCount(1);
  });

  test("a draft plan offers review but not apply", async ({ page }) => {
    await stubPlans(page, { ...EMPTY_LIST, results: [planSummary()] }, {
      ...planSummary(),
      items: [planItem()],
      permissions: UPGRADE_PERMS,
    });
    await page.goto(`/submission-dossiers/${DOSSIER}?tenant=${TENANT}`);
    await expect(page.getByTestId("accept-item")).toBeVisible();
    await expect(page.getByTestId("mark-ready")).toBeVisible();
    await expect(page.getByTestId("apply-plan")).toHaveCount(0);
  });

  test("accepting a subset leaves the rest alone", async ({ page }) => {
    let accepted = false;
    await page.route(
      new RegExp(`/api/regx/v1/submission-dossiers/${DOSSIER}/upgrade-plans/$`),
      (r) => json(r, { ...EMPTY_LIST, results: [planSummary({ accepted_items: accepted ? 1 : 0 })] })
    );
    await page.route(new RegExp(`/api/regx/v1/dossier-upgrade-plans/${PLAN}/$`), (r) =>
      json(r, {
        ...planSummary({ accepted_items: accepted ? 1 : 0 }),
        items: [
          planItem({ status: accepted ? "accepted" : "proposed" }),
          planItem({ public_id: "item-add", change_type: "add_section", section_code: "C" }),
        ],
        permissions: UPGRADE_PERMS,
      })
    );
    await page.route(
      new RegExp(`/api/regx/v1/dossier-upgrade-plans/${PLAN}/items/item-title/accept/$`),
      (r) => {
        accepted = true;
        return json(r, planItem({ status: "accepted" }));
      }
    );

    await page.goto(`/submission-dossiers/${DOSSIER}?tenant=${TENANT}`);
    await page.getByTestId("accept-item").first().click();

    const rows = page.getByTestId("upgrade-row");
    await expect(rows.nth(0)).toHaveAttribute("data-item-status", "accepted");
    await expect(rows.nth(1)).toHaveAttribute("data-item-status", "proposed");
  });

  test("a blocked item explains itself and cannot be accepted", async ({ page }) => {
    await stubPlans(
      page,
      { ...EMPTY_LIST, results: [planSummary({ blocked_items: 1 })] },
      {
        ...planSummary({ blocked_items: 1 }),
        items: [
          planItem({
            public_id: "item-retire",
            change_type: "retire_section",
            status: "blocked",
            blocking_reason: "has_open_blockers",
            section_code: "B",
          }),
        ],
        permissions: UPGRADE_PERMS,
      }
    );
    await page.goto(`/submission-dossiers/${DOSSIER}?tenant=${TENANT}`);
    await expect(page.getByTestId("blocking-reason")).toContainText(/open blocker/i);
    await expect(page.getByTestId("accept-item")).toHaveCount(0);
  });

  test("a conflict is labelled and needs manual review", async ({ page }) => {
    await stubPlans(
      page,
      { ...EMPTY_LIST, results: [planSummary({ conflict_items: 1, blocked_items: 1 })] },
      {
        ...planSummary({ conflict_items: 1, blocked_items: 1 }),
        items: [
          planItem({
            public_id: "item-conflict",
            change_type: "conflict",
            status: "blocked",
            blocking_reason: "ambiguous_section_code",
            section_code: "Z",
            field_name: "",
            before_value: "",
            after_value: "",
          }),
        ],
        permissions: UPGRADE_PERMS,
      }
    );
    await page.goto(`/submission-dossiers/${DOSSIER}?tenant=${TENANT}`);
    await expect(page.getByTestId("change-type-badge")).toContainText(/Conflict/);
    await expect(page.getByTestId("blocking-reason")).toContainText(/added by hand/i);
  });

  test("a stale plan warns and must be regenerated", async ({ page }) => {
    await stubPlans(
      page,
      { ...EMPTY_LIST, results: [planSummary({ is_stale: true })] },
      { ...planSummary({ is_stale: true }), items: [planItem()], permissions: UPGRADE_PERMS }
    );
    await page.goto(`/submission-dossiers/${DOSSIER}?tenant=${TENANT}`);
    await expect(page.getByTestId("plan-stale")).toContainText(/Regenerate before applying/i);
    await expect(page.getByTestId("regenerate-plan")).toBeVisible();
  });

  test("apply asks for confirmation before sending anything", async ({ page }) => {
    let applyCalls = 0;
    await stubPlans(
      page,
      { ...EMPTY_LIST, results: [planSummary({ status: "ready", accepted_items: 1 })] },
      {
        ...planSummary({ status: "ready", accepted_items: 1 }),
        items: [planItem({ status: "accepted" })],
        permissions: UPGRADE_PERMS,
      }
    );
    await page.route(new RegExp(`/api/regx/v1/dossier-upgrade-plans/${PLAN}/apply/$`), (r) => {
      applyCalls += 1;
      return json(r, {}, 201);
    });

    await page.goto(`/submission-dossiers/${DOSSIER}?tenant=${TENANT}`);
    await page.getByTestId("apply-plan").click();
    await expect(page.getByTestId("apply-confirm")).toBeVisible();
    expect(applyCalls).toBe(0);

    await page.getByTestId("apply-confirm-no").click();
    await expect(page.getByTestId("apply-confirm")).toHaveCount(0);
    expect(applyCalls).toBe(0);
  });

  test("confirming applies and reports exactly what changed", async ({ page }) => {
    let applied = false;
    await page.route(
      new RegExp(`/api/regx/v1/submission-dossiers/${DOSSIER}/upgrade-plans/$`),
      (r) =>
        json(r, {
          ...EMPTY_LIST,
          available_targets: applied ? [] : EMPTY_LIST.available_targets,
          results: [
            planSummary({
              status: applied ? "applied" : "ready",
              accepted_items: 1,
              applied_at: applied ? "2026-02-01T00:00:00Z" : null,
            }),
          ],
        })
    );
    await page.route(new RegExp(`/api/regx/v1/dossier-upgrade-plans/${PLAN}/$`), (r) =>
      json(r, {
        ...planSummary({ status: applied ? "applied" : "ready", accepted_items: 1 }),
        items: [planItem({ status: applied ? "applied" : "accepted" })],
        permissions: UPGRADE_PERMS,
      })
    );
    await page.route(new RegExp(`/api/regx/v1/dossier-upgrade-plans/${PLAN}/apply/$`), (r) => {
      applied = true;
      return json(
        r,
        {
          public_id: "app-1",
          plan_public_id: PLAN,
          dossier_public_id: DOSSIER,
          source_version_number: 1,
          target_version_number: 2,
          sections_added: 2,
          sections_retired: 1,
          sections_updated: 1,
          dossier_route: `/submission-dossiers/${DOSSIER}`,
        },
        201
      );
    });

    await page.goto(`/submission-dossiers/${DOSSIER}?tenant=${TENANT}`);
    await page.getByTestId("apply-plan").click();
    await page.getByTestId("apply-confirm-yes").click();

    await expect(page.getByTestId("upgrade-applied")).toContainText(
      "2 added, 1 updated, 1 retired"
    );
    await expect(page.getByTestId("upgrade-history")).toContainText("Version 1 → 2");
  });

  test("does not offer apply to a caller the API says cannot apply", async ({ page }) => {
    const perms = { ...UPGRADE_PERMS, can_apply: false };
    await stubPlans(
      page,
      { ...EMPTY_LIST, results: [planSummary({ status: "ready" })], permissions: perms },
      { ...planSummary({ status: "ready" }), items: [planItem()], permissions: perms }
    );
    await page.goto(`/submission-dossiers/${DOSSIER}?tenant=${TENANT}`);
    await expect(page.getByTestId("open-plan")).toBeVisible();
    await expect(page.getByTestId("apply-plan")).toHaveCount(0);
  });

  test("surfaces a refused apply as a readable message and keeps the plan", async ({ page }) => {
    await stubPlans(
      page,
      { ...EMPTY_LIST, results: [planSummary({ status: "ready", accepted_items: 1 })] },
      {
        ...planSummary({ status: "ready", accepted_items: 1 }),
        items: [planItem({ status: "accepted" })],
        permissions: UPGRADE_PERMS,
      }
    );
    await page.route(new RegExp(`/api/regx/v1/dossier-upgrade-plans/${PLAN}/apply/$`), (r) =>
      json(r, { detail: "The dossier changed after this plan was generated." }, 409)
    );

    await page.goto(`/submission-dossiers/${DOSSIER}?tenant=${TENANT}`);
    await page.getByTestId("apply-plan").click();
    await page.getByTestId("apply-confirm-yes").click();

    // The server's own reason reaches the user, rather than a generic string:
    // it is what tells them whether to regenerate or clear the work first.
    await expect(page.getByTestId("upgrade-error")).toContainText(
      "The dossier changed after this plan was generated."
    );
    await expect(page.getByTestId("open-plan")).toBeVisible();
  });

  test("a retirement refused for work recorded after review names the section", async ({
    page,
  }) => {
    await stubPlans(
      page,
      { ...EMPTY_LIST, results: [planSummary({ status: "ready", accepted_items: 1 })] },
      {
        ...planSummary({ status: "ready", accepted_items: 1 }),
        items: [planItem({ status: "accepted", change_type: "retire_section" })],
        permissions: UPGRADE_PERMS,
      }
    );
    await page.route(new RegExp(`/api/regx/v1/dossier-upgrade-plans/${PLAN}/apply/$`), (r) =>
      json(
        r,
        {
          detail:
            "Cannot retire A.1: has_open_blockers. Work was recorded on it " +
            "after this plan was reviewed; regenerate the plan.",
        },
        409
      )
    );

    await page.goto(`/submission-dossiers/${DOSSIER}?tenant=${TENANT}`);
    await page.getByTestId("apply-plan").click();
    await page.getByTestId("apply-confirm-yes").click();

    const alert = page.getByTestId("upgrade-error");
    await expect(alert).toContainText("A.1");
    await expect(alert).toContainText(/regenerate the plan/i);
    // Refused whole: the plan is still there to regenerate.
    await expect(page.getByTestId("open-plan")).toBeVisible();
  });

  test("a dossier already matching the target says there is nothing to apply", async ({
    page,
  }) => {
    await stubPlans(
      page,
      { ...EMPTY_LIST, results: [planSummary({ actionable_items: 0, total_items: 1 })] },
      {
        ...planSummary({ actionable_items: 0, total_items: 1 }),
        items: [planItem({ public_id: "item-nc", change_type: "no_change", section_code: "" })],
        permissions: UPGRADE_PERMS,
      }
    );
    await page.goto(`/submission-dossiers/${DOSSIER}?tenant=${TENANT}`);
    await expect(page.getByTestId("no-differences")).toBeVisible();
    await expect(page.getByTestId("upgrade-row")).toHaveCount(0);
  });
});
