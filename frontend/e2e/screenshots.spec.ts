import { test, expect, type Page, type Route } from "@playwright/test";

/**
 * Visual capture for the UI-alignment review.
 *
 * Not an assertion suite -- it exists so the design change can be inspected
 * rather than taken on trust from a passing test run. It writes PNGs to
 * `screenshots/` and is excluded from the default run by its own project
 * filter; invoke it explicitly.
 *
 * Authenticated pages mock the API the same way `regx-shell.spec.ts` does,
 * so no seeded data or real credentials are involved.
 */

const OUT = "screenshots";

const EMPTY_PAGE = { count: 0, next: null, previous: null, results: [] };

async function mockApi(page: Page) {
  await page.route("**/api/**", (route: Route) => {
    const url = route.request().url();
    if (url.includes("/auth/csrf")) {
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ csrfToken: "shot", email: "reviewer@example.com" }),
      });
    }
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(EMPTY_PAGE),
    });
  });
}

const BREAKPOINTS = [
  { name: "1440", width: 1440, height: 900 },
  { name: "1280", width: 1280, height: 860 },
  { name: "1024", width: 1024, height: 820 },
  { name: "768", width: 768, height: 900 },
  { name: "mobile-375", width: 375, height: 812 },
];

test.describe("visual capture", () => {
  test("sign-in across every reviewed breakpoint", async ({ page }) => {
    await mockApi(page);
    for (const bp of BREAKPOINTS) {
      await page.setViewportSize({ width: bp.width, height: bp.height });
      await page.goto("/signin");
      await expect(page.getByRole("heading", { name: /sign in/i })).toBeVisible();
      await page.screenshot({ path: `${OUT}/signin-${bp.name}.png`, fullPage: true });

      // No horizontal overflow at any width -- the sign-in page must not
      // require sideways scrolling on a phone.
      const overflow = await page.evaluate(
        () => document.documentElement.scrollWidth > window.innerWidth + 1,
      );
      expect(overflow, `horizontal overflow at ${bp.name}`).toBe(false);
    }
  });

  test("sign-in error state", async ({ page }) => {
    await page.route("**/api/**", (route: Route) => {
      const url = route.request().url();
      if (url.includes("/auth/csrf")) {
        return route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({ csrfToken: "shot" }),
        });
      }
      return route.fulfill({
        status: 401,
        contentType: "application/json",
        body: JSON.stringify({
          error: { status: 401, detail: { detail: "Invalid email or password." } },
        }),
      });
    });
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto("/signin");
    await page.getByLabel("Email").fill("nobody@example.com");
    await page.getByLabel("Password").fill("WrongPass1234!");
    await page.getByRole("button", { name: /^sign in$/i }).click();
    await expect(page.getByRole("alert")).toBeVisible({ timeout: 10_000 });
    await page.screenshot({ path: `${OUT}/signin-error.png`, fullPage: true });
  });

  test("mfa", async ({ page }) => {
    await mockApi(page);
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto("/mfa");
    await expect(page.getByRole("heading", { name: /two-factor/i })).toBeVisible();
    await page.screenshot({ path: `${OUT}/mfa-1440.png`, fullPage: true });
  });

  for (const [label, path] of [
    ["documents", "/documents?tenant=alpha"],
    ["workflows", "/workflows?tenant=alpha"],
    ["dashboard", "/dashboard?tenant=alpha"],
  ] as const) {
    test(`authenticated shell — ${label}`, async ({ page }) => {
      await mockApi(page);
      await page.setViewportSize({ width: 1440, height: 900 });
      await page.goto(path);
      await page.waitForLoadState("networkidle");
      await page.screenshot({ path: `${OUT}/shell-${label}-1440.png`, fullPage: true });

      // Regression guard. `.content-wrapper` is a column flex container, and
      // auto cross-axis margins on each page's <main> suppressed the default
      // stretch -- every authenticated page was laying out at 390px on a
      // 1440px viewport. If that recurs, this fails rather than merely looking
      // wrong in a screenshot nobody opens.
      const geom = await page.evaluate(() => {
        const m = document.querySelector("main");
        return {
          mainWidth: m ? Math.round(m.getBoundingClientRect().width) : 0,
          overflow: document.documentElement.scrollWidth > window.innerWidth + 1,
        };
      });
      expect(geom.mainWidth, `${label} content collapsed`).toBeGreaterThan(600);
      expect(geom.overflow, `${label} overflows horizontally`).toBe(false);
    });
  }
});
