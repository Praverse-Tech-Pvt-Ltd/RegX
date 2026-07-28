// IIG checklist definition-governance Playwright suite.
//
// As in fda-iid.spec.ts, every backend response here is a deterministic
// Playwright route mock (page.route), not a live backend. Server-side
// enforcement (permissions, lifecycle transitions, tenant isolation) is
// covered by the backend pytest suite (iig_checklist/tests/) instead.
// This suite proves the FRONTEND renders and reacts correctly to those
// API contracts. Fixtures are synthetic and non-confidential.
//
// This suite covers checklist DEFINITION GOVERNANCE only -- it never
// renders or exercises checklist execution, responses, or calculation
// outcomes, none of which exist in this milestone's scope.
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

function definitionFixture(overrides: Record<string, unknown> = {}) {
  return {
    public_id: "def-e2e-1",
    code: "IIG-ORAL-SOLID",
    title: "IIG Oral Solid (synthetic)",
    description: "",
    scope_type: "tenant",
    tenant_public_id: "tenant-e2e-1",
    created_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

function versionFixture(overrides: Record<string, unknown> = {}) {
  return {
    public_id: "ver-e2e-1",
    definition_public_id: "def-e2e-1",
    version_number: 1,
    status: "draft",
    effective_date: null,
    expiry_date: null,
    regulatory_basis: "",
    change_summary: "",
    cloned_from_version_public_id: null,
    return_reason: "",
    submitted_by_email: null,
    reviewed_by_email: null,
    approved_by_email: null,
    activated_by_email: null,
    returned_at: null,
    rejected_at: null,
    retired_at: null,
    sections: [],
    created_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

test.describe("Checklist definition inventory", () => {
  test("loads and lists a checklist definition", async ({ page }) => {
    await page.route(
      /\/api\/regx\/v1\/iig-checklists\/definitions\/(\?[^/]*)?$/,
      jsonRoute(paginate([definitionFixture()])),
    );

    await page.goto(`/iig-checklists?tenant=${TENANT}`);
    await expect(page.getByRole("heading", { name: "Checklist Definitions" })).toBeVisible();
    await expect(page.getByRole("link", { name: "IIG-ORAL-SOLID" })).toBeVisible();
  });

  test("creating a definition navigates to its detail page", async ({ page }) => {
    await mockCsrf(page);
    await page.route(
      `${API}/api/regx/v1/iig-checklists/definitions/`,
      async (route) => {
        if (route.request().method() === "POST") {
          return route.fulfill({
            status: 201,
            contentType: "application/json",
            body: JSON.stringify(definitionFixture({ public_id: "def-e2e-new" })),
          });
        }
        return route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify(paginate([])),
        });
      },
    );
    await page.route(
      `${API}/api/regx/v1/iig-checklists/definitions/def-e2e-new/`,
      jsonRoute(definitionFixture({ public_id: "def-e2e-new" })),
    );
    await page.route(
      `${API}/api/regx/v1/iig-checklists/definitions/def-e2e-new/versions/`,
      jsonRoute(paginate([])),
    );

    await page.goto(`/iig-checklists/new?tenant=${TENANT}`);
    await page.getByLabel("Code").fill("NEW-DEF");
    await page.getByLabel("Title").fill("New Definition");
    await page.getByRole("button", { name: "Create" }).click();

    await expect(page).toHaveURL(/\/iig-checklists\/def-e2e-new/);
  });
});

test.describe("Checklist version lifecycle", () => {
  test("create version 1 (draft) from the definition page", async ({ page }) => {
    await mockCsrf(page);
    await page.route(
      `${API}/api/regx/v1/iig-checklists/definitions/def-e2e-1/`,
      jsonRoute(definitionFixture()),
    );
    let versionCreated = false;
    await page.route(
      `${API}/api/regx/v1/iig-checklists/definitions/def-e2e-1/versions/`,
      async (route) => {
        if (route.request().method() === "POST") {
          versionCreated = true;
          return route.fulfill({
            status: 201,
            contentType: "application/json",
            body: JSON.stringify(versionFixture()),
          });
        }
        return route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify(paginate(versionCreated ? [versionFixture()] : [])),
        });
      },
    );

    await page.goto(`/iig-checklists/def-e2e-1?tenant=${TENANT}`);
    await expect(page.getByText("No versions yet.")).toBeVisible();
    await page.getByRole("button", { name: "Create new version" }).click();
    await expect(page.getByRole("link", { name: "v1" })).toBeVisible();
  });

  test("submit for review, return with a reason, then resubmit", async ({ page }) => {
    await mockCsrf(page);
    let status = "draft";
    let returnReason = "";
    // GET reflects current mutable state; POST actions below mutate it.
    await page.route(`${API}/api/regx/v1/iig-checklists/versions/ver-e2e-1/`, (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(versionFixture({ status, return_reason: returnReason })),
      }),
    );
    await page.route(
      `${API}/api/regx/v1/iig-checklists/versions/ver-e2e-1/submit-review/`,
      (route) => {
        status = "under_review";
        return route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify(versionFixture({ status })),
        });
      },
    );
    await page.route(`${API}/api/regx/v1/iig-checklists/versions/ver-e2e-1/return/`, (route) => {
      const body = route.request().postDataJSON() as { reason?: string };
      returnReason = body.reason ?? "";
      status = "returned";
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(versionFixture({ status, return_reason: returnReason })),
      });
    });

    await page.goto(`/iig-checklists/versions/ver-e2e-1?tenant=${TENANT}`);
    await page.getByRole("button", { name: "Submit for review" }).click();
    await expect(page.getByRole("button", { name: "Return for edits" })).toBeVisible();

    await page.getByLabel(/return reason/i).fill("Fix section order");
    await page.getByRole("button", { name: "Return for edits" }).click();
    await expect(page.getByText(/fix section order/i)).toBeVisible();
    await expect(page.getByRole("button", { name: "Submit for review" })).toBeVisible();
  });

  test("approve then activate; a second activate on an already-active definition is blocked", async ({
    page,
  }) => {
    await mockCsrf(page);
    let status = "under_review";
    await page.route(`${API}/api/regx/v1/iig-checklists/versions/ver-e2e-1/`, (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(
          versionFixture({ status, effective_date: "2026-01-01" }),
        ),
      }),
    );
    await page.route(`${API}/api/regx/v1/iig-checklists/versions/ver-e2e-1/approve/`, (route) => {
      status = "approved";
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(versionFixture({ status, effective_date: "2026-01-01" })),
      });
    });
    await page.route(`${API}/api/regx/v1/iig-checklists/versions/ver-e2e-1/activate/`, (route) => {
      status = "active";
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(versionFixture({ status, effective_date: "2026-01-01" })),
      });
    });

    await page.goto(`/iig-checklists/versions/ver-e2e-1?tenant=${TENANT}`);
    await page.getByRole("button", { name: "Approve" }).click();
    await expect(page.getByRole("button", { name: "Activate" })).toBeVisible();
    await page.getByRole("button", { name: "Activate" }).click();
    await expect(page.getByRole("button", { name: "Supersede" })).toBeVisible();

    // A second version attempting to activate while this one is already
    // active is rejected by the backend's one-active-version constraint;
    // the frontend must surface that structured error, not silently succeed.
    await page.route(
      `${API}/api/regx/v1/iig-checklists/versions/ver-e2e-2/`,
      jsonRoute(versionFixture({ public_id: "ver-e2e-2", version_number: 2, status: "approved", effective_date: "2026-01-01" })),
    );
    await page.route(
      `${API}/api/regx/v1/iig-checklists/versions/ver-e2e-2/activate/`,
      jsonRoute(
        { error: { status: 409, detail: { error_code: "ACTIVE_VERSION_CONFLICT", detail: "Another version is already active." } } },
        409,
      ),
    );
    await page.goto(`/iig-checklists/versions/ver-e2e-2?tenant=${TENANT}`);
    await page.getByRole("button", { name: "Activate" }).click();
    await expect(page.getByRole("alert")).toBeVisible();
  });

  test("an approved/active version never shows execution UI", async ({ page }) => {
    await page.route(
      `${API}/api/regx/v1/iig-checklists/versions/ver-e2e-1/`,
      jsonRoute(versionFixture({ status: "active" })),
    );
    await page.goto(`/iig-checklists/versions/ver-e2e-1?tenant=${TENANT}`);
    await expect(page.getByText(/checklist execution/i)).toBeVisible(); // disclaimer text
    await expect(page.getByRole("button", { name: /submit response/i })).toHaveCount(0);
    await expect(page.getByRole("button", { name: /run calculation/i })).toHaveCount(0);
  });
});

test.describe("Clone", () => {
  test("clone produces a new definition with a fresh draft version 1", async ({ page }) => {
    await mockCsrf(page);
    await page.route(
      `${API}/api/regx/v1/iig-checklists/definitions/def-e2e-1/`,
      jsonRoute(definitionFixture()),
    );
    await page.route(
      `${API}/api/regx/v1/iig-checklists/definitions/def-e2e-1/versions/`,
      jsonRoute(paginate([versionFixture({ status: "active" })])),
    );
    await page.route(
      `${API}/api/regx/v1/iig-checklists/definitions/def-e2e-1/clone/`,
      jsonRoute({
        definition: definitionFixture({ public_id: "def-e2e-clone", code: "IIG-ORAL-SOLID-CLONE" }),
        current_version: versionFixture({ public_id: "ver-e2e-clone", status: "draft" }),
      }),
    );
    await page.route(
      `${API}/api/regx/v1/iig-checklists/definitions/def-e2e-clone/`,
      jsonRoute(definitionFixture({ public_id: "def-e2e-clone", code: "IIG-ORAL-SOLID-CLONE" })),
    );
    await page.route(
      `${API}/api/regx/v1/iig-checklists/definitions/def-e2e-clone/versions/`,
      jsonRoute(paginate([versionFixture({ public_id: "ver-e2e-clone", status: "draft" })])),
    );

    await page.goto(`/iig-checklists/def-e2e-1?tenant=${TENANT}`);
    await page.getByRole("button", { name: "Clone into new definition" }).click();

    await expect(page).toHaveURL(/\/iig-checklists\/def-e2e-clone/);
    await expect(page.getByRole("link", { name: "v1" })).toBeVisible();
    await expect(page.getByText("draft", { exact: true })).toBeVisible();
  });
});

test.describe("Empty draft deletion", () => {
  test("an empty, never-submitted draft can be deleted from its definition page", async ({
    page,
  }) => {
    await mockCsrf(page);
    await page.route(
      `${API}/api/regx/v1/iig-checklists/definitions/def-e2e-1/`,
      (route) => {
        if (route.request().method() === "DELETE") {
          return route.fulfill({ status: 204 });
        }
        return route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify(definitionFixture()),
        });
      },
    );
    await page.route(
      `${API}/api/regx/v1/iig-checklists/definitions/def-e2e-1/versions/`,
      jsonRoute(paginate([versionFixture()])),
    );

    await page.goto(`/iig-checklists/def-e2e-1?tenant=${TENANT}`);
    await page.getByRole("button", { name: "Delete draft definition" }).click();
    await expect(page).toHaveURL(/\/iig-checklists\?tenant=alpha/);
  });
});
