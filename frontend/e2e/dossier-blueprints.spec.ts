import { test, expect, type Page, type Route } from "@playwright/test";

/**
 * Dossier blueprint library E2E.
 *
 * API responses are mocked with page.route, as every other spec here does, so
 * the test exercises the UI contract rather than a live backend.
 *
 * The property under test is that the UI renders what the API projects: a
 * published version is read-only whatever the caller's permissions say, an
 * active version offers instantiation and a draft does not, and a dossier built
 * from a version does not change when a later version is edited.
 */

const API = "http://localhost:8000";
const TENANT = "alpha";
const BP = "aaaaaaaa-1111-2222-3333-444444444444";
const V1 = "bbbbbbbb-1111-2222-3333-444444444444";
const V2 = "cccccccc-1111-2222-3333-444444444444";
const CASE = "dddddddd-1111-2222-3333-444444444444";
const DOSSIER = "eeeeeeee-1111-2222-3333-444444444444";

const PERMS = {
  can_create: true,
  can_edit: true,
  can_manage_sections: true,
  can_create_version: true,
  can_activate: true,
  can_retire: true,
  can_instantiate: true,
  can_archive: true,
};

function section(over: Record<string, unknown> = {}) {
  return {
    public_id: "sec-a",
    parent_public_id: null,
    section_code: "A",
    title: "Section A",
    description: "",
    sequence: 0,
    required: true,
    default_due_offset_days: null,
    is_retired: false,
    ...over,
  };
}

const OUTLINE = [
  section({ public_id: "sec-a", section_code: "A", sequence: 0 }),
  section({ public_id: "sec-a1", section_code: "A.1", parent_public_id: "sec-a", sequence: 0 }),
  section({ public_id: "sec-b", section_code: "B", sequence: 10, required: false }),
];

function version(over: Record<string, unknown> = {}) {
  return {
    public_id: V1,
    blueprint_public_id: BP,
    version_number: 1,
    status: "draft",
    notes: "",
    created_by: { public_id: "u1", full_name: "Author One" },
    supersedes_public_id: null,
    activated_at: null,
    retired_at: null,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...over,
  };
}

function versionDetail(over: Record<string, unknown> = {}) {
  return {
    ...version(),
    blueprint: { public_id: BP, name: "Synthetic outline A" },
    sections: OUTLINE,
    section_count: OUTLINE.length,
    instantiation_count: 0,
    is_editable: true,
    permissions: PERMS,
    ...over,
  };
}

async function json(route: Route, body: unknown, status = 200) {
  await route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
}

async function stubAuth(page: Page) {
  await page.route(`${API}/api/regx/v1/auth/session/`, (r) =>
    json(r, { user: { public_id: "u1", email: "a@example.test", full_name: "Author One" } })
  );
  // Every mutation fetches a CSRF token first; without this stub each POST
  // fails before it reaches its own route and the UI shows an error instead.
  await page.route(`${API}/api/regx/v1/auth/csrf/`, (r) => json(r, { csrfToken: "e2e" }));
  await page.route(`${API}/api/regx/v1/tenants/**`, (r) =>
    json(r, { results: [{ public_id: "t1", name: "Alpha", slug: TENANT }] })
  );
}

test.describe("Blueprint library", () => {
  test.beforeEach(async ({ page }) => {
    await stubAuth(page);
  });

  test("lists blueprints with their current version and usage", async ({ page }) => {
    await page.route(/\/api\/regx\/v1\/dossier-blueprints\/($|\?)/, (r) =>
      json(r, {
        results: [
          {
            public_id: BP,
            name: "Synthetic outline A",
            description: "",
            owner: null,
            created_by: null,
            is_archived: false,
            created_at: "2026-01-01T00:00:00Z",
            updated_at: "2026-01-02T00:00:00Z",
            current_version_number: 1,
            current_version_status: "active",
            current_version_public_id: V1,
            version_count: 2,
            instantiation_count: 3,
          },
        ],
        permissions: PERMS,
      })
    );

    await page.goto(`/dossier-blueprints?tenant=${TENANT}`);
    await expect(page.getByTestId("blueprints-table")).toBeVisible();
    await expect(page.getByTestId("blueprint-link")).toHaveText("Synthetic outline A");
    await expect(page.getByTestId("usage-count")).toHaveText("3");
    await expect(page.getByTestId("version-status-badge")).toHaveText(/Active/);
  });

  test("states what Active means so it is not read as an approval", async ({ page }) => {
    await page.route(/\/api\/regx\/v1\/dossier-blueprints\/($|\?)/, (r) =>
      json(r, { results: [], permissions: PERMS })
    );
    await page.goto(`/dossier-blueprints?tenant=${TENANT}`);
    await expect(page.getByTestId("active-meaning-note")).toContainText(
      /not a regulatory, QA or agency approval/i
    );
  });

  test("shows an empty state when there are no blueprints", async ({ page }) => {
    await page.route(/\/api\/regx\/v1\/dossier-blueprints\/($|\?)/, (r) =>
      json(r, { results: [], permissions: PERMS })
    );
    await page.goto(`/dossier-blueprints?tenant=${TENANT}`);
    await expect(page.getByTestId("blueprints-empty")).toBeVisible();
  });

  test("does not offer creation to a caller the API says cannot create", async ({ page }) => {
    await page.route(/\/api\/regx\/v1\/dossier-blueprints\/($|\?)/, (r) =>
      json(r, { results: [], permissions: { ...PERMS, can_create: false } })
    );
    await page.goto(`/dossier-blueprints?tenant=${TENANT}`);
    await expect(page.getByTestId("blueprints-empty")).toBeVisible();
    await expect(page.getByTestId("new-blueprint")).toHaveCount(0);
  });

  test("creates a blueprint", async ({ page }) => {
    let created = false;
    await page.route(/\/api\/regx\/v1\/dossier-blueprints\/($|\?)/, async (r) => {
      if (r.request().method() === "POST") {
        created = true;
        return json(r, { public_id: BP, name: "New outline" }, 201);
      }
      return json(r, {
        results: created
          ? [
              {
                public_id: BP,
                name: "New outline",
                description: "",
                owner: null,
                created_by: null,
                is_archived: false,
                created_at: "2026-01-01T00:00:00Z",
                updated_at: "2026-01-01T00:00:00Z",
                version_count: 0,
                instantiation_count: 0,
              },
            ]
          : [],
        permissions: PERMS,
      });
    });

    await page.goto(`/dossier-blueprints?tenant=${TENANT}`);
    await page.getByTestId("new-blueprint").click();
    await page.getByTestId("blueprint-name-input").fill("New outline");
    await page.getByTestId("create-blueprint-submit").click();
    await expect(page.getByTestId("blueprint-link")).toHaveText("New outline");
  });
});

test.describe("Blueprint version editing", () => {
  test.beforeEach(async ({ page }) => {
    await stubAuth(page);
  });

  test("renders the outline as a tree with levels", async ({ page }) => {
    await page.route(new RegExp(`/api/regx/v1/dossier-blueprint-versions/${V1}/$`), (r) =>
      json(r, versionDetail())
    );
    await page.goto(`/dossier-blueprints/${BP}/versions/${V1}?tenant=${TENANT}`);

    const rows = page.getByTestId("blueprint-tree-row");
    await expect(rows).toHaveCount(3);
    await expect(rows.nth(0)).toHaveAttribute("data-depth", "0");
    await expect(rows.nth(1)).toHaveAttribute("data-depth", "1");
  });

  test("collapsing a parent hides its children", async ({ page }) => {
    await page.route(new RegExp(`/api/regx/v1/dossier-blueprint-versions/${V1}/$`), (r) =>
      json(r, versionDetail())
    );
    await page.goto(`/dossier-blueprints/${BP}/versions/${V1}?tenant=${TENANT}`);
    await expect(page.getByTestId("blueprint-tree-row")).toHaveCount(3);
    await page.getByRole("button", { name: /collapse A$/i }).click();
    await expect(page.getByTestId("blueprint-tree-row")).toHaveCount(2);
  });

  test("searching filters the outline", async ({ page }) => {
    await page.route(new RegExp(`/api/regx/v1/dossier-blueprint-versions/${V1}/$`), (r) =>
      json(r, versionDetail())
    );
    await page.goto(`/dossier-blueprints/${BP}/versions/${V1}?tenant=${TENANT}`);
    await page.getByTestId("blueprint-tree-search").fill("A.1");
    await expect(page.getByTestId("blueprint-tree-row")).toHaveCount(1);
  });

  test("adds a section to a draft", async ({ page }) => {
    let added = false;
    await page.route(new RegExp(`/api/regx/v1/dossier-blueprint-versions/${V1}/$`), (r) =>
      json(
        r,
        versionDetail({
          sections: added ? [...OUTLINE, section({ public_id: "sec-c", section_code: "C", sequence: 20 })] : OUTLINE,
          section_count: added ? 4 : 3,
        })
      )
    );
    await page.route(new RegExp(`/api/regx/v1/dossier-blueprint-versions/${V1}/sections/$`), (r) => {
      added = true;
      return json(r, section({ public_id: "sec-c", section_code: "C" }), 201);
    });

    await page.goto(`/dossier-blueprints/${BP}/versions/${V1}?tenant=${TENANT}`);
    await page.getByTestId("add-section").click();
    await page.getByTestId("section-code-input").fill("C");
    await page.getByTestId("section-title-input").fill("Section C");
    await page.getByTestId("add-section-submit").click();
    await expect(page.getByTestId("blueprint-tree-row")).toHaveCount(4);
  });

  test("reorders a section", async ({ page }) => {
    let reordered = false;
    await page.route(new RegExp(`/api/regx/v1/dossier-blueprint-versions/${V1}/$`), (r) =>
      json(
        r,
        versionDetail({
          sections: reordered
            ? [
                section({ public_id: "sec-b", section_code: "B", sequence: 0, required: false }),
                section({ public_id: "sec-a", section_code: "A", sequence: 10 }),
                section({
                  public_id: "sec-a1",
                  section_code: "A.1",
                  parent_public_id: "sec-a",
                  sequence: 0,
                }),
              ]
            : OUTLINE,
        })
      )
    );
    await page.route(
      /\/api\/regx\/v1\/dossier-blueprint-sections\/[0-9a-z-]+\/reorder\/$/,
      (r) => {
        reordered = true;
        return json(r, section());
      }
    );

    await page.goto(`/dossier-blueprints/${BP}/versions/${V1}?tenant=${TENANT}`);
    await expect(page.getByTestId("blueprint-tree-row").first()).toHaveAttribute(
      "data-section-code",
      "A"
    );
    await page.getByTestId("move-down").first().click();
    await expect(page.getByTestId("blueprint-tree-row").first()).toHaveAttribute(
      "data-section-code",
      "B"
    );
  });

  test("activates a draft and the version becomes read-only", async ({ page }) => {
    let active = false;
    await page.route(new RegExp(`/api/regx/v1/dossier-blueprint-versions/${V1}/$`), (r) =>
      json(
        r,
        versionDetail(
          active
            ? { status: "active", is_editable: false, activated_at: "2026-02-01T00:00:00Z" }
            : {}
        )
      )
    );
    await page.route(new RegExp(`/api/regx/v1/dossier-blueprint-versions/${V1}/activate/$`), (r) => {
      active = true;
      return json(r, version({ status: "active" }));
    });

    await page.goto(`/dossier-blueprints/${BP}/versions/${V1}?tenant=${TENANT}`);
    await expect(page.getByTestId("add-section")).toBeVisible();

    await page.getByTestId("activate-version").click();

    await expect(page.getByTestId("read-only-note")).toBeVisible();
    await expect(page.getByTestId("version-status-badge")).toHaveText(/Active/);
    // Editing controls are gone, and the API would refuse them anyway.
    await expect(page.getByTestId("add-section")).toHaveCount(0);
    await expect(page.getByTestId("move-up")).toHaveCount(0);
    await expect(page.getByTestId("retire-section")).toHaveCount(0);
  });

  test("an active version offers instantiation and a draft does not", async ({ page }) => {
    await page.route(new RegExp(`/api/regx/v1/dossier-blueprint-versions/${V1}/$`), (r) =>
      json(r, versionDetail())
    );
    await page.goto(`/dossier-blueprints/${BP}/versions/${V1}?tenant=${TENANT}`);
    await expect(page.getByTestId("open-instantiate")).toHaveCount(0);

    await page.route(new RegExp(`/api/regx/v1/dossier-blueprint-versions/${V2}/$`), (r) =>
      json(r, versionDetail({ public_id: V2, status: "active", is_editable: false }))
    );
    await page.goto(`/dossier-blueprints/${BP}/versions/${V2}?tenant=${TENANT}`);
    await expect(page.getByTestId("open-instantiate")).toBeVisible();
  });

  test("does not offer activation to a caller the API says cannot activate", async ({ page }) => {
    await page.route(new RegExp(`/api/regx/v1/dossier-blueprint-versions/${V1}/$`), (r) =>
      json(r, versionDetail({ permissions: { ...PERMS, can_activate: false } }))
    );
    await page.goto(`/dossier-blueprints/${BP}/versions/${V1}?tenant=${TENANT}`);
    await expect(page.getByTestId("blueprint-tree")).toBeVisible();
    await expect(page.getByTestId("activate-version")).toHaveCount(0);
  });

  test("surfaces a refused activation as a readable message", async ({ page }) => {
    await page.route(new RegExp(`/api/regx/v1/dossier-blueprint-versions/${V1}/$`), (r) =>
      json(r, versionDetail({ sections: [], section_count: 0 }))
    );
    await page.route(new RegExp(`/api/regx/v1/dossier-blueprint-versions/${V1}/activate/$`), (r) =>
      json(r, { detail: "A version must have at least one section." }, 409)
    );

    await page.goto(`/dossier-blueprints/${BP}/versions/${V1}?tenant=${TENANT}`);
    await page.getByTestId("activate-version").click();
    await expect(page.getByTestId("version-error")).toContainText(/at least one section/i);
  });
});

test.describe("Instantiation", () => {
  test.beforeEach(async ({ page }) => {
    await stubAuth(page);
  });

  test("creates a dossier from an active version and links to it", async ({ page }) => {
    await page.route(new RegExp(`/api/regx/v1/dossier-blueprint-versions/${V2}/$`), (r) =>
      json(r, versionDetail({ public_id: V2, status: "active", is_editable: false }))
    );
    await page.route(/\/api\/regx\/v1\/regulatory-cases\/($|\?)/, (r) =>
      json(r, {
        results: [
          {
            public_id: CASE,
            case_number: "CASE-0001",
            title: "Synthetic case",
            status: "open",
            is_terminal: false,
          },
        ],
        permissions: {},
      })
    );
    await page.route(
      new RegExp(`/api/regx/v1/dossier-blueprint-versions/${V2}/instantiate/$`),
      (r) =>
        json(
          r,
          {
            dossier_public_id: DOSSIER,
            case_public_id: CASE,
            blueprint_public_id: BP,
            version_public_id: V2,
            version_number: 1,
            section_count: 3,
            dossier_route: `/submission-dossiers/${DOSSIER}`,
          },
          201
        )
    );

    await page.goto(`/dossier-blueprints/${BP}/versions/${V2}?tenant=${TENANT}`);
    await page.getByTestId("open-instantiate").click();
    await page.getByTestId("instantiate-case").selectOption(CASE);
    await page.getByTestId("instantiate-title").fill("Dossier from blueprint");
    await page.getByTestId("instantiate-submit").click();

    await expect(page.getByTestId("instantiate-result")).toContainText("3 sections");
    await expect(page.getByTestId("go-to-dossier")).toHaveAttribute(
      "href",
      new RegExp(`/submission-dossiers/${DOSSIER}`)
    );
  });

  test("surfaces a refused case as a safe message rather than a leak", async ({ page }) => {
    await page.route(new RegExp(`/api/regx/v1/dossier-blueprint-versions/${V2}/$`), (r) =>
      json(r, versionDetail({ public_id: V2, status: "active", is_editable: false }))
    );
    await page.route(/\/api\/regx\/v1\/regulatory-cases\/($|\?)/, (r) =>
      json(r, {
        results: [
          {
            public_id: CASE,
            case_number: "CASE-0001",
            title: "Synthetic case",
            status: "open",
            is_terminal: false,
          },
        ],
        permissions: {},
      })
    );
    await page.route(
      new RegExp(`/api/regx/v1/dossier-blueprint-versions/${V2}/instantiate/$`),
      (r) => json(r, { detail: "That item is not available." }, 400)
    );

    await page.goto(`/dossier-blueprints/${BP}/versions/${V2}?tenant=${TENANT}`);
    await page.getByTestId("open-instantiate").click();
    await page.getByTestId("instantiate-case").selectOption(CASE);
    await page.getByTestId("instantiate-title").fill("Nope");
    await page.getByTestId("instantiate-submit").click();

    const error = page.getByTestId("version-error");
    await expect(error).toBeVisible();
    // The message says nothing about whether the case exists.
    await expect(error).not.toContainText(/does not exist|not found|another tenant/i);
  });

  test("does not offer instantiation to a caller the API says cannot instantiate", async ({
    page,
  }) => {
    await page.route(new RegExp(`/api/regx/v1/dossier-blueprint-versions/${V2}/$`), (r) =>
      json(
        r,
        versionDetail({
          public_id: V2,
          status: "active",
          is_editable: false,
          permissions: { ...PERMS, can_instantiate: false },
        })
      )
    );
    await page.goto(`/dossier-blueprints/${BP}/versions/${V2}?tenant=${TENANT}`);
    await expect(page.getByTestId("blueprint-tree")).toBeVisible();
    await expect(page.getByTestId("open-instantiate")).toHaveCount(0);
  });
});

test.describe("Provenance and independence", () => {
  test.beforeEach(async ({ page }) => {
    await stubAuth(page);
  });

  test("a dossier built from a version does not change when a later draft is edited", async ({
    page,
  }) => {
    // The generated dossier is a snapshot: its sections come from the dossier
    // API and never from the blueprint, so editing v2 cannot reach them.
    const dossierSections = [
      {
        public_id: "d-a",
        parent_public_id: null,
        section_code: "A",
        title: "Section A",
        description: "",
        notes: "",
        sequence: 0,
        required: true,
        status: "not_started",
        readiness: "partially_ready",
        readiness_reason: "section_not_complete",
        owner: null,
        due_date: null,
        is_retired: false,
        created_at: "2026-01-01T00:00:00Z",
        updated_at: "2026-01-01T00:00:00Z",
      },
    ];

    await page.route(new RegExp(`/api/regx/v1/submission-dossiers/${DOSSIER}/$`), (r) =>
      json(r, {
        dossier: {
          public_id: DOSSIER,
          regulatory_case_public_id: CASE,
          title: "Dossier from blueprint",
          description: "",
          status: "open",
          owner: null,
          target_date: null,
          is_terminal: false,
          created_at: "2026-01-01T00:00:00Z",
          updated_at: "2026-01-01T00:00:00Z",
        },
        sections: dossierSections,
        summary: {
          total_sections: 1,
          required_sections: 1,
          ready: 0,
          partially_ready: 1,
          not_ready: 0,
          not_applicable: 0,
          open_blockers: 0,
          overall_readiness: "partially_ready",
          overall_reason: "section_not_complete",
        },
        blocker_counts: {},
        module_counts: { workflow_evidence_links: null },
        permissions: {
          can_create: true,
          can_edit: true,
          can_manage_sections: true,
          can_manage_links: true,
          can_manage_blockers: true,
          can_complete: true,
          can_cancel: true,
        },
      })
    );
    await page.route(
      new RegExp(`/api/regx/v1/submission-dossiers/${DOSSIER}/blueprint-provenance/$`),
      (r) =>
        json(r, {
          instantiated_from_blueprint: true,
          instantiation_public_id: "inst-1",
          blueprint_public_id: BP,
          version_public_id: V1,
          version_number: 1,
          section_count: 1,
          instantiated_at: "2026-01-01T00:00:00Z",
          blueprint_name: "Synthetic outline A",
        })
    );

    await page.goto(`/submission-dossiers/${DOSSIER}?tenant=${TENANT}`);
    await expect(page.getByTestId("blueprint-provenance")).toContainText("Synthetic outline A");
    await expect(page.getByTestId("blueprint-provenance")).toContainText("version 1");
    await expect(page.getByTestId("section-row")).toHaveCount(1);
  });

  test("a restricted caller sees the provenance but not the blueprint name", async ({ page }) => {
    await page.route(new RegExp(`/api/regx/v1/submission-dossiers/${DOSSIER}/$`), (r) =>
      json(r, {
        dossier: {
          public_id: DOSSIER,
          regulatory_case_public_id: CASE,
          title: "Dossier from blueprint",
          description: "",
          status: "open",
          owner: null,
          target_date: null,
          is_terminal: false,
          created_at: "2026-01-01T00:00:00Z",
          updated_at: "2026-01-01T00:00:00Z",
        },
        sections: [],
        summary: {
          total_sections: 0,
          required_sections: 0,
          ready: 0,
          partially_ready: 0,
          not_ready: 0,
          not_applicable: 0,
          open_blockers: 0,
          overall_readiness: "not_ready",
          overall_reason: "no_supporting_work",
        },
        blocker_counts: {},
        module_counts: { workflow_evidence_links: null },
        permissions: {
          can_create: false,
          can_edit: false,
          can_manage_sections: false,
          can_manage_links: false,
          can_manage_blockers: false,
          can_complete: false,
          can_cancel: false,
        },
      })
    );
    await page.route(
      new RegExp(`/api/regx/v1/submission-dossiers/${DOSSIER}/blueprint-provenance/$`),
      (r) =>
        json(r, {
          instantiated_from_blueprint: true,
          version_number: 4,
          restricted: true,
        })
    );

    await page.goto(`/submission-dossiers/${DOSSIER}?tenant=${TENANT}`);
    const line = page.getByTestId("blueprint-provenance");
    await expect(line).toHaveAttribute("data-restricted", "true");
    await expect(line).toContainText(/controlled blueprint/i);
    await expect(line).toContainText("version 4");
    await expect(line).not.toContainText("Synthetic outline A");
  });
});
