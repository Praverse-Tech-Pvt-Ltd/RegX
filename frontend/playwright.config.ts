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
