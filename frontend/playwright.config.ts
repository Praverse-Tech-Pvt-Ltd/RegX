import { defineConfig, devices } from "@playwright/test";

/**
 * LOCAL frontend E2E.
 *
 * Exercises a Next.js dev server that **Playwright starts and owns**, whose
 * bundle calls the API at `http://localhost:8000` — which is what every spec in
 * this family mocks with `page.route`.
 *
 * Two deliberate choices, both fixing a real defect:
 *
 * `port: 3100` — a dedicated port, not 3000. The compose stack publishes the
 * frontend container on 3000, and that container's bundle calls `:8080`. With
 * the old config this suite silently attached to it, so every `:8000` mock
 * missed, real calls returned 403, and 40 tests failed for reasons that had
 * nothing to do with the code under test. It cost one incorrect project report
 * before it was understood. 3100 is claimed by nothing in `compose.yaml`.
 *
 * `reuseExistingServer: false` — always. Playwright owns this port in every
 * environment, local and CI alike, so there is one contract rather than two.
 * If anything else is already listening on 3100, Playwright fails immediately
 * with a port error instead of quietly testing it. That loud failure *is* the
 * guard: no title sniffing, no identity probe, nothing brittle.
 *
 * `baseURL` is fixed and deliberately ignores `BASE_URL`. Honouring it here is
 * what allowed one suite to be pointed at another environment without saying
 * so. The integrated-origin suite has its own config and its own command.
 *
 * Integrated-origin specs are excluded by `testIgnore`; run them with
 * `npm run test:e2e:integrated`.
 */
export default defineConfig({
  testDir: "./e2e",
  testIgnore: "**/company-site-integration.spec.ts",
  fullyParallel: true,
  forbidOnly: !!process.env["CI"],
  retries: process.env["CI"] ? 2 : 0,
  workers: process.env["CI"] ? 1 : undefined,
  reporter: [["html", { open: "never" }], ["list"]],
  expect: {
    // 15s, not Playwright's 5s default.
    //
    // `router.push()` in the App Router does not change the URL until the
    // destination route's payload is ready, and `npm run dev` compiles routes on
    // demand. Under parallel workers all hitting one dev server, a cold route
    // compile can take longer than 5s, so `expect(page).toHaveURL(...)` expires
    // while the navigation is still legitimately in flight -- the assertion
    // outruns the compiler, not the application.
    //
    // Measured on this suite at --repeat-each=2 --workers=20:
    //   expect 5s  -> 16 failures / 896 executions, every one a toHaveURL
    //   expect 15s ->  0 failures / 672 executions
    //   expect 30s ->  0 failures / 896 executions
    // At the default local worker count nothing failed in 1,410 executions, so
    // this is a margin for contention, not a fix for a broken test.
    //
    // Kept at 15s rather than 30s deliberately: a genuinely wrong assertion
    // should still fail promptly. This raises the ceiling; it does not hide a
    // race. Nothing here waits on a timer -- every assertion still polls for the
    // real condition and returns as soon as it holds.
    timeout: 15_000,
  },
  use: {
    baseURL: "http://localhost:3100",
    trace: "on-first-retry",
    screenshot: "only-on-failure",
    // CSP with 'script-src self' blocks Next.js dev-mode eval and inline scripts,
    // and 'connect-src self' blocks cross-origin API fetches during tests.
    // bypassCSP lets React hydrate and page.route() intercept API calls correctly.
    bypassCSP: true,
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
  webServer: {
    command: "npm run dev -- --port 3100",
    url: "http://localhost:3100",
    reuseExistingServer: false,
    timeout: 120_000,
  },
});
