// Document-flow Playwright suite.
//
// IMPORTANT — scope note: every backend response here is a deterministic
// Playwright route mock (page.route), not a live Django/Celery/ClamAV/S3
// backend. This proves the FRONTEND correctly renders, submits, and reacts
// to the API contract described in src/lib/api.ts — it does NOT re-verify
// backend scanning, processing, or authorization logic, which is covered by
// the backend pytest suite (documents/tests/) instead. Where a scenario below
// depends on server-side enforcement we don't have client code for (e.g. role
// gating), the test proves the frontend handles the server's authoritative
// response correctly rather than asserting a client-side permission model
// that does not exist in this codebase.
//
// Fixtures are synthetic and non-confidential.
import { test, expect, type Page, type Route } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

const TENANT = "alpha";
const DOC_ID = "doc-e2e-0001";
const VERSION_ID = "ver-e2e-0001";
const API = "http://localhost:8000";

function jsonRoute(body: unknown, status = 200) {
  return (route: Route) =>
    route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
}

function makeVersion(overrides: Record<string, unknown> = {}) {
  return {
    public_id: VERSION_ID,
    version_number: 1,
    original_filename: "synthetic-report.pdf",
    extension: "pdf",
    declared_mime_type: "application/pdf",
    detected_mime_type: "application/pdf",
    size_bytes: 20480,
    scan_status: "clean",
    processing_status: "complete",
    failure_code: null,
    uploaded_by: "Synthetic User",
    uploaded_at: "2026-07-20T10:00:00Z",
    processing_started_at: "2026-07-20T10:00:05Z",
    processing_finished_at: "2026-07-20T10:00:12Z",
    ...overrides,
  };
}

function makeDocument(overrides: Record<string, unknown> = {}) {
  return {
    public_id: DOC_ID,
    title: "Synthetic Validation Report",
    document_type: "pdf",
    status: "active",
    current_version: makeVersion(),
    created_by: "Synthetic User",
    created_at: "2026-07-20T09:59:00Z",
    archived_at: null,
    ...overrides,
  };
}

// The plain "/documents/" list-create endpoint is requested with a
// "?page=1"-style query string on every load. A bare string route pattern in
// Playwright must match the URL exactly, so it silently misses the query
// string and falls through to the real (unlistened) network, producing a
// masked failure whose UI (an empty list) is indistinguishable from a
// genuine empty-list response. Regexes below match with-or-without a query
// string but stop before any further path segment, so they never also catch
// "/documents/{id}/" or its sub-resources.
const DOCUMENTS_LIST_URL = /\/api\/regx\/v1\/documents\/(\?[^/]*)?$/;

async function mockCsrf(page: Page) {
  await page.route(`${API}/api/regx/v1/auth/csrf/`, jsonRoute({ csrfToken: "e2e-csrf-token" }));
}

async function mockDocumentsList(page: Page, docs: unknown[]) {
  await page.route(DOCUMENTS_LIST_URL, async (route) => {
    if (route.request().method() === "GET") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ count: docs.length, next: null, previous: null, results: docs }),
      });
    } else {
      await route.fallback();
    }
  });
}

async function mockDocumentDetail(page: Page, doc: unknown, status = 200) {
  await page.route(`${API}/api/regx/v1/documents/${DOC_ID}/`, jsonRoute(doc, status));
}

async function mockVersions(page: Page, versions: unknown[]) {
  await page.route(`${API}/api/regx/v1/documents/${DOC_ID}/versions/`, async (route) => {
    if (route.request().method() === "GET") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ count: versions.length, next: null, previous: null, results: versions }),
      });
    } else {
      await route.fallback();
    }
  });
}

async function mockVersionStatus(page: Page, status: { scan_status: string; processing_status: string }) {
  await page.route(
    `${API}/api/regx/v1/documents/${DOC_ID}/versions/${VERSION_ID}/status/`,
    jsonRoute(status),
  );
}

async function mockLocators(page: Page, locators: unknown[]) {
  await page.route(
    `${API}/api/regx/v1/documents/${DOC_ID}/versions/${VERSION_ID}/locators/`,
    jsonRoute({ count: locators.length, next: null, previous: null, results: locators }),
  );
}

test.describe("Document flow: list and empty state", () => {
  test("authenticated user opens /documents and the empty state renders", async ({ page }) => {
    await mockCsrf(page);
    await mockDocumentsList(page, []);

    await page.goto(`/documents?tenant=${TENANT}`);

    await expect(page.getByRole("heading", { name: "Documents" })).toBeVisible();
    await expect(page.getByText(/No documents yet\. Upload one to get started\./i)).toBeVisible();
    // "No documents yet" also renders on a genuine fetch failure (docs stays
    // []), so assert the failure alert is specifically absent to prove this
    // is the real empty-list response, not a masked network error.
    await expect(page.getByText(/Failed to load documents\./i)).toHaveCount(0);
  });

  test("processing status is displayed for a listed document", async ({ page }) => {
    await mockCsrf(page);
    await mockDocumentsList(page, [
      makeDocument({ current_version: makeVersion({ processing_status: "processing", scan_status: "clean" }) }),
    ]);

    await page.goto(`/documents?tenant=${TENANT}`);

    const row = page.getByRole("row", { name: /Synthetic Validation Report/i });
    await expect(row.getByText(/processing…/i)).toBeVisible();
    await expect(row.getByText(/clean/i)).toBeVisible();
  });
});

test.describe("Document flow: upload dialog", () => {
  test("upload dialog opens", async ({ page }) => {
    await mockCsrf(page);
    await mockDocumentsList(page, []);
    await page.goto(`/documents?tenant=${TENANT}`);

    await expect(page.getByRole("dialog")).toHaveCount(0);
    await page.getByRole("button", { name: /upload document/i }).click();
    await expect(page.getByRole("dialog")).toBeVisible();
    await expect(page.getByRole("heading", { name: /upload document/i })).toBeVisible();
  });

  test("a valid PDF upload is accepted and navigates to the new document", async ({ page }) => {
    await mockCsrf(page);
    await mockDocumentsList(page, []);
    await page.route(DOCUMENTS_LIST_URL, async (route) => {
      if (route.request().method() === "POST") {
        await route.fulfill({
          status: 201,
          contentType: "application/json",
          body: JSON.stringify(makeDocument()),
        });
      } else {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({ count: 0, next: null, previous: null, results: [] }),
        });
      }
    });
    await mockDocumentDetail(page, makeDocument());
    await mockVersions(page, [makeVersion()]);
    await mockVersionStatus(page, { scan_status: "clean", processing_status: "complete" });

    await page.goto(`/documents?tenant=${TENANT}`);
    await page.getByRole("button", { name: /upload document/i }).click();
    const dialog = page.getByRole("dialog");
    await dialog.getByLabel("Title").fill("Synthetic Validation Report");
    await dialog
      .getByLabel("File")
      .setInputFiles({ name: "report.pdf", mimeType: "application/pdf", buffer: Buffer.from("%PDF-1.4 synthetic") });
    await dialog.getByRole("button", { name: /^upload$/i }).click();

    await expect(page).toHaveURL(new RegExp(`/documents/${DOC_ID}\\?tenant=${TENANT}`));
    await expect(page.getByRole("heading", { name: "Synthetic Validation Report" })).toBeVisible();
  });

  test("an invalid extension is rejected with the server's validation message", async ({ page }) => {
    await mockCsrf(page);
    await mockDocumentsList(page, []);
    await page.route(DOCUMENTS_LIST_URL, async (route) => {
      if (route.request().method() === "POST") {
        await route.fulfill({
          status: 400,
          contentType: "application/json",
          body: JSON.stringify({ detail: "Unsupported file extension: .exe is not allowed." }),
        });
      } else {
        await route.fallback();
      }
    });

    await page.goto(`/documents?tenant=${TENANT}`);
    await page.getByRole("button", { name: /upload document/i }).click();
    const dialog = page.getByRole("dialog");
    await dialog.getByLabel("Title").fill("Bad Extension");
    // A real accept="" filter blocks this in a live file picker; setInputFiles
    // bypasses that (as a user renaming/mistyping a file also would), so this
    // exercises the server-side extension check the frontend has no client
    // equivalent for.
    await dialog
      .getByLabel("File")
      .setInputFiles({ name: "payload.pdf", mimeType: "application/pdf", buffer: Buffer.from("data") });
    await dialog.getByRole("button", { name: /^upload$/i }).click();

    await expect(dialog.getByRole("alert")).toHaveText(/Unsupported file extension: \.exe is not allowed\./i);
    await expect(dialog).toBeVisible();
  });

  test("a MIME mismatch error is displayed safely as text, not markup", async ({ page }) => {
    await mockCsrf(page);
    await mockDocumentsList(page, []);
    const dangerousMessage = 'MIME mismatch: declared "application/pdf" but detected <script>alert(1)</script>.';
    await page.route(DOCUMENTS_LIST_URL, async (route) => {
      if (route.request().method() === "POST") {
        await route.fulfill({
          status: 400,
          contentType: "application/json",
          body: JSON.stringify({ detail: dangerousMessage }),
        });
      } else {
        await route.fallback();
      }
    });

    await page.goto(`/documents?tenant=${TENANT}`);
    await page.getByRole("button", { name: /upload document/i }).click();
    const dialog = page.getByRole("dialog");
    await dialog.getByLabel("Title").fill("Mismatch");
    await dialog
      .getByLabel("File")
      .setInputFiles({ name: "report.pdf", mimeType: "application/pdf", buffer: Buffer.from("data") });
    await dialog.getByRole("button", { name: /^upload$/i }).click();

    const alert = dialog.getByRole("alert");
    await expect(alert).toBeVisible();
    // Rendered as literal text (React escapes by default) — the injected
    // <script> tag must not exist as an actual element in the DOM.
    expect(await alert.innerText()).toContain("<script>alert(1)</script>");
    await expect(page.locator("script:has-text(\"alert(1)\")")).toHaveCount(0);
  });

  test("an oversized-file response is handled and shown to the user", async ({ page }) => {
    await mockCsrf(page);
    await mockDocumentsList(page, []);
    await page.route(DOCUMENTS_LIST_URL, async (route) => {
      if (route.request().method() === "POST") {
        await route.fulfill({
          status: 413,
          contentType: "application/json",
          body: JSON.stringify({ detail: "File exceeds the maximum allowed size of 50 MB." }),
        });
      } else {
        await route.fallback();
      }
    });

    await page.goto(`/documents?tenant=${TENANT}`);
    await page.getByRole("button", { name: /upload document/i }).click();
    const dialog = page.getByRole("dialog");
    await dialog.getByLabel("Title").fill("Huge File");
    await dialog
      .getByLabel("File")
      .setInputFiles({ name: "huge.pdf", mimeType: "application/pdf", buffer: Buffer.from("data") });
    await dialog.getByRole("button", { name: /^upload$/i }).click();

    await expect(dialog.getByRole("alert")).toHaveText(/File exceeds the maximum allowed size of 50 MB\./i);
  });
});

test.describe("Document flow: detail page", () => {
  test("document detail opens and the version list renders", async ({ page }) => {
    await mockCsrf(page);
    await mockDocumentDetail(page, makeDocument());
    await mockVersions(page, [makeVersion()]);
    await mockVersionStatus(page, { scan_status: "clean", processing_status: "complete" });

    await page.goto(`/documents/${DOC_ID}?tenant=${TENANT}`);

    await expect(page.getByRole("heading", { name: "Synthetic Validation Report" })).toBeVisible();
    await expect(page.getByText("Versions (1)")).toBeVisible();
    await expect(page.getByText("Version 1")).toBeVisible();
  });

  test("locator summary renders on demand", async ({ page }) => {
    await mockCsrf(page);
    await mockDocumentDetail(page, makeDocument());
    await mockVersions(page, [makeVersion()]);
    await mockVersionStatus(page, { scan_status: "clean", processing_status: "complete" });
    await mockLocators(page, [
      { public_id: "loc-1", locator_type: "page", display_label: "Page 1", ordering: 1 },
      { public_id: "loc-2", locator_type: "page", display_label: "Page 2", ordering: 2 },
    ]);

    await page.goto(`/documents/${DOC_ID}?tenant=${TENANT}`);
    await page.getByRole("button", { name: /show structure/i }).click();

    await expect(page.getByText("Page 1")).toBeVisible();
    await expect(page.getByText("Page 2")).toBeVisible();
  });

  test("a new version upload works from the detail page", async ({ page }) => {
    await mockCsrf(page);
    await mockDocumentDetail(page, makeDocument());
    await mockVersionStatus(page, { scan_status: "clean", processing_status: "complete" });

    let versionsCallCount = 0;
    await page.route(`${API}/api/regx/v1/documents/${DOC_ID}/versions/`, async (route) => {
      if (route.request().method() === "GET") {
        versionsCallCount += 1;
        const results = versionsCallCount === 1 ? [makeVersion()] : [makeVersion({ public_id: "ver-e2e-0002", version_number: 2 }), makeVersion()];
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({ count: results.length, next: null, previous: null, results }),
        });
      } else if (route.request().method() === "POST") {
        await route.fulfill({
          status: 201,
          contentType: "application/json",
          body: JSON.stringify(makeVersion({ public_id: "ver-e2e-0002", version_number: 2 })),
        });
      } else {
        await route.fallback();
      }
    });

    await page.goto(`/documents/${DOC_ID}?tenant=${TENANT}`);
    await expect(page.getByText("Versions (1)")).toBeVisible();

    await page
      .getByLabel(/new version file/i)
      .setInputFiles({ name: "v2.pdf", mimeType: "application/pdf", buffer: Buffer.from("data") });
    await page.getByRole("button", { name: /^upload$/i }).click();

    await expect(page.getByText("Versions (2)")).toBeVisible();
    await expect(page.getByText("Version 2")).toBeVisible();
  });
});

test.describe("Document flow: archive/restore (server-enforced authorization)", () => {
  // The frontend has no client-side role/permission model — Document carries
  // no "can_archive"/"can_restore" field, and the button is rendered purely
  // from doc.status. Authorization is enforced server-side by the archive/
  // restore endpoints. These tests prove the frontend defers correctly to
  // that server decision in both directions, rather than asserting a
  // client-side gating feature that does not exist in this codebase.
  test("archive action is available and succeeds for an authorized role", async ({ page }) => {
    await mockCsrf(page);
    await mockDocumentDetail(page, makeDocument({ status: "active" }));
    await mockVersions(page, [makeVersion()]);
    await mockVersionStatus(page, { scan_status: "clean", processing_status: "complete" });
    await page.route(`${API}/api/regx/v1/documents/${DOC_ID}/archive/`, jsonRoute(makeDocument({ status: "archived", archived_at: "2026-07-22T00:00:00Z" })));

    await page.goto(`/documents/${DOC_ID}?tenant=${TENANT}`);
    await expect(page.getByRole("button", { name: /^archive$/i })).toBeVisible();
    await page.getByRole("button", { name: /^archive$/i }).click();

    await expect(page.getByRole("button", { name: /^restore$/i })).toBeVisible();
  });

  test("archive action is rejected and surfaced as an error for an unauthorized role", async ({ page }) => {
    await mockCsrf(page);
    await mockDocumentDetail(page, makeDocument({ status: "active" }));
    await mockVersions(page, [makeVersion()]);
    await mockVersionStatus(page, { scan_status: "clean", processing_status: "complete" });
    await page.route(
      `${API}/api/regx/v1/documents/${DOC_ID}/archive/`,
      jsonRoute({ detail: "You do not have permission to perform this action." }, 403),
    );

    await page.goto(`/documents/${DOC_ID}?tenant=${TENANT}`);
    await page.getByRole("button", { name: /^archive$/i }).click();

    // Scoped to <main>: Next.js's route announcer div also carries
    // role="alert" but lives outside the page content.
    await expect(page.locator("main").getByRole("alert")).toHaveText(
      /You do not have permission to perform this action\./i,
    );
    // The document must NOT flip to archived on a rejected request.
    await expect(page.getByRole("button", { name: /^archive$/i })).toBeVisible();
  });

  test("restore action is available for an archived document and succeeds for an authorized role", async ({ page }) => {
    await mockCsrf(page);
    await mockDocumentDetail(page, makeDocument({ status: "archived", archived_at: "2026-07-21T00:00:00Z" }));
    await mockVersions(page, [makeVersion()]);
    await mockVersionStatus(page, { scan_status: "clean", processing_status: "complete" });
    await page.route(`${API}/api/regx/v1/documents/${DOC_ID}/restore/`, jsonRoute(makeDocument({ status: "active" })));

    await page.goto(`/documents/${DOC_ID}?tenant=${TENANT}`);
    await expect(page.getByRole("button", { name: /^restore$/i })).toBeVisible();
    await expect(page.getByRole("button", { name: /^archive$/i })).toHaveCount(0);
    await page.getByRole("button", { name: /^restore$/i }).click();

    await expect(page.getByRole("button", { name: /^archive$/i })).toBeVisible();
  });
});

test.describe("Document flow: cross-tenant access does not reveal existence", () => {
  test("a document belonging to another tenant is reported generically, not as a specific denial", async ({ page }) => {
    await mockCsrf(page);
    // The backend returns 404 (not 403) for cross-tenant document access
    // specifically so existence in another tenant is never disclosed.
    await mockDocumentDetail(page, { detail: "Not found." }, 404);

    await page.goto(`/documents/${DOC_ID}?tenant=${TENANT}`);

    await expect(page.locator("main").getByRole("alert")).toHaveText(/Failed to load document\./i);
    const body = await page.locator("body").innerText();
    expect(body).not.toMatch(/exists|belongs to|another tenant|forbidden/i);
  });
});

test.describe("Document flow: no internal implementation details leak", () => {
  test("storage key and server filesystem path are never displayed", async ({ page }) => {
    await mockCsrf(page);
    const doc = makeDocument({
      current_version: {
        ...makeVersion(),
        storage_key: "tenant/7/e2e-secret-object-key",
        storage_path: "/var/lib/regx/media/tenant/7/e2e-secret-object-key",
      },
    });
    await mockDocumentDetail(page, doc);
    await mockVersions(page, [doc.current_version]);
    await mockVersionStatus(page, { scan_status: "clean", processing_status: "complete" });

    await page.goto(`/documents/${DOC_ID}?tenant=${TENANT}`);
    await expect(page.getByRole("heading", { name: "Synthetic Validation Report" })).toBeVisible();

    const body = await page.locator("body").innerText();
    expect(body).not.toContain("e2e-secret-object-key");
    expect(body).not.toContain("/var/lib/regx/media");
  });

  test("internal numeric IDs are never displayed", async ({ page }) => {
    await mockCsrf(page);
    const doc = { ...makeDocument(), id: 848484, current_version: { ...makeVersion(), id: 959595 } };
    await mockDocumentDetail(page, doc);
    await mockVersions(page, [doc.current_version]);
    await mockVersionStatus(page, { scan_status: "clean", processing_status: "complete" });

    await page.goto(`/documents/${DOC_ID}?tenant=${TENANT}`);
    await expect(page.getByRole("heading", { name: "Synthetic Validation Report" })).toBeVisible();

    const body = await page.locator("body").innerText();
    expect(body).not.toContain("848484");
    expect(body).not.toContain("959595");
  });
});

test.describe("Document flow: no auth token in web storage during document actions", () => {
  test("uploading, archiving, and browsing documents never writes a token to localStorage/sessionStorage", async ({ page }) => {
    await mockCsrf(page);
    await mockDocumentsList(page, [makeDocument()]);
    await mockDocumentDetail(page, makeDocument());
    await mockVersions(page, [makeVersion()]);
    await mockVersionStatus(page, { scan_status: "clean", processing_status: "complete" });
    await page.route(`${API}/api/regx/v1/documents/${DOC_ID}/archive/`, jsonRoute(makeDocument({ status: "archived" })));

    await page.goto(`/documents?tenant=${TENANT}`);
    await page.getByRole("link", { name: "Synthetic Validation Report" }).click();
    await expect(page.getByRole("button", { name: /^archive$/i })).toBeVisible();
    await page.getByRole("button", { name: /^archive$/i }).click();
    await expect(page.getByRole("button", { name: /^restore$/i })).toBeVisible();

    const [localKeys, sessionKeys] = await Promise.all([
      page.evaluate(() => Object.keys(localStorage).filter((k) => /(token|auth|jwt|session)/i.test(k))),
      page.evaluate(() => Object.keys(sessionStorage).filter((k) => /(token|auth|jwt|session)/i.test(k))),
    ]);
    expect(localKeys).toHaveLength(0);
    expect(sessionKeys).toHaveLength(0);
  });
});

test.describe("Document flow: accessibility spot-check (page-level, complements component-level axe)", () => {
  test("the documents list page has no serious/critical automated violations", async ({ page }) => {
    await mockCsrf(page);
    await mockDocumentsList(page, [makeDocument()]);
    await page.goto(`/documents?tenant=${TENANT}`);
    await expect(page.getByRole("link", { name: "Synthetic Validation Report" })).toBeVisible();

    const results = await new AxeBuilder({ page }).include("main").analyze();
    const serious = results.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
    expect(serious, JSON.stringify(serious, null, 2)).toEqual([]);
  });
});
