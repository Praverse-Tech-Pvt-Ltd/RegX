// Milestone 4D-3 -- client-visible calculation automation, end to end.
//
// Backend responses are deterministic Playwright route mocks (page.route), the
// same convention the 4D-2 execution suite uses. The cascade itself is a
// backend behaviour and is proven by the pytest cascade suite (140 tests); what
// this suite proves is the *client* half of the contract:
//
//   edit a manual response
//     -> PATCH carries the loaded expected_version
//     -> the client refetches the whole authoritative collection
//     -> the calculated dependent visibly changes
//
// The mock therefore serves a different response collection after the PATCH,
// exactly as a real backend would once the cascade had run. Fixtures are
// synthetic and non-confidential.
import { test, expect, type Page, type Route } from "@playwright/test";

const TENANT = "alpha";
const API = "http://localhost:8000";

const EXECUTION_ID = "exec-e2e-calc-1";
const VERSION_ID = "ver-e2e-calc-1";
const MANUAL_ID = "resp-e2e-manual-1";
const CALC_ID = "resp-e2e-calc-1";

function jsonRoute(body: unknown, status = 200) {
  return (route: Route) =>
    route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
}

function paginate(results: unknown[]) {
  return { count: results.length, next: null, previous: null, results };
}

function executionFixture() {
  return {
    public_id: EXECUTION_ID,
    status: "draft",
    checklist_version: { public_id: VERSION_ID, version_number: 1, status: "active" },
    formulation_version_public_id: "fv-e2e-calc-1",
    created_by_email: "doer@example.com",
    submitted_by_email: null,
    submitted_at: null,
    returned_by_email: null,
    returned_at: null,
    return_reason: "",
    approved_by_email: null,
    approved_at: null,
    rejected_by_email: null,
    rejected_at: null,
    cancelled_by_email: null,
    cancelled_at: null,
    reviewer_conclusion_note: "",
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
  };
}

function versionFixture() {
  return {
    public_id: VERSION_ID,
    version_number: 1,
    status: "active",
    sections: [
      {
        public_id: "sec-e2e-1",
        code: "S1",
        title: "Section 1",
        description: "",
        display_order: 1,
        criticality: "low",
        questions: [
          {
            public_id: `q-${MANUAL_ID}`,
            code: "Q_MANUAL",
            question_text: "Excipient amount",
            display_order: 1,
            answer_type: "short_text",
            data_source_classification: "user_required",
            criticality: "low",
            required: true,
          },
          {
            public_id: `q-${CALC_ID}`,
            code: "Q_CALC",
            question_text: "Percentage w/w",
            display_order: 2,
            answer_type: "calculated_value",
            data_source_classification: "system_calculated",
            criticality: "low",
            required: true,
          },
        ],
      },
    ],
  };
}

function responseFixture(overrides: Record<string, unknown> = {}) {
  return {
    public_id: MANUAL_ID,
    question_public_id: `q-${MANUAL_ID}`,
    data_source_type_snapshot: "user_required",
    // raw_value is always enveloped: {"value": …} per response_validation.py.
    raw_value: { value: "50" },
    is_not_applicable: false,
    not_applicable_reason: null,
    entered_by_email: "doer@example.com",
    entered_at: "2026-01-01T00:00:00Z",
    confirmed_by_email: null,
    confirmed_at: null,
    override_reason: "",
    system_derived_value: null,
    version: 4,
    calculation: null,
    ...overrides,
  };
}

function calculatedFixture(
  version: number,
  calculation: Record<string, unknown> | null
) {
  return responseFixture({
    public_id: CALC_ID,
    question_public_id: `q-${CALC_ID}`,
    data_source_type_snapshot: "system_calculated",
    // M4D3-MDL-006: a calculated response never carries raw_value.
    raw_value: null,
    system_derived_value: null,
    version,
    calculation,
  });
}

const COMPLETE_BEFORE = {
  outcome_public_id: "outcome-e2e-1",
  status: "complete",
  value: "25.0000000000",
  unit: "gram",
  reason_code: null,
};

const COMPLETE_AFTER = {
  outcome_public_id: "outcome-e2e-1",
  status: "complete",
  value: "75.0000000000",
  unit: "gram",
  reason_code: null,
};

const DATA_REQUIRED = {
  outcome_public_id: "outcome-e2e-1",
  status: "data_required",
  value: null,
  unit: null,
  reason_code: "DATA_REQUIRED",
};

/**
 * Wire up the execution page. `state` is mutated by the PATCH handler so a
 * later refetch serves post-cascade data, mirroring a real backend.
 */
async function mockExecutionPage(
  page: Page,
  state: { manualValue: string; manualVersion: number; calc: Record<string, unknown> | null }
) {
  const patchBodies: Record<string, unknown>[] = [];

  await page.route(`${API}/api/regx/v1/auth/csrf/`, jsonRoute({ csrfToken: "e2e-csrf-token" }));
  await page.route(
    `${API}/api/regx/v1/iig-checklists/executions/${EXECUTION_ID}/`,
    jsonRoute(executionFixture())
  );
  await page.route(
    `${API}/api/regx/v1/iig-checklists/versions/${VERSION_ID}/`,
    jsonRoute(versionFixture())
  );

  await page.route(
    `${API}/api/regx/v1/iig-checklists/executions/${EXECUTION_ID}/responses/`,
    (route) =>
      jsonRoute(
        paginate([
          responseFixture({
            raw_value: state.manualValue === "" ? null : { value: state.manualValue },
            version: state.manualVersion,
          }),
          calculatedFixture(state.manualVersion + 1, state.calc),
        ])
      )(route)
  );

  await page.route(
    `${API}/api/regx/v1/iig-checklists/executions/${EXECUTION_ID}/responses/${MANUAL_ID}/`,
    async (route) => {
      const body = route.request().postDataJSON() as Record<string, unknown>;
      patchBodies.push(body);
      // The governed write succeeded and the backend cascaded; the next
      // collection read reflects both.
      // The client sends the enveloped shape, so unwrap it the way the real
      // serializer would before storing.
      const envelope = body["raw_value"] as { value?: unknown } | null | undefined;
      state.manualValue = envelope == null ? "" : String(envelope.value ?? "");
      state.manualVersion += 1;
      state.calc = state.manualValue === "" ? DATA_REQUIRED : COMPLETE_AFTER;
      await jsonRoute(
        responseFixture({
          raw_value: state.manualValue === "" ? null : { value: state.manualValue },
          version: state.manualVersion,
        })
      )(route);
    }
  );

  return patchBodies;
}

function executionUrl() {
  return `/iig-checklists/executions/${EXECUTION_ID}?tenant=${TENANT}`;
}

test.describe("Milestone 4D-3 calculated results", () => {
  test("a manual edit cascades and the calculated result refreshes without a calculate action", async ({
    page,
  }) => {
    const state = { manualValue: "50", manualVersion: 4, calc: { ...COMPLETE_BEFORE } };
    const patchBodies = await mockExecutionPage(page, state);

    await page.goto(executionUrl());

    // 1-3. execution opens; manual response editable, calculated one read-only.
    const manualRow = page.getByTestId(`response-${MANUAL_ID}`);
    const calcRow = page.getByTestId(`response-${CALC_ID}`);
    await expect(manualRow).toHaveAttribute("data-editable", "true");
    await expect(calcRow).toHaveAttribute("data-editable", "false");
    await expect(calcRow.getByRole("button")).toHaveCount(0);
    await expect(calcRow.getByRole("textbox")).toHaveCount(0);

    // The calculated value is visible before the edit.
    await expect(page.getByTestId("calculation-value")).toHaveText(/25\.0000000000/);
    await expect(page.getByTestId("calculation-unit")).toHaveText("gram");

    // 10. there is no client-side "Calculate" affordance anywhere.
    await expect(page.getByRole("button", { name: /calculate|recalculate/i })).toHaveCount(0);

    // 4-5. edit the manual response and save.
    await manualRow.getByRole("textbox").fill("75");
    await manualRow.getByRole("button", { name: /save/i }).click();

    // 7-9. the cascade ran server-side and the refetch shows the new result.
    await expect(page.getByTestId("calculation-value")).toHaveText(/75\.0000000000/);
    await expect(page.getByTestId("calculation-value")).not.toHaveText(/25\.0000000000/);

    // 6. the governed write carried the version that was loaded, not a default.
    expect(patchBodies).toHaveLength(1);
    expect(patchBodies[0]).toMatchObject({
      expected_version: 4,
      raw_value: { value: "75" },
    });

    // 11-12. a reload still serves the recalculated value.
    await page.reload();
    await expect(page.getByTestId("calculation-value")).toHaveText(/75\.0000000000/);
  });

  test("clearing the upstream answer shows DATA_REQUIRED and hides the previous value", async ({
    page,
  }) => {
    const state = { manualValue: "50", manualVersion: 4, calc: { ...COMPLETE_BEFORE } };
    await mockExecutionPage(page, state);

    await page.goto(executionUrl());
    await expect(page.getByTestId("calculation-value")).toHaveText(/25\.0000000000/);

    const manualRow = page.getByTestId(`response-${MANUAL_ID}`);
    await manualRow.getByRole("textbox").fill("");
    await manualRow.getByRole("button", { name: /save/i }).click();

    const state_ = page.getByTestId("calculation-state");
    await expect(state_).toHaveAttribute("data-status", "data_required");
    await expect(state_).toHaveText("Data required");
    // The superseded result is gone, not merely relabelled.
    await expect(page.getByTestId("calculation-value")).toHaveCount(0);
    await expect(page.getByText("25.0000000000")).toHaveCount(0);
  });

  test("a stale version refreshes authoritative state instead of keeping the rejected edit", async ({
    page,
  }) => {
    const state = { manualValue: "50", manualVersion: 4, calc: { ...COMPLETE_BEFORE } };
    await mockExecutionPage(page, state);

    // Override the PATCH with a governed 409 after the page has loaded.
    await page.route(
      `${API}/api/regx/v1/iig-checklists/executions/${EXECUTION_ID}/responses/${MANUAL_ID}/`,
      jsonRoute({ error_code: "stale_version", detail: "stale" }, 409)
    );

    await page.goto(executionUrl());
    const manualRow = page.getByTestId(`response-${MANUAL_ID}`);
    await manualRow.getByRole("textbox").fill("999");
    await manualRow.getByRole("button", { name: /save/i }).click();

    // Scoped to the responses section: Next.js's route announcer is also
    // role="alert", so an unscoped locator is ambiguous.
    await expect(
      page.getByTestId("checklist-responses").getByRole("alert")
    ).toContainText(/changed since you loaded it/i);
    // The rejected client value did not survive the refetch.
    await expect(manualRow.getByRole("textbox")).toHaveValue("50");
  });
});
