// Integrated-origin suite: the company website and the REGX modules answering
// on one host.
//
// Unlike every other spec here, this one needs the REAL stack — the company
// Django container, the REGX backend and nginx — because the whole point is
// that unmocked company pages render from the company's own code and data.
// It therefore only runs when BASE_URL points at the integrated origin:
//
//   docker compose up -d
//   BASE_URL=http://localhost:8080 npx playwright test company-site-integration
//
// Against the default :3000 dev server the company routes do not exist, so
// the suite skips rather than reporting misleading failures.
import { test, expect } from "@playwright/test";

const BASE = process.env["BASE_URL"] ?? "";
const INTEGRATED = /:8080(\/|$)/.test(BASE);

test.skip(
  !INTEGRATED,
  "Requires the integrated stack; run with BASE_URL=http://localhost:8080",
);

// The company homepage builds pandas dataframes over the FDA-483 dataset.
test.setTimeout(120_000);

test.describe("company website served verbatim", () => {
  test("the homepage renders the company's own page, not a rebuild", async ({ page }) => {
    await page.goto("/");
    await expect(page).toHaveTitle(/iTechnicalTools/i);
    await expect(page.locator("nav.custom-navbar")).toBeVisible();
    await expect(page.locator("footer, .footer").first()).toBeVisible();
  });

  test("the navbar carries the company destinations", async ({ page }) => {
    await page.goto("/");
    const nav = page.locator("nav.custom-navbar");
    await expect(nav.getByRole("link", { name: "Audit IQ" })).toBeVisible();
    await expect(
      nav.getByRole("link", { name: "ANDA CTD SmartTemplate" }),
    ).toBeVisible();
    await expect(nav.getByRole("link", { name: "RegX" })).toBeVisible();
  });

  test("no image on the homepage is broken", async ({ page }) => {
    await page.goto("/");
    await page.waitForLoadState("networkidle");
    const broken = await page.evaluate(() =>
      [...document.images]
        .filter((i) => i.complete && i.naturalWidth === 0)
        .map((i) => i.currentSrc || i.src),
    );
    expect(broken, `broken company images:\n${broken.join("\n")}`).toEqual([]);
  });

  for (const path of ["/termsofuse/", "/privacy-policy/", "/about-alpesh/"]) {
    test(`public page ${path} responds and keeps the company chrome`, async ({ page }) => {
      const res = await page.goto(path);
      expect(res?.status()).toBe(200);
      await expect(page.locator("nav.custom-navbar")).toBeVisible();
    });
  }

  test("the demo and contact pages are reachable", async ({ page }) => {
    expect((await page.goto("/ratools/requestdemo"))?.status()).toBe(200);
    expect((await page.goto("/ratools/contactus"))?.status()).toBe(200);
  });

  test("the company login page is the company's own", async ({ page }) => {
    const res = await page.goto("/adminmaster/login/");
    expect(res?.status()).toBe(200);
  });

  test("Audit IQ renders from the company database", async ({ page }) => {
    const res = await page.goto("/aidatabase/auditiq/");
    expect(res?.status()).toBe(200);
  });
});

test.describe("the original /ratools/ RegX landing", () => {
  test("renders the company hero, cards and sidebar untouched", async ({ page }) => {
    await page.goto("/ratools/");
    await expect(page).toHaveTitle(/Technical Tools/i);

    await expect(page.locator(".tt-hero h1")).toHaveText("RegX");
    await expect(page.locator(".tt-hero h2")).toContainText("Withstand Review");
    // The marketing hero and its Three.js canvas belong here and nowhere else.
    await expect(page.locator("#toolsScene")).toHaveCount(1);
    expect(await page.locator(".tt-card").count()).toBeGreaterThan(0);

    await expect(page.locator(".dashboard-sidebar")).toHaveCSS("width", "270px");
    await expect(page.locator("body")).toHaveCSS(
      "background-color",
      "rgb(240, 247, 255)",
    );
  });

  test("the hero GIF loads", async ({ page }) => {
    await page.goto("/ratools/");
    const width = await page.evaluate(() => {
      const img = [...document.images].find((i) => /RegX/i.test(i.src));
      return img ? img.naturalWidth : 0;
    });
    expect(width).toBeGreaterThan(0);
  });

  test("the legacy tools in the sidebar are all present", async ({ page }) => {
    await page.goto("/ratools/");
    for (const label of [
      "ANDA Review Checklist",
      "DMF Review Checklist",
      "Validation Checklist",
      "IIG Clearance Checklist",
      "Size Shape & Score",
    ]) {
      await expect(page.locator(".dashboard-sidebar").getByText(label)).toBeVisible();
    }
  });
});

test.describe("one origin, both applications", () => {
  test("company assets are served from the copied trees", async ({ request }) => {
    for (const path of [
      "/static/assets/css/style.css",
      "/static/assets/vendors/mdi/css/materialdesignicons.min.css",
    ]) {
      expect((await request.get(path)).status(), path).toBe(200);
    }
  });

  test("the REGX shell bundle is served from its own prefix", async ({ request }) => {
    for (const path of [
      "/regx-shell/regx/regx-shell.css",
      "/regx-shell/regx/company-navbar.css",
      "/regx-shell/css/style.css",
      "/regx-shell/itechnical-logo.png",
      "/regx-shell/vendors/mdi/fonts/materialdesignicons-webfont.woff2",
    ]) {
      expect((await request.get(path)).status(), path).toBe(200);
    }
  });

  test("every REGX operational route answers on the same origin", async ({ request }) => {
    for (const path of [
      "/signin",
      "/mfa",
      "/documents",
      "/fda-data/releases",
      "/fda-data/mappings",
      "/fda-data/orange-book",
      "/formulations",
      "/iid-assessments/preview",
      "/iig-checklists",
      "/iig-checklists/executions",
      "/migration-batches",
      "/templates",
      "/template-sources",
      "/tenants",
    ]) {
      expect((await request.get(path)).status(), path).toBe(200);
    }
  });

  test("the REGX API is reachable same-origin and still refuses anonymous callers", async ({
    request,
  }) => {
    expect((await request.get("/api/regx/v1/health/")).status()).toBe(200);
    // Authoritative REGX authorization is unchanged by the integration: an
    // unauthenticated tenant listing must not succeed.
    const tenants = await request.get("/api/regx/v1/tenants/");
    expect([401, 403]).toContain(tenants.status());
  });

  test("an unknown path falls through to the company site, not the frontend", async ({
    request,
  }) => {
    const res = await request.get("/definitely-not-a-real-page", {
      maxRedirects: 0,
      failOnStatusCode: false,
    });
    // Django answers 404 for its own unknown routes; what matters is that the
    // default route belongs to the company site.
    expect(res.status()).toBe(404);
    expect(res.headers()["x-powered-by"]).toBeUndefined();
  });
});

test.describe("the REGX modules wear the company shell", () => {
  // These are HTML-level checks on purpose. Opening an operational page
  // without a REGX session redirects to /signin — that redirect is the
  // authorization working, so a rendered-DOM assertion here would be
  // measuring the sign-in page. The server-rendered markup is what proves the
  // shell is applied, and it is the same markup an authenticated user gets.

  test("an operational page is server-rendered inside the company chrome", async ({
    request,
  }) => {
    const html = await (await request.get("/documents")).text();
    expect(html).toContain("custom-navbar");
    expect(html).toContain("dashboard-sidebar");
    expect(html).toContain("dashboard-main-panel");
    // The company nav destinations travel with the shell.
    expect(html).toContain("/aidatabase/auditiq/");
    expect(html).toContain("/ratools/");
  });

  test("it loads the company design system in the landing's own order", async ({
    request,
  }) => {
    const html = await (await request.get("/documents")).text();
    const order = [
      "/regx-shell/vendors/mdi/css/materialdesignicons.min.css",
      "/regx-shell/vendors/ti-icons/css/themify-icons.css",
      "/regx-shell/vendors/css/vendor.bundle.base.css",
      "/regx-shell/vendors/font-awesome/css/font-awesome.min.css",
      "/regx-shell/css/style.css",
      "/regx-shell/regx/regx-shell.css",
      // Last: navbar.html's <style> is later in the document than the
      // template's own, so its Inter body font must win here too.
      "/regx-shell/regx/company-navbar.css",
    ];
    const positions = order.map((href) => html.indexOf(href));
    expect(positions.every((p) => p >= 0), "a shell stylesheet is missing").toBe(true);
    const sorted = [...positions].sort((a, b) => a - b);
    expect(positions, "shell stylesheets load out of order").toEqual(sorted);
  });

  test("the landing does not carry the operational chrome's assumptions", async ({
    page,
  }) => {
    // The hero lives on /ratools/ only; the operational pages must not repeat
    // it (Phase 10). Verified from the landing side here.
    await page.goto("/ratools/");
    await expect(page.locator(".tt-hero")).toHaveCount(1);
    const operationalHtml = await (
      await page.request.get("/documents")
    ).text();
    expect(operationalHtml).not.toContain('class="tt-hero"');
    expect(operationalHtml).not.toContain('id="toolsScene"');
  });
});
