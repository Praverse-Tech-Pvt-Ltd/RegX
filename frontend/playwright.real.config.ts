import { defineConfig, devices } from "@playwright/test";

/**
 * REAL-STACK smoke check: a browser against the running integrated stack at
 * :8080 (nginx -> frontend, backend, company_site). Nothing is mocked.
 *
 * Run it with `scripts/real_stack_smoke.sh`, which seeds nothing and changes no
 * configuration: it expects a stack that was migrated and seeded with
 * `seed_regx_demo`, and the demo password in REAL_STACK_PASSWORD (never in a
 * file). Results (one JSON line per page, screenshots) go to REAL_STACK_OUT.
 *
 * Separate from `playwright.config.ts` (mocked, owns :3100) and
 * `playwright.integrated.config.ts` (company_site integration), so neither
 * picks these specs up by accident.
 */
export default defineConfig({
  testDir: "./e2e-real",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 10 * 60 * 1000,
  reporter: [["list"]],
  expect: { timeout: 15_000 },
  use: {
    baseURL: process.env["REAL_STACK_URL"] ?? "http://localhost:8080",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
