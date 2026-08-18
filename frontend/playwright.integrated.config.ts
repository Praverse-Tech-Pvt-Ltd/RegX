import { defineConfig, devices } from "@playwright/test";

/**
 * INTEGRATED-ORIGIN E2E.
 *
 * Exercises the **real compose stack** through the nginx origin: the company
 * Django site, the RegX frontend and the RegX backend on one host, with no API
 * mocking at all. That is the whole point of this family — it verifies the
 * integration, so mocking would defeat it.
 *
 * Deliberately has **no `webServer`**. Playwright must never start anything
 * here; the stack is brought up by `docker compose up -d` and this config only
 * points a browser at it. Nothing on port 3100 or 3000 is involved.
 *
 * Run with:
 *
 *   docker compose up -d
 *   npm run test:e2e:integrated
 *
 * `INTEGRATED_BASE_URL` overrides the origin for a non-default deployment.
 * Unlike the local config, honouring an override is correct here: the caller is
 * explicitly naming the environment they mean.
 *
 * Deliberately **not** `BASE_URL`. Vite sets `BASE_URL` to `"/"` in its own
 * process env, so a config reading it can silently resolve to `"/"` instead of
 * the intended origin — which the config-contract unit test caught. A name the
 * toolchain does not already own removes that whole class of surprise.
 */
export default defineConfig({
  testDir: "./e2e",
  testMatch: "**/company-site-integration.spec.ts",
  fullyParallel: true,
  forbidOnly: !!process.env["CI"],
  retries: process.env["CI"] ? 2 : 0,
  workers: process.env["CI"] ? 1 : undefined,
  reporter: [["html", { open: "never" }], ["list"]],
  use: {
    baseURL: process.env["INTEGRATED_BASE_URL"] ?? "http://localhost:8080",
    trace: "on-first-retry",
    screenshot: "only-on-failure",
    bypassCSP: true,
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
});
