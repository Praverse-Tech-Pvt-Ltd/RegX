/**
 * Guards the E2E harness contract that F-1 fixed.
 *
 * The defect: the local Playwright config used port 3000 with
 * `reuseExistingServer: !CI`, so whenever the compose stack was up, the suite
 * silently attached to the frontend *container* — whose bundle calls the API on
 * :8080 while every local spec mocks :8000. The result was 40 failures that had
 * nothing to do with the code, and one incorrect project report before anyone
 * understood why.
 *
 * These assertions are on configuration values, not on rendered output, so they
 * cannot flake. They exist because the failure was silent: nothing broke
 * loudly, the suite just answered a question about a different server.
 */
import { describe, expect, it } from "vitest";

import localConfig from "../../playwright.config";
import integratedConfig from "../../playwright.integrated.config";
import realConfig from "../../playwright.real.config";

/** The port the compose stack publishes the frontend container on. */
const DOCKER_FRONTEND_PORT = "3000";

describe("local E2E config", () => {
  it("never reuses a server it did not start", () => {
    // The single line that caused the defect. If this is ever true again, a
    // stray process on the E2E port silently becomes the system under test.
    expect(localConfig.webServer).toBeDefined();
    expect((localConfig.webServer as { reuseExistingServer?: boolean }).reuseExistingServer).toBe(
      false,
    );
  });

  it("does not use the port the Docker frontend publishes", () => {
    const web = localConfig.webServer as { url?: string; command?: string };
    expect(web.url).not.toContain(`:${DOCKER_FRONTEND_PORT}`);
    expect(web.command).not.toContain(`--port ${DOCKER_FRONTEND_PORT}`);
    expect(String(localConfig.use?.baseURL)).not.toContain(`:${DOCKER_FRONTEND_PORT}`);
  });

  it("starts its server on the same origin it points the browser at", () => {
    // A mismatch here would send the browser somewhere Playwright is not
    // managing — the same class of bug by a different route.
    const web = localConfig.webServer as { url?: string };
    expect(String(localConfig.use?.baseURL)).toBe(web.url);
  });

  it("pins baseURL rather than honouring BASE_URL", () => {
    // Honouring BASE_URL here is what let one suite be aimed at another
    // environment without saying so. The integrated suite has its own config.
    expect(String(localConfig.use?.baseURL)).toBe("http://localhost:3100");
  });

  it("excludes the integrated-origin suite", () => {
    expect(String(localConfig.testIgnore)).toContain("company-site-integration");
  });
});

describe("integrated-origin E2E config", () => {
  it("starts no server of its own", () => {
    // The stack is brought up by docker compose. If Playwright started
    // anything here it would not be testing the integration.
    expect(integratedConfig.webServer).toBeUndefined();
  });

  it("targets the nginx origin by default", () => {
    expect(String(integratedConfig.use?.baseURL)).toContain(":8080");
  });

  it("runs only the integrated spec", () => {
    expect(String(integratedConfig.testMatch)).toContain("company-site-integration");
  });
});

describe("the two configs cannot collide", () => {
  it("target different origins", () => {
    expect(String(localConfig.use?.baseURL)).not.toBe(
      String(integratedConfig.use?.baseURL),
    );
  });
});

describe("the real-stack config (scripts/real_stack_smoke.sh)", () => {
  // Its specs sign in to a running stack and create records; the mocked suite
  // (npm run test:e2e, run in CI) must never pick them up, and vice versa.
  it("has its own test directory, outside the mocked suite's", () => {
    expect(realConfig.testDir).toBe("./e2e-real");
    expect(localConfig.testDir).toBe("./e2e");
    expect(integratedConfig.testDir).toBe("./e2e");
  });

  it("runs one worker in order (the flows depend on each other)", () => {
    expect(realConfig.workers).toBe(1);
    expect(realConfig.fullyParallel).toBe(false);
  });
});
