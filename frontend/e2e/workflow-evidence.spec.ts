import { test, expect } from "@playwright/test";

/**
 * Workflow evidence lifecycle E2E.
 *
 * API responses are mocked with page.route, as every other spec here does.
 *
 * Two properties matter most and both are asserted:
 *   1. the section offers NO upload control -- the document platform owns
 *      uploads, and a second implementation would duplicate storage handling;
 *   2. a caller without `documents.view` sees that evidence exists but gets no
 *      document detail, because workflow access must not confer document access.
 */

const API = "http://localhost:8000";
const TENANT = "alpha";
const ITEM_ID = "11111111-2222-3333-4444-555555555555";
const DOC_ID = "aaaaaaaa-0000-0000-0000-000000000001";
const VERSION_ID = "bbbbbbbb-0000-0000-0000-000000000002";
const EVIDENCE_ID = "cccccccc-0000-0000-0000-000000000003";

function jsonRoute(body: unknown, status = 200) {
  return async (route: import("@playwright/test").Route) =>
    route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
}

function item(overrides: Record<string, unknown> = {}) {
  return {
    public_id: ITEM_ID,
    title: "Synthetic workflow item",
    description: "",
    state: "draft",
    created_by: { public_id: "u-1", email: "doer@example.com", full_name: "Doer" },
    assigned_to: null,
    assigned_at: null,
    due_at: null,
    is_overdue: false,
    is_terminal: false,
    available_actions: ["submit", "cancel"],
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

function evidenceRow(withDocument = true) {
  const base = {
    public_id: EVIDENCE_ID,
    label: "Validation protocol",
    linked_by: { public_id: "u-1", email: "doer@example.com", full_name: "Doer" },
    linked_at: "2026-01-02T00:00:00Z",
    document_version_public_id: VERSION_ID,
    document_public_id: DOC_ID,
  };
  if (!withDocument) return base;
  return {
    ...base,
    document: {
      title: "Protocol PV-001",
      document_type: "pdf",
      version_number: 3,
      original_filename: "protocol.pdf",
      size_bytes: 1024,
      sha256_checksum: "a".repeat(64),
      scan_status: "clean",
      uploaded_at: "2026-01-01T12:00:00Z",
    },
  };
}

async function mockWorkflow(
  page: import("@playwright/test").Page,
  detail: Record<string, unknown>,
  evidence: unknown[],
) {
  await page.route(`${API}/api/regx/v1/auth/csrf/`, jsonRoute({ csrfToken: "e2e-csrf-token" }));
  await page.route(new RegExp(`/api/regx/v1/workflows/${ITEM_ID}/$`), jsonRoute(detail));
  await page.route(new RegExp(`/api/regx/v1/workflows/${ITEM_ID}/history/$`), jsonRoute([]));
  await page.route(
    new RegExp(`/api/regx/v1/workflows/${ITEM_ID}/evidence/$`),
    jsonRoute(evidence),
  );
}

test.describe("Workflow evidence", () => {
  test("lists linked evidence with stable document and version identity", async ({ page }) => {
    await mockWorkflow(page, item(), [evidenceRow()]);
    await page.goto(`/workflows/${ITEM_ID}?tenant=${TENANT}`);

    const table = page.getByTestId("evidence-table");
    await expect(table).toBeVisible();
    await expect(table).toContainText("Protocol PV-001");
    await expect(table).toContainText("v3");
    await expect(table).toContainText("Validation protocol");
    await expect(page.getByTestId("evidence-document-link")).toHaveAttribute(
      "href",
      `/documents/${DOC_ID}?tenant=${TENANT}`,
    );
  });

  test("offers no upload control and routes users to Documents", async ({ page }) => {
    await mockWorkflow(page, item(), []);
    await page.goto(`/workflows/${ITEM_ID}?tenant=${TENANT}`);

    const section = page.getByTestId("evidence-section");
    // The whole point: no second upload implementation lives here.
    await expect(section.locator('input[type="file"]')).toHaveCount(0);
    await expect(section).toContainText("does not upload files");
    await expect(section.getByRole("link", { name: "Documents" })).toBeVisible();
  });

  test("a caller without document access sees identity but no detail", async ({ page }) => {
    // The backend omits `document` entirely for such a caller.
    await mockWorkflow(page, item(), [evidenceRow(false)]);
    await page.goto(`/workflows/${ITEM_ID}?tenant=${TENANT}`);

    await expect(page.getByTestId("evidence-restricted")).toBeVisible();
    await expect(page.getByTestId("evidence-restricted")).toContainText("no document access");
    // No link is offered, because following it would 403.
    await expect(page.getByTestId("evidence-document-link")).toHaveCount(0);
    // The title must not appear anywhere.
    await expect(page.getByTestId("evidence-section")).not.toContainText("Protocol PV-001");
  });

  test("links a document version and reloads the list", async ({ page }) => {
    let posted: string | null = null;
    await mockWorkflow(page, item(), []);
    await page.route(new RegExp(`/api/regx/v1/workflows/${ITEM_ID}/evidence/$`), async (route) => {
      if (route.request().method() === "POST") {
        posted = route.request().postData();
        return route.fulfill({
          status: 201,
          contentType: "application/json",
          body: JSON.stringify(evidenceRow()),
        });
      }
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(posted ? [evidenceRow()] : []),
      });
    });

    await page.goto(`/workflows/${ITEM_ID}?tenant=${TENANT}`);
    await page.getByTestId("evidence-version-input").fill(VERSION_ID);
    await page.getByTestId("evidence-label-input").fill("Validation protocol");
    await page.getByTestId("evidence-link-submit").click();

    await expect.poll(() => posted).toContain(VERSION_ID);
    await expect(page.getByTestId("evidence-table")).toBeVisible();
  });

  test("evidence is locked outside draft, with an explanation", async ({ page }) => {
    await mockWorkflow(
      page,
      item({ state: "in_review", available_actions: ["approve", "reject"] }),
      [evidenceRow()],
    );
    await page.goto(`/workflows/${ITEM_ID}?tenant=${TENANT}`);

    await expect(page.getByTestId("evidence-locked")).toContainText("under review");
    await expect(page.getByTestId("evidence-form")).toHaveCount(0);
    await expect(page.getByTestId(`unlink-${EVIDENCE_ID}`)).toHaveCount(0);
  });

  test("an approved item states its evidence set is permanent", async ({ page }) => {
    await mockWorkflow(
      page,
      item({ state: "approved", is_terminal: true, available_actions: [] }),
      [evidenceRow()],
    );
    await page.goto(`/workflows/${ITEM_ID}?tenant=${TENANT}`);

    await expect(page.getByTestId("evidence-locked")).toContainText("permanent");
    await expect(page.getByTestId("evidence-form")).toHaveCount(0);
  });

  test("a 409 on link surfaces and reloads rather than guessing", async ({ page }) => {
    await mockWorkflow(page, item(), []);
    await page.route(new RegExp(`/api/regx/v1/workflows/${ITEM_ID}/evidence/$`), async (route) => {
      if (route.request().method() === "POST") {
        return route.fulfill({
          status: 409,
          contentType: "application/json",
          body: JSON.stringify({ detail: "already linked" }),
        });
      }
      return route.fulfill({ status: 200, contentType: "application/json", body: "[]" });
    });

    await page.goto(`/workflows/${ITEM_ID}?tenant=${TENANT}`);
    await page.getByTestId("evidence-version-input").fill(VERSION_ID);
    await page.getByTestId("evidence-link-submit").click();

    await expect(page.getByTestId("evidence-error")).toContainText("Already linked");
  });

  test("unlinks an evidence link", async ({ page }) => {
    let unlinked = false;
    await mockWorkflow(page, item(), []);
    await page.route(new RegExp(`/api/regx/v1/workflows/${ITEM_ID}/evidence/$`), (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(unlinked ? [] : [evidenceRow()]),
      }),
    );
    await page.route(
      new RegExp(`/api/regx/v1/workflows/${ITEM_ID}/evidence/${EVIDENCE_ID}/$`),
      async (route) => {
        unlinked = true;
        return route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify(evidenceRow()),
        });
      },
    );

    await page.goto(`/workflows/${ITEM_ID}?tenant=${TENANT}`);
    await page.getByTestId(`unlink-${EVIDENCE_ID}`).click();

    await expect(page.getByTestId("evidence-empty")).toBeVisible();
  });
});
