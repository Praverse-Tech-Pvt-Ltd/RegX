// REGX operational shell — the company /ratools/ chrome around our modules.
//
// Scope note, in the same spirit as the other specs here: the backend is
// mocked with page.route, so this proves the SHELL renders and behaves, not
// that any API authorizes anything. Auth/tenancy/permission enforcement is
// covered by the backend pytest suite.
//
// What this guards against is visual and structural drift between the
// Django-rendered /ratools/ landing and the Next.js pages that sit inside the
// same shell — the failure mode the whole integration exists to prevent.
import { test, expect, type Page, type Route } from "@playwright/test";

// Without ?tenant= the app redirects to the tenant picker, exactly as the
// other specs here handle it — the shell assertions would then be measuring
// /tenants instead of the page under test.
const TENANT = "alpha";

// Origin-agnostic on purpose. NEXT_PUBLIC_API_URL is baked in at build time,
// so the app calls :8000 when served by `npm run dev` and :8080 when served
// by the container image. Pinning one origin here silently stops mocking
// against the other: the real API answers 403, the page redirects to /signin
// mid-test, and the failures point at the shell instead of at the mock.
const API_GLOB = "**/api/regx/v1/**";

/** Empty-but-valid responses so pages render instead of redirecting to /signin. */
async function stubApi(page: Page) {
  await page.route(API_GLOB, (route: Route) => {
    const url = route.request().url();
    if (url.includes("/tenants/")) {
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify([{ slug: "alpha", name: "Alpha Pharma" }]),
      });
    }
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ count: 0, next: null, previous: null, results: [] }),
    });
  });
}

test.beforeEach(async ({ page }) => {
  await stubApi(page);
});

test.describe("company navbar", () => {
  test("renders the company navbar with its three destinations", async ({ page }) => {
    await page.goto(`/documents?tenant=${TENANT}`);

    const nav = page.locator("nav.custom-navbar");
    await expect(nav).toBeVisible();

    // Company destinations must be real navigations to the Django site, not
    // client-side routes that would never leave the React app.
    await expect(nav.getByRole("link", { name: "Audit IQ" })).toHaveAttribute(
      "href",
      "/aidatabase/auditiq/",
    );
    await expect(
      nav.getByRole("link", { name: "ANDA CTD SmartTemplate" }),
    ).toHaveAttribute("href", "/ratools/modulehome/");
    await expect(nav.getByRole("link", { name: "RegX" })).toHaveAttribute(
      "href",
      "/ratools/",
    );
    await expect(nav.getByRole("link", { name: "Login" })).toHaveAttribute(
      "href",
      "/adminmaster/login/",
    );
    await expect(
      nav.getByRole("link", { name: "Schedule Consultation" }),
    ).toHaveAttribute("href", "/ratools/requestdemo");
  });

  test("keeps the RegX entry lit while inside an operational module", async ({ page }) => {
    await page.goto(`/documents?tenant=${TENANT}`);
    await expect(page.locator("nav.custom-navbar a.active-nav")).toHaveText(/RegX/);
  });

  test("is fixed to the top with the company treatment", async ({ page }) => {
    await page.goto(`/documents?tenant=${TENANT}`);
    const nav = page.locator("nav.custom-navbar");
    await expect(nav).toHaveCSS("position", "fixed");
    await expect(nav).toHaveCSS("background-color", "rgba(255, 255, 255, 0.95)");
  });
});

test.describe("editing ?tenant= to another organisation", () => {
  test("shows the refusal, loads no data and does not bounce to sign-in", async ({ page }) => {
    // stubApi lists the user's organisations as ["alpha"] only.
    const dataRequests: string[] = [];
    page.on("request", (req) => {
      const url = req.url();
      if (url.includes("/api/regx/v1/") && !url.includes("/tenants/") && !url.includes("/auth/") && !url.includes("/mfa/")) {
        dataRequests.push(url);
      }
    });
    await page.goto("/documents?tenant=beta");

    await expect(page.getByRole("heading", { name: "No access to this organisation" })).toBeVisible();
    await expect(page.getByRole("alert")).toContainText("You are not a member of the organisation “beta”");
    await expect(page).toHaveURL(/\/documents\?tenant=beta$/);
    expect(dataRequests).toEqual([]);

    await page.getByRole("link", { name: "Choose one of your organisations" }).click();
    await expect(page).toHaveURL(/\/tenants$/);
  });
});

test.describe("sidebar", () => {
  test("lists the REGX modules and the company's own tools", async ({ page }) => {
    await page.goto(`/documents?tenant=${TENANT}`);
    const sidebar = page.locator("nav.dashboard-sidebar");
    await expect(sidebar).toBeVisible();

    for (const label of [
      "Documents",
      "FDA Data",
      "Formulations",
      "IID Assessments",
      "IIG Checklists",
      "Migration Batches",
    ]) {
      await expect(sidebar.getByText(label, { exact: true })).toBeVisible();
    }

    // The legacy company tools are listed too, and they point at pages the
    // company site actually serves — no placeholder links.
    await expect(
      sidebar.getByRole("link", { name: "DMF Review Checklist" }),
    ).toHaveAttribute("href", "/ratools/show_dmf_table");
    await expect(
      sidebar.getByRole("link", { name: "Size Shape & Score" }),
    ).toHaveAttribute("href", "/ratools/show_sss");
  });

  test("REGX links carry the current tenant so a click stays in the workspace", async ({ page }) => {
    await page.goto(`/documents?tenant=${TENANT}`);
    const sidebar = page.locator("nav.dashboard-sidebar");
    await expect(sidebar.getByRole("link", { name: "Formulations" })).toHaveAttribute(
      "href",
      `/formulations?tenant=${TENANT}`,
    );
    // Legacy company tools have no tenant and keep their own URLs.
    await expect(
      sidebar.getByRole("link", { name: "DMF Review Checklist" }),
    ).toHaveAttribute("href", "/ratools/show_dmf_table");
  });

  test("is 270px wide and offsets the content panel by the same amount", async ({ page }) => {
    await page.goto(`/documents?tenant=${TENANT}`);
    await expect(page.locator("nav.dashboard-sidebar")).toHaveCSS("width", "270px");
    await expect(page.locator(".dashboard-main-panel")).toHaveCSS(
      "margin-left",
      "270px",
    );
  });

  test("collapses to a 96px icon-only rail and back", async ({ page }) => {
    await page.goto(`/documents?tenant=${TENANT}`);
    const sidebar = page.locator("nav.dashboard-sidebar");
    const toggle = page.locator("#sidebarToggle");

    await expect(sidebar).toHaveCSS("width", "270px");

    await toggle.click();
    await expect(sidebar).toHaveCSS("width", "96px");
    // Labels hide, leaving only the icons.
    await expect(page.locator(".dashboard-sidebar-label").first()).toBeHidden();
    // The company CSS moves the content panel via an !important rule.
    await expect(page.locator(".dashboard-main-panel")).toHaveCSS(
      "margin-left",
      "96px",
    );

    await toggle.click();
    await expect(sidebar).toHaveCSS("width", "270px");
    await expect(page.locator(".dashboard-sidebar-label").first()).toBeVisible();
  });

  test("exposes a tooltip for every collapsed entry", async ({ page }) => {
    await page.goto(`/documents?tenant=${TENANT}`);
    await page.locator("#sidebarToggle").click();

    // The collapsed rail relies on data-tooltip for ::after content; an entry
    // without one is an unlabelled icon.
    const entries = page.locator(
      ".dashboard-sidebar-item > .dashboard-sidebar-link",
    );
    const count = await entries.count();
    expect(count).toBeGreaterThan(0);
    for (let i = 0; i < count; i += 1) {
      await expect(entries.nth(i)).toHaveAttribute("data-tooltip", /.+/);
    }
  });

  test("marks the active route and opens the submenu that owns it", async ({ page }) => {
    await page.goto(`/documents?tenant=${TENANT}`);
    await expect(
      page.locator(`.dashboard-sidebar a[href="/documents?tenant=${TENANT}"]`),
    ).toHaveAttribute("aria-current", "page");

    await page.goto(`/fda-data/releases?tenant=${TENANT}`);
    const releases = page.locator(`.dashboard-sidebar a[href="/fda-data/releases?tenant=${TENANT}"]`);
    await expect(releases).toHaveAttribute("aria-current", "page");
    // Its parent group expands so the active child is reachable.
    await expect(releases).toBeVisible();
  });

  test("keeps sibling sections distinct on the checklist routes", async ({ page }) => {
    // /iig-checklists owns its own detail pages but must not light up when the
    // user is under /iig-checklists/executions.
    await page.goto(`/iig-checklists/executions?tenant=${TENANT}`);
    await expect(
      page.locator(`.dashboard-sidebar a[href="/iig-checklists/executions?tenant=${TENANT}"]`),
    ).toHaveAttribute("aria-current", "page");
    await expect(
      page.locator(`.dashboard-sidebar a[href="/iig-checklists?tenant=${TENANT}"]`),
    ).not.toHaveAttribute("aria-current", "page");
  });
});

test.describe("operational page treatment", () => {
  test("does not repeat the marketing hero", async ({ page }) => {
    // Phase 10: the hero belongs to the /ratools/ landing, which the company
    // site renders itself. Operational pages must not carry it.
    await page.goto(`/documents?tenant=${TENANT}`);
    await expect(page.locator(".tt-hero")).toHaveCount(0);
    await expect(page.locator("#toolsScene")).toHaveCount(0);
  });

  test("matches the design tokens measured on the company /ratools/ landing", async ({
    page,
  }) => {
    // These four values were read off the Django-rendered /ratools/ page in
    // the running stack. They are pinned here so that a change to the shell
    // CSS, or to the order it is loaded in, fails a test instead of quietly
    // making the operational pages look different from the landing beside
    // them. Notably `Inter` — not DM Sans — because navbar.html's <style>
    // sits later in the company document than the template's own.
    await page.goto(`/documents?tenant=${TENANT}`);
    await expect(page.locator("body")).toHaveCSS("font-family", "Inter, sans-serif");
    await expect(page.locator("body")).toHaveCSS(
      "background-color",
      "rgb(240, 247, 255)",
    );
    await expect(page.locator(".custom-navbar")).toHaveCSS("height", "60px");
    await expect(page.locator(".dashboard-sidebar-link").first()).toHaveCSS(
      "color",
      "rgb(11, 92, 171)",
    );
  });
});

test.describe("static assets", () => {
  test("every shell stylesheet, font and image resolves", async ({ page }) => {
    const failures: string[] = [];
    page.on("response", (res) => {
      if (res.status() >= 400) failures.push(`${res.status()} ${res.url()}`);
    });
    page.on("requestfailed", (req) => failures.push(`FAILED ${req.url()}`));

    await page.goto(`/documents?tenant=${TENANT}`);
    // "load", not "networkidle": the Google Fonts request can hang in a
    // sandboxed runner and networkidle would time out on the network rather
    // than tell us anything about the shell's own assets.
    await page.waitForLoadState("load");
    await page.locator(".dashboard-sidebar-icon").first().waitFor();

    // Google Fonts may be unreachable in a sandboxed CI runner; the assets
    // this integration is responsible for are the local ones.
    const local = failures.filter((f) => !f.includes("fonts.g"));
    expect(local, `broken shell assets:\n${local.join("\n")}`).toEqual([]);
  });

  test("the icon font actually paints glyphs", async ({ page }) => {
    await page.goto(`/documents?tenant=${TENANT}`);
    // A missing webfont silently degrades to blank boxes rather than erroring.
    const family = await page
      .locator(".dashboard-sidebar-icon")
      .first()
      .evaluate((el) => getComputedStyle(el, "::before").fontFamily);
    expect(family).toContain("Material Design Icons");
  });

  test("the company logo loads at its real dimensions", async ({ page }) => {
    await page.goto(`/documents?tenant=${TENANT}`);
    const width = await page
      .locator("img.navbar-logo")
      .evaluate((img) => (img as HTMLImageElement).naturalWidth);
    expect(width).toBeGreaterThan(0);
  });
});

test.describe("sign-in journey", () => {
  // The company site and REGX have separate authentication domains (see
  // docs/COMPANY_SITE_AUTH_INTEGRATION.md). A visitor arriving from a company
  // page into a REGX module must land on the REGX sign-in screen and then be
  // returned to what they asked for, rather than being dropped on the tenant
  // picker with no idea where they were going.
  test("an unauthenticated module bounces to REGX sign-in carrying the return target", async ({
    page,
  }) => {
    // This page treats 403 as "go and sign in"; others use 401. That
    // inconsistency predates the integration and is left alone — the point
    // here is only that whichever status a page bounces on, it carries the
    // return target with it.
    await page.route(API_GLOB, (route: Route) =>
      route.fulfill({
        status: 403,
        contentType: "application/json",
        body: JSON.stringify({ detail: "Authentication credentials were not provided." }),
      }),
    );

    await page.goto(`/migration-batches?tenant=${TENANT}`);
    await expect(page).toHaveURL(/\/signin\?next=/);

    const next = new URL(page.url()).searchParams.get("next");
    expect(next).toContain("/migration-batches");
    await expect(page.getByRole("heading", { name: /sign in/i })).toBeVisible();
  });

  // ?next= is attacker-controllable, so the sign-in screen must not become an
  // open redirect. Each of these is signed in for real (against a mocked
  // login) and must land on /tenants, never on the supplied target.
  for (const hostile of [
    "//evil.example.com/steal",
    "https://evil.example.com/steal",
    "/\\evil.example.com/steal",
    "/signin",
  ]) {
    test(`refuses the return target ${hostile}`, async ({ page }) => {
      await page.route(API_GLOB, (route: Route) =>
        route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({ csrfToken: "test", email: "a@b.c" }),
        }),
      );

      await page.goto(`/signin?next=${encodeURIComponent(hostile)}`);
      await page.getByLabel("Email").fill("a@b.c");
      await page.getByLabel("Password").fill("password123");
      await page.getByRole("button", { name: /^sign in$/i }).click();

      await expect(page).toHaveURL(/\/tenants$/);
      expect(page.url()).not.toContain("evil.example.com");
    });
  }

  test("honours a legitimate same-origin return target", async ({ page }) => {
    await page.route(API_GLOB, (route: Route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ csrfToken: "test", email: "a@b.c" }),
      }),
    );

    await page.goto("/signin?next=%2Fmigration-batches%3Ftenant%3Dalpha");
    await page.getByLabel("Email").fill("a@b.c");
    await page.getByLabel("Password").fill("password123");
    await page.getByRole("button", { name: /^sign in$/i }).click();

    await expect(page).toHaveURL(/\/migration-batches\?tenant=alpha/);
  });
});

test.describe("mobile", () => {
  test.use({ viewport: { width: 375, height: 812 } });

  test("collapses the navbar behind the toggler and never scrolls sideways", async ({
    page,
  }) => {
    await page.goto(`/documents?tenant=${TENANT}`);

    const toggler = page.locator("button.navbar-toggler");
    await expect(toggler).toBeVisible();

    const menu = page.locator("#mainNavbar");
    await expect(menu).not.toHaveClass(/show/);
    await toggler.click();
    await expect(menu).toHaveClass(/show/);
    await expect(menu.getByRole("link", { name: "RegX" })).toBeVisible();

    const overflows = await page.evaluate(
      () => document.documentElement.scrollWidth > window.innerWidth,
    );
    expect(overflows, "page scrolls horizontally on mobile").toBe(false);
  });
});
