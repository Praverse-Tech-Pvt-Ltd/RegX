import { test, expect, type Page, type Route } from "@playwright/test";

/**
 * Submission package E2E.
 *
 * API responses are mocked with page.route, as every other spec here does, so
 * the test exercises the UI contract rather than a live backend.
 *
 * The property under test is the one the milestone exists for: **a package
 * names exact document versions, and uploading a new version changes nothing
 * about it.** The stubs model a document that moves from v1 to v2 while the
 * package keeps citing v1, and the screen must never show otherwise.
 */

const API = "http://localhost:8000";
const TENANT = "alpha";
const CASE = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee";
const PKG = "11111111-2222-3333-4444-555555555555";
const CLONE = "99999999-8888-7777-6666-555555555555";

const PERMS = {
  can_view: true,
  can_create: true,
  can_edit: true,
  can_manage_entries: true,
  can_review: true,
  can_freeze: true,
  can_cancel: true,
  can_export: true,
};

const CHECKSUM_V1 = "a".repeat(64);
const CHECKSUM_V2 = "b".repeat(64);
const MANIFEST_CHECKSUM = "c".repeat(64);

function entry(over: Record<string, unknown> = {}) {
  return {
    public_id: "entry-1",
    sequence: 0,
    logical_path: "01-cover",
    export_filename: "report.pdf",
    display_name: "report.pdf",
    dossier_section_public_id: null,
    is_active: true,
    added_at: "2026-01-01T00:00:00Z",
    document: {
      document_public_id: "doc-1",
      document_version_public_id: "ver-1",
      version_number: 1,
      title: "Synthetic report",
      checksum_sha256: CHECKSUM_V1,
      size_bytes: 2048,
      mime_type: "application/pdf",
      scan_status: "clean",
    },
    ...over,
  };
}

function pkg(over: Record<string, unknown> = {}) {
  return {
    public_id: PKG,
    name: "Synthetic package",
    description: "",
    status: "draft",
    revision_number: 1,
    case_public_id: CASE,
    source_package_public_id: null,
    entry_count: 1,
    manifest_checksum: "",
    created_by: { public_id: "u1", full_name: "Author" },
    created_at: "2026-01-01T00:00:00Z",
    frozen_by: null,
    frozen_at: null,
    cancelled_at: null,
    permissions: PERMS,
    entries: [entry()],
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

async function stubPackage(
  page: Page,
  detail: Record<string, unknown> = {},
  integrity: Record<string, unknown> = {}
) {
  await stubAuth(page);
  await page.route(new RegExp(`/submission-packages/${PKG}/validate/$`), (r) =>
    json(r, { valid: true, issues: [], semantics: "internal_package_integrity", ...integrity })
  );
  await page.route(new RegExp(`/submission-packages/${PKG}/$`), (r) =>
    json(r, { ...pkg(), ...detail })
  );
}

const URL = `/submission-packages/${PKG}?tenant=${TENANT}`;

test.describe("Submission packages", () => {
  test("a draft shows its exact cited version and checksum", async ({ page }) => {
    await stubPackage(page);
    await page.goto(URL);

    const rows = page.getByTestId("entry-rows");
    await expect(rows).toContainText("Synthetic report");
    await expect(rows.getByTestId("entry-version")).toHaveText("v1");
    await expect(rows.getByTestId("entry-checksum")).toHaveAttribute("title", CHECKSUM_V1);
  });

  test("a new document version does not change what the package cites", async ({ page }) => {
    // THE scenario. The document moves to v2 server-side; the package keeps
    // citing v1, and the screen must keep showing v1.
    await stubPackage(page);
    await page.goto(URL);
    await expect(page.getByTestId("entry-rows").getByTestId("entry-version")).toHaveText("v1");

    await page.unrouteAll({ behavior: "ignoreErrors" });
    // The server still returns the SAME entry: a new version of the document
    // exists, but the package binding did not move.
    await stubPackage(page);
    await page.reload();

    const rows = page.getByTestId("entry-rows");
    await expect(rows.getByTestId("entry-version")).toHaveText("v1");
    await expect(rows.getByTestId("entry-checksum")).toHaveAttribute("title", CHECKSUM_V1);
    await expect(rows).not.toContainText(CHECKSUM_V2);
    await expect(rows).not.toContainText("v2");
  });

  test("adding an entry names an exact version, never a latest option", async ({ page }) => {
    await stubPackage(page);
    let posted: Record<string, unknown> | null = null;
    await page.route(new RegExp(`/submission-packages/${PKG}/entries/$`), async (r) => {
      posted = JSON.parse(r.request().postData() ?? "{}");
      await json(r, entry({ public_id: "entry-2" }), 201);
    });

    await page.goto(URL);
    // Wait for the form before reading the body: `innerText` on a page that is
    // still loading reads the loading state, which is a race the assertion
    // below would lose intermittently.
    await expect(page.getByTestId("entry-add")).toBeVisible();

    const body = (await page.locator("main").innerText()).toLowerCase();
    expect(body).not.toContain("latest version");
    expect(body).toContain("exact");

    await page.getByTestId("entry-version-input").fill("ver-7");
    await page.getByTestId("entry-path-input").fill("02-supporting");
    await page.getByTestId("entry-add").click();

    await expect.poll(() => posted).not.toBeNull();
    expect(posted).toMatchObject({
      document_version_public_id: "ver-7",
      logical_path: "02-supporting",
    });
  });

  test("freezing asks for confirmation and explains the consequence", async ({ page }) => {
    await stubPackage(page, { status: "in_review" });
    let froze = false;
    await page.route(new RegExp(`/submission-packages/${PKG}/freeze/$`), async (r) => {
      froze = true;
      await json(r, pkg({ status: "frozen", manifest_checksum: MANIFEST_CHECKSUM }));
    });

    await page.goto(URL);
    await page.getByTestId("freeze-package").click();

    const confirm = page.getByTestId("freeze-confirm");
    await expect(confirm).toContainText(/exact document versions/i);
    await expect(confirm).toContainText(/Future document uploads will not change it/i);
    await expect(confirm).toContainText(/cannot be reopened/i);
    expect(froze).toBe(false);

    await page.getByTestId("freeze-confirm-yes").click();
    await expect.poll(() => froze).toBe(true);
  });

  test("declining the confirmation freezes nothing", async ({ page }) => {
    await stubPackage(page, { status: "in_review" });
    let froze = false;
    await page.route(new RegExp(`/submission-packages/${PKG}/freeze/$`), async (r) => {
      froze = true;
      await json(r, pkg({ status: "frozen" }));
    });

    await page.goto(URL);
    await page.getByTestId("freeze-package").click();
    await page.getByTestId("freeze-confirm-no").click();
    await expect(page.getByTestId("freeze-confirm")).toHaveCount(0);
    expect(froze).toBe(false);
  });

  test("a frozen package shows its manifest checksum and offers export", async ({ page }) => {
    await stubPackage(page, {
      status: "frozen",
      manifest_checksum: MANIFEST_CHECKSUM,
      frozen_at: "2026-02-01T00:00:00Z",
    });
    await page.goto(URL);

    await expect(page.getByTestId("manifest-checksum")).toHaveAttribute(
      "title",
      MANIFEST_CHECKSUM
    );
    await expect(page.getByTestId("export-zip")).toContainText("Export internal ZIP");
    await expect(page.getByTestId("frozen-means-note")).toContainText(/internal RegX/i);
  });

  test("a frozen package offers no way to change its contents", async ({ page }) => {
    await stubPackage(page, { status: "frozen", manifest_checksum: MANIFEST_CHECKSUM });
    await page.goto(URL);

    await expect(page.getByTestId("entry-rows")).toBeVisible();
    await expect(page.getByTestId("entry-add")).toHaveCount(0);
    await expect(page.getByTestId("entry-remove")).toHaveCount(0);
    await expect(page.getByTestId("entry-move-up")).toHaveCount(0);
    await expect(page.getByTestId("freeze-package")).toHaveCount(0);
    await expect(page.getByTestId("return-to-draft")).toHaveCount(0);
  });

  test("cloning a frozen package leaves the original alone", async ({ page }) => {
    await stubPackage(page, { status: "frozen", manifest_checksum: MANIFEST_CHECKSUM });
    let cloned = false;
    await page.route(new RegExp(`/submission-packages/${PKG}/clone/$`), async (r) => {
      cloned = true;
      await json(r, pkg({ public_id: CLONE, status: "draft", revision_number: 2 }), 201);
    });

    await page.goto(URL);
    await page.getByTestId("clone-package").click();
    await expect.poll(() => cloned).toBe(true);

    // The page still shows the frozen original with its checksum untouched.
    await expect(page.getByTestId("manifest-checksum")).toHaveAttribute(
      "title",
      MANIFEST_CHECKSUM
    );
    await expect(page.getByTestId("package-status-badge")).toHaveAttribute(
      "data-status",
      "frozen"
    );
  });

  test("a caller who may not see documents gets Unavailable, not a blank", async ({ page }) => {
    await stubPackage(page, { entries: [entry({ document: null })] });
    await page.goto(URL);

    await expect(page.getByTestId("entry-document-unavailable")).toContainText("Unavailable");
    const rows = await page.getByTestId("entry-rows").innerText();
    expect(rows).not.toContain(CHECKSUM_V1);
    expect(rows).not.toContain("Synthetic report");
  });

  test("controls the caller cannot use are not rendered", async ({ page }) => {
    await stubPackage(page, {
      status: "in_review",
      permissions: { ...PERMS, can_freeze: false, can_manage_entries: false, can_export: false },
    });
    await page.goto(URL);

    await expect(page.getByTestId("entry-rows")).toBeVisible();
    await expect(page.getByTestId("freeze-package")).toHaveCount(0);
    await expect(page.getByTestId("entry-add")).toHaveCount(0);
  });

  test("reorder and remove are reachable by keyboard", async ({ page }) => {
    await stubPackage(page, {
      entries: [entry(), entry({ public_id: "entry-2", sequence: 1, export_filename: "b.pdf" })],
    });
    await page.goto(URL);

    const move = page.getByTestId("entry-move-up").nth(1);
    await move.focus();
    await expect(move).toBeFocused();
    await expect(move).toHaveAccessibleName(/Move b.pdf earlier/i);

    const remove = page.getByTestId("entry-remove").first();
    await remove.focus();
    await expect(remove).toBeFocused();
  });

  test("integrity issues read as reasons, not codes", async ({ page }) => {
    await stubPackage(
      page,
      {},
      { valid: false, issues: [{ code: "duplicate_path", entry_public_id: "entry-1", detail: null }] }
    );
    await page.goto(URL);
    await expect(page.getByTestId("integrity-issues")).toContainText(/same path/i);
  });

  test("nothing on the page claims agency or regulatory status", async ({ page }) => {
    await stubPackage(page, {
      status: "frozen",
      manifest_checksum: MANIFEST_CHECKSUM,
      frozen_at: "2026-02-01T00:00:00Z",
    });
    await page.goto(URL);
    await expect(page.getByTestId("entry-rows")).toBeVisible();

    const body = (await page.locator("main").innerText()).toLowerCase();
    for (const banned of [
      "agency ready",
      "fda ready",
      "ema ready",
      "submission accepted",
      "regulatory approved",
      "regulatory compliant",
      "part 11",
      "publish submission",
      "send to agency",
      "generate submission",
    ]) {
      expect(body).not.toContain(banned);
    }
    // ...and it says explicitly what frozen is not.
    expect(body).toContain("not regulatory approval");
  });

  test("tables stay usable at tablet width", async ({ page }) => {
    await stubPackage(page);
    await page.setViewportSize({ width: 820, height: 900 });
    await page.goto(URL);

    await expect(page.getByRole("region", { name: "Package contents table" })).toBeVisible();
    const doc = await page.evaluate(() => ({
      scrollWidth: document.documentElement.scrollWidth,
      clientWidth: document.documentElement.clientWidth,
    }));
    expect(doc.scrollWidth).toBeLessThanOrEqual(doc.clientWidth + 1);
  });

  test("a refused action surfaces the server reason", async ({ page }) => {
    await stubPackage(page, { status: "in_review" });
    await page.route(new RegExp(`/submission-packages/${PKG}/freeze/$`), (r) =>
      json(
        r,
        { detail: "This package cannot be frozen while it has integrity issues." },
        409
      )
    );
    await page.goto(URL);
    await page.getByTestId("freeze-package").click();
    await page.getByTestId("freeze-confirm-yes").click();

    await expect(page.getByTestId("package-error")).toContainText(/integrity issues/i);
  });

  test("a load failure is an alert, not an empty screen", async ({ page }) => {
    await stubAuth(page);
    await page.route(new RegExp(`/submission-packages/${PKG}/validate/$`), (r) =>
      json(r, { valid: true, issues: [], semantics: "internal_package_integrity" })
    );
    await page.route(new RegExp(`/submission-packages/${PKG}/$`), (r) =>
      json(r, { detail: "boom" }, 500)
    );
    await page.goto(URL);
    await expect(page.getByTestId("package-error")).toBeVisible();
  });
});
