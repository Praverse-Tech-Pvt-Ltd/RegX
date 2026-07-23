// Regression guard for a defect found during Docker-stack verification:
// with CSP genuinely enforced (as every real browser does), the app
// rendered a completely blank page on every route — React never hydrated
// because its own inline bootstrap/RSC-payload scripts were blocked by
// script-src. This was invisible to every other spec in this suite because
// playwright.config.ts sets bypassCSP: true globally (necessary so
// page.route() mocking and dev-mode HMR work). This file explicitly
// re-enables CSP enforcement to prove the app still renders under it.
import { test, expect } from "@playwright/test";

test.describe("CSP is enforced and the app still renders (regression guard)", () => {
  test.use({ bypassCSP: false });

  test("/signin hydrates and stays rendered under real CSP enforcement", async ({ page }) => {
    const cspViolations: string[] = [];
    page.on("console", (msg) => {
      if (msg.text().toLowerCase().includes("content security policy")) {
        cspViolations.push(msg.text());
      }
    });

    await page.goto("/signin");

    await expect(page.getByRole("heading", { name: /sign in/i })).toBeVisible();
    await expect(page.getByLabel("Email")).toBeVisible();

    // Prove genuine React hydration occurred (not just static SSR markup
    // sitting inert): type into a controlled input and read the value back
    // through the DOM, which only reflects if React's onChange handler ran.
    await page.getByLabel("Email").fill("csp-guard@example.com");
    await expect(page.getByLabel("Email")).toHaveValue("csp-guard@example.com");

    // Content must still be there after a delay — the original defect
    // showed content briefly (from SSR) before React's failed-hydration
    // recovery cleared it.
    await page.waitForTimeout(2000);
    await expect(page.getByRole("heading", { name: /sign in/i })).toBeVisible();

    expect(cspViolations, cspViolations.join("\n")).toEqual([]);
  });
});
