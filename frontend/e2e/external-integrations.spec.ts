import { test, expect, type Page, type Route } from "@playwright/test";

/**
 * External integration E2E.
 *
 * API responses are mocked with `page.route`, as every other spec here does, so
 * the test exercises the UI contract rather than a live backend -- and, more to
 * the point here, so that nothing in the suite ever makes a real outbound
 * request to anywhere.
 *
 * The properties under test are the ones the milestone exists for:
 *   - a connector is a destination, and "Enabled" is not approval;
 *   - a transfer is a technical act, never a submission;
 *   - **no secret value is ever rendered**, only the name of a variable;
 *   - a disabled connector offers nothing to run.
 */

const API = "http://localhost:8000";
const TENANT = "alpha";
const CONNECTOR = "11111111-2222-3333-4444-555555555555";
const PKG = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee";
const EXECUTION = "99999999-8888-7777-6666-555555555555";

/** Never a real credential, and never rendered -- present so the assertions
 *  that it is absent have something specific to look for. */
const SECRET_VALUE = "synthetic-token-value-not-a-real-credential";

const PERMISSIONS = {
  can_edit: true,
  can_enable: true,
  can_test: true,
  can_execute: true,
};

function connector(over: Record<string, unknown> = {}) {
  return {
    public_id: CONNECTOR,
    name: "Partner endpoint",
    description: "",
    connector_type: "generic_https",
    status: "active",
    configuration: {
      base_url: "https://partner.example/",
      allowed_path_prefix: "/regx/",
      health_path: "health",
      connect_timeout_seconds: 5,
      read_timeout_seconds: 30,
      max_response_bytes: 33554432,
      verify_tls: true,
      static_headers: {},
    },
    configuration_version: 3,
    last_tested_at: null,
    last_test_status: "never_tested",
    created_at: "2026-01-01T00:00:00Z",
    credential: {
      public_id: "cred-1",
      credential_type: "bearer_token",
      environment_variable: "REGX_CONNECTOR_ABC_TOKEN",
      is_resolvable: true,
    },
    permissions: PERMISSIONS,
    ...over,
  };
}

function execution(over: Record<string, unknown> = {}) {
  return {
    public_id: EXECUTION,
    connector_public_id: CONNECTOR,
    operation: "push_frozen_package",
    status: "succeeded",
    resource_type: "submission_package",
    resource_public_id: PKG,
    snapshot_public_id: "snap-1",
    manifest_checksum: "c".repeat(64),
    requested_at: "2026-02-01T09:00:00Z",
    started_at: "2026-02-01T09:00:01Z",
    finished_at: "2026-02-01T09:00:04Z",
    attempt_count: 1,
    connector_configuration_version: 3,
    error_code: "",
    external_reference: "remote-object-1",
    correlation_id: "req-abc",
    request_summary: { operation: "push_frozen_package" },
    response_summary: { http_status: 200, bytes_transferred: 4096 },
    ...over,
  };
}

async function json(route: Route, body: unknown, status = 200) {
  await route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
}

async function stubAuth(page: Page) {
  await page.route(`${API}/api/regx/v1/auth/session/`, (r) =>
    json(r, { user: { public_id: "u1", email: "a@example.test", full_name: "Author" } }),
  );
  await page.route(`${API}/api/regx/v1/auth/csrf/`, (r) => json(r, { csrfToken: "e2e" }));
  await page.route(`${API}/api/regx/v1/tenants/**`, (r) =>
    json(r, { results: [{ public_id: "t1", name: "Alpha", slug: TENANT }] }),
  );
}

function page1(results: unknown[]) {
  return { count: results.length, next: null, previous: null, results };
}

// ---------------------------------------------------------------------------
test.describe("Connector list", () => {
  test("lists connectors and states that enabled is not approval", async ({ page }) => {
    await stubAuth(page);
    await page.route(new RegExp("/external-integrations/\\?"), (r) =>
      json(r, page1([connector()])),
    );

    await page.goto(`/external-integrations?tenant=${TENANT}`);
    await expect(page.getByTestId("connector-table")).toBeVisible();
    await expect(page.getByTestId("connector-row")).toHaveCount(1);
    await expect(page.getByTestId("connector-status-badge")).toHaveText("Enabled");

    const note = await page.getByTestId("enabled-means-note").innerText();
    expect(note.toLowerCase()).toContain("not approval");
    expect(note.toLowerCase()).toContain("not a regulatory submission");
  });

  test("an empty list says nothing is configured rather than showing an error", async ({
    page,
  }) => {
    await stubAuth(page);
    await page.route(new RegExp("/external-integrations/\\?"), (r) => json(r, page1([])));

    await page.goto(`/external-integrations?tenant=${TENANT}`);
    await expect(page.getByTestId("connectors-empty")).toBeVisible();
    await expect(page.getByTestId("integration-error")).toHaveCount(0);
  });

  test("a caller without permission is told so, not shown a failure", async ({ page }) => {
    await stubAuth(page);
    await page.route(new RegExp("/external-integrations/\\?"), (r) =>
      json(r, { error: { status: 403, detail: "no" } }, 403),
    );

    await page.goto(`/external-integrations?tenant=${TENANT}`);
    await expect(page.getByTestId("connectors-forbidden")).toBeVisible();
  });

  test("the create form asks for a secret reference, not a password", async ({ page }) => {
    await stubAuth(page);
    await page.route(new RegExp("/external-integrations/\\?"), (r) => json(r, page1([])));

    await page.goto(`/external-integrations?tenant=${TENANT}`);
    await page.getByTestId("new-connector").click();
    await expect(page.getByTestId("connector-form")).toBeVisible();

    const secretField = page.getByTestId("credential-reference");
    await expect(secretField).toHaveAttribute("type", "text");
    await expect(page.getByText(/never the value/i)).toBeVisible();
    // TLS is stated as unconditional, with no control offered to change it.
    await expect(page.getByText(/TLS verification is\s+always on/i)).toBeVisible();
  });
});

// ---------------------------------------------------------------------------
test.describe("Connector detail", () => {
  async function stubDetail(page: Page, over: Record<string, unknown> = {}, history = [execution()]) {
    await stubAuth(page);
    await page.route(new RegExp(`/external-integrations/${CONNECTOR}/executions/`), (r) =>
      json(r, page1(history)),
    );
    await page.route(new RegExp(`/external-integrations/${CONNECTOR}/$`), (r) =>
      json(r, { ...connector(), ...over }),
    );
  }

  test("shows the credential's variable name and never a value", async ({ page }) => {
    await stubDetail(page);
    await page.goto(`/external-integrations/${CONNECTOR}?tenant=${TENANT}`);

    await expect(page.getByTestId("credential-variable")).toContainText("REGX_CONNECTOR_ABC");
    await expect(page.getByTestId("credential-resolvable")).toHaveText("Yes");

    // The whole rendered page, not just the fields somebody remembered.
    const body = await page.locator("body").innerText();
    expect(body).not.toContain(SECRET_VALUE);
    expect(body).not.toContain("Bearer ");
  });

  test("states that TLS verification is always on", async ({ page }) => {
    await stubDetail(page);
    await page.goto(`/external-integrations/${CONNECTOR}?tenant=${TENANT}`);
    await expect(page.getByTestId("config-tls")).toHaveText("Always on");
  });

  test("a successful connection test reports reachability and latency", async ({ page }) => {
    await stubDetail(page);
    await page.route(new RegExp(`/external-integrations/${CONNECTOR}/test/`), (r) =>
      json(r, {
        reachable: true,
        authenticated: true,
        status: "reachable",
        latency_ms: 42,
        error_code: "",
      }),
    );

    await page.goto(`/external-integrations/${CONNECTOR}?tenant=${TENANT}`);
    await page.getByTestId("test-connection").click();
    await expect(page.getByTestId("test-result")).toContainText("42 ms");
    await expect(page.getByTestId("connector-test-badge").first()).toBeVisible();
  });

  test("a failed test shows an enumerated reason, never a remote body", async ({ page }) => {
    await stubDetail(page);
    await page.route(new RegExp(`/external-integrations/${CONNECTOR}/test/`), (r) =>
      json(r, {
        reachable: false,
        authenticated: false,
        status: "unauthorised",
        latency_ms: null,
        error_code: "AUTH_FAILED",
      }),
    );

    await page.goto(`/external-integrations/${CONNECTOR}?tenant=${TENANT}`);
    await page.getByTestId("test-connection").click();
    await expect(page.getByTestId("test-error")).toHaveText(
      "Authentication was rejected by the endpoint",
    );
  });

  test("execution history names the configuration version each transfer used", async ({
    page,
  }) => {
    await stubDetail(page);
    await page.goto(`/external-integrations/${CONNECTOR}?tenant=${TENANT}`);

    const row = page.getByTestId("execution-row").first();
    await expect(row).toContainText("Transfer frozen package");
    await expect(row).toContainText("Transferred");
    await expect(row).toContainText("3");
  });

  test("a failed execution shows a sentence rather than a code", async ({ page }) => {
    await stubDetail(page, {}, [
      execution({ status: "failed", error_code: "PACKAGE_INTEGRITY_FAILED", external_reference: "" }),
    ]);
    await page.goto(`/external-integrations/${CONNECTOR}?tenant=${TENANT}`);
    await expect(page.getByTestId("execution-result").first()).toHaveText(
      "The package could not be assembled as it was frozen",
    );
  });

  test("an empty history is distinguished from no access", async ({ page }) => {
    await stubDetail(page, {}, []);
    await page.goto(`/external-integrations/${CONNECTOR}?tenant=${TENANT}`);
    await expect(page.getByTestId("history-empty")).toBeVisible();
    await expect(page.getByTestId("history-forbidden")).toHaveCount(0);
  });

  test("a disabled connector offers Enable rather than Disable", async ({ page }) => {
    await stubDetail(page, { status: "disabled" });
    await page.goto(`/external-integrations/${CONNECTOR}?tenant=${TENANT}`);
    await expect(page.getByTestId("enable-connector")).toBeVisible();
    await expect(page.getByTestId("disable-connector")).toHaveCount(0);
  });

  test("a connector in another tenant reads as absent", async ({ page }) => {
    await stubAuth(page);
    await page.route(new RegExp(`/external-integrations/${CONNECTOR}/`), (r) =>
      json(r, { error: { status: 404, detail: "No such connector." } }, 404),
    );
    await page.goto(`/external-integrations/${CONNECTOR}?tenant=${TENANT}`);
    await expect(page.getByTestId("connector-not-found")).toBeVisible();
  });
});

// ---------------------------------------------------------------------------
test.describe("Transferring a frozen package", () => {
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

  function frozenPackage() {
    return {
      public_id: PKG,
      name: "Synthetic package",
      description: "",
      status: "frozen",
      revision_number: 1,
      case_public_id: "case-1",
      source_package_public_id: null,
      entry_count: 1,
      manifest_checksum: "c".repeat(64),
      created_by: { public_id: "u1", full_name: "Author" },
      created_at: "2026-01-01T00:00:00Z",
      frozen_by: { public_id: "u1", full_name: "Author" },
      frozen_at: "2026-01-02T00:00:00Z",
      cancelled_at: null,
      permissions: PERMS,
      entries: [],
    };
  }

  async function stubPackagePage(page: Page, connectors: unknown[]) {
    await stubAuth(page);
    await page.route(new RegExp(`/submission-packages/${PKG}/validate/`), (r) =>
      json(r, { valid: true, issues: [], semantics: "internal_package_integrity" }),
    );
    await page.route(new RegExp(`/submission-packages/${PKG}/$`), (r) => json(r, frozenPackage()));
    await page.route(new RegExp("/external-integrations/\\?"), (r) => json(r, page1(connectors)));
  }

  test("offers transfer, and calls it a transfer rather than a submission", async ({ page }) => {
    await stubPackagePage(page, [connector()]);
    await page.route(new RegExp(`/external-integrations/${CONNECTOR}/executions/`), (r) =>
      json(r, execution({ status: "queued", error_code: "", external_reference: "" }), 201),
    );

    await page.goto(`/submission-packages/${PKG}?tenant=${TENANT}`);
    await expect(page.getByTestId("transfer-panel")).toBeVisible();

    const panel = await page.getByTestId("transfer-panel").innerText();
    expect(panel.toLowerCase()).toContain("technical transfer");
    expect(panel.toLowerCase()).not.toContain("submit to agency");
    expect(panel.toLowerCase()).not.toContain("regulatory filing");

    await page.getByTestId("start-transfer").click();
    await expect(page.getByTestId("transfer-result")).toBeVisible();
    await expect(page.getByTestId("transfer-result")).toContainText("configuration version 3");
  });

  test("a disabled connector is not offered as a destination", async ({ page }) => {
    await stubPackagePage(page, [connector({ status: "disabled" })]);
    await page.goto(`/submission-packages/${PKG}?tenant=${TENANT}`);
    await expect(page.getByTestId("no-connectors")).toBeVisible();
    await expect(page.getByTestId("start-transfer")).toHaveCount(0);
  });

  test("a refused transfer explains which permission is missing", async ({ page }) => {
    await stubPackagePage(page, [connector()]);
    await page.route(new RegExp(`/external-integrations/${CONNECTOR}/executions/`), (r) =>
      json(r, { error: { status: 403, detail: "nope" } }, 403),
    );

    await page.goto(`/submission-packages/${PKG}?tenant=${TENANT}`);
    await page.getByTestId("start-transfer").click();
    await expect(page.getByTestId("transfer-error")).toContainText("export packages");
  });

  test("no secret appears anywhere on the package page", async ({ page }) => {
    await stubPackagePage(page, [connector()]);
    await page.goto(`/submission-packages/${PKG}?tenant=${TENANT}`);
    await expect(page.getByTestId("transfer-panel")).toBeVisible();

    const body = await page.locator("body").innerText();
    expect(body).not.toContain(SECRET_VALUE);
    expect(body).not.toContain("REGX_CONNECTOR_ABC_TOKEN");
  });
});
