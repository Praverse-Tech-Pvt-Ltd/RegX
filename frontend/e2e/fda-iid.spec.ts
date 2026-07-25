// FDA data governance / Orange Book / formulation / IID assessment
// Playwright suite.
//
// As in migration-governance.spec.ts, every backend response here is a
// deterministic Playwright route mock (page.route), not a live backend.
// Server-side enforcement (permissions, tenant isolation, matching/
// calculation/decision correctness) is covered by the backend pytest
// suite (fda_data/, formulations/, iid_assessment/ tests) instead. This
// suite proves the FRONTEND renders and reacts correctly to those API
// contracts. Fixtures are synthetic and non-confidential.
import { test, expect, type Route } from "@playwright/test";

const TENANT = "alpha";
const API = "http://localhost:8000";

function jsonRoute(body: unknown, status = 200) {
  return (route: Route) =>
    route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
}

function paginate(results: unknown[]) {
  return { count: results.length, next: null, previous: null, results };
}

async function mockCsrf(page: import("@playwright/test").Page) {
  await page.route(`${API}/api/regx/v1/auth/csrf/`, jsonRoute({ csrfToken: "e2e-csrf-token" }));
}

test.describe("FDA release inventory", () => {
  test("loads and lists a registered release", async ({ page }) => {
    await page.route(
      /\/api\/regx\/v1\/fda-data\/releases\/(\?[^/]*)?$/,
      jsonRoute(
        paginate([
          {
            public_id: "release-e2e-1",
            dataset_type: "fda_iid",
            source_name: "Synthetic FDA IID",
            official_source_reference: "synthetic://fda-iid",
            schema_version: "",
            publication_date: "2026-01-01",
            retrieved_at: null,
            imported_at: null,
            imported_by_email: null,
            record_count_expected: 2,
            record_count_extracted: 2,
            record_count_imported: 2,
            record_count_failed: 0,
            status: "registered",
            approved_by_email: null,
            approved_at: null,
            activated_by_email: null,
            activated_at: null,
            superseded_by_release: null,
            correlation_id: "corr-1",
            created_at: "2026-01-01T00:00:00Z",
          },
        ]),
      ),
    );

    await page.goto(`/fda-data/releases?tenant=${TENANT}`);
    await expect(page.getByRole("heading", { name: "FDA Data-Source Releases" })).toBeVisible();
    const row = page.getByRole("row", { name: /Synthetic FDA IID/i });
    await expect(row.getByText(/registered/i)).toBeVisible();
  });

  test("new release registration navigates to detail and does not auto-activate", async ({ page }) => {
    await mockCsrf(page);
    const newRelease = {
      public_id: "release-e2e-2",
      dataset_type: "fda_iid",
      source_name: "New Synthetic Release",
      official_source_reference: "synthetic://ref",
      schema_version: "",
      publication_date: null,
      retrieved_at: null,
      imported_at: null,
      imported_by_email: null,
      record_count_expected: 0,
      record_count_extracted: 0,
      record_count_imported: 0,
      record_count_failed: 0,
      status: "registered",
      approved_by_email: null,
      approved_at: null,
      activated_by_email: null,
      activated_at: null,
      superseded_by_release: null,
      correlation_id: "corr-2",
      created_at: "2026-01-01T00:00:00Z",
    };
    await page.route(/\/api\/regx\/v1\/fda-data\/releases\/$/, async (route) => {
      if (route.request().method() === "POST") {
        return route.fulfill(await jsonMock(newRelease, 201));
      }
      return route.fulfill(await jsonMock(paginate([])));
    });
    await page.route(
      /\/api\/regx\/v1\/fda-data\/releases\/release-e2e-2\/$/,
      jsonRoute(newRelease),
    );

    await page.goto(`/fda-data/releases?tenant=${TENANT}`);
    await page.getByRole("link", { name: /register release/i }).click();
    await expect(page).toHaveURL(/\/fda-data\/releases\/new/);

    await page.getByLabel(/source name/i).fill("New Synthetic Release");
    await page.getByLabel(/official source reference/i).fill("synthetic://ref");
    await page.getByRole("button", { name: /^register$/i }).click();

    await expect(page).toHaveURL(/\/fda-data\/releases\/release-e2e-2/);
    await expect(page.getByRole("heading", { name: "New Synthetic Release" })).toBeVisible();
    await expect(page.getByText(/^registered$/i)).toBeVisible();
    await expect(page.getByText(/^active$/i)).not.toBeVisible();
  });
});

async function jsonMock(body: unknown, status = 200) {
  return { status, contentType: "application/json", body: JSON.stringify(body) };
}

function jsonRouteBody(body: unknown, status = 200) {
  return { status, contentType: "application/json", body: JSON.stringify(body) };
}

test.describe("Orange Book search", () => {
  test("searches and shows FDA-sourced results", async ({ page }) => {
    await page.route(
      /\/api\/regx\/v1\/fda-data\/orange-book\/products\/(\?[^/]*)?$/,
      jsonRoute(
        paginate([
          {
            public_id: "ob-e2e-1",
            release: "release-e2e-1",
            application_number: "099999",
            application_type: "A",
            product_number: "001",
            trade_name: "Synthacet",
            active_ingredient_raw: "SYNTHETIC-ACETAMINOPHEN",
            dosage_form_raw: "TABLET",
            route_raw: "ORAL",
            dosage_form_normalized: "Tablet",
            route_normalized: "Oral",
            strength_raw: "500MG",
            strength_amount: "500",
            strength_parse_status: "parsed",
            rld_flag: true,
            reference_standard_flag: true,
            te_code: "AB",
            approval_date: null,
            approval_date_text: "Jan 1, 2000",
            discontinued: false,
          },
        ]),
      ),
    );

    await page.goto(`/fda-data/orange-book?tenant=${TENANT}`);
    await page.getByPlaceholder(/active ingredient/i).fill("acetaminophen");
    await page.getByRole("button", { name: /^search$/i }).click();
    await expect(page.getByText("Synthacet")).toBeVisible();
  });
});

test.describe("Formulation record and explicit reference selection", () => {
  test("creating a product record and selecting a reference product requires explicit confirmation", async ({
    page,
  }) => {
    await mockCsrf(page);
    let selected = false;
    await page.route(/\/api\/regx\/v1\/formulations\/products\/$/, async (route) => {
      if (route.request().method() === "POST") {
        return route.fulfill(
          await jsonMock(
            {
              public_id: "product-e2e-1",
              product_code: "PROD-E2E",
              proposed_product_name: "Synthetic Tablet",
              active_ingredient: "Synthetic Starch",
              is_combination_product: false,
              release_type: "immediate",
              route: "",
              dosage_form: "",
              proposed_strength_amount: null,
              proposed_strength_unit: "",
              regulatory_market_context: "",
              selected_ob_application_number: "",
              selected_ob_product_number: "",
              selected_ob_product_public_id: null,
              selected_ob_release_public_id: null,
              selection_timestamp: null,
              selecting_user_email: null,
              selection_justification: "",
              status: "draft",
              created_at: "2026-01-01T00:00:00Z",
            },
            201,
          ),
        );
      }
      return route.fulfill(await jsonMock(paginate([])));
    });

    await page.route(
      /\/api\/regx\/v1\/formulations\/products\/product-e2e-1\/$/,
      async (route) => {
        route.fulfill(
          await jsonMock({
            public_id: "product-e2e-1",
            product_code: "PROD-E2E",
            proposed_product_name: "Synthetic Tablet",
            active_ingredient: "Synthetic Starch",
            is_combination_product: false,
            release_type: "immediate",
            route: "",
            dosage_form: "",
            proposed_strength_amount: null,
            proposed_strength_unit: "",
            regulatory_market_context: "",
            selected_ob_application_number: selected ? "099999" : "",
            selected_ob_product_number: selected ? "001" : "",
            selected_ob_product_public_id: selected ? "ob-e2e-1" : null,
            selected_ob_release_public_id: selected ? "release-e2e-1" : null,
            selection_timestamp: selected ? "2026-01-02T00:00:00Z" : null,
            selecting_user_email: selected ? "vp@example.com" : null,
            selection_justification: selected ? "Exact match." : "",
            status: "draft",
            created_at: "2026-01-01T00:00:00Z",
          }),
        );
      },
    );

    await page.route(
      /\/api\/regx\/v1\/formulations\/products\/product-e2e-1\/select-reference\/$/,
      async (route) => {
        selected = true;
        route.fulfill(
          await jsonMock({
            public_id: "product-e2e-1",
            product_code: "PROD-E2E",
            proposed_product_name: "Synthetic Tablet",
            active_ingredient: "Synthetic Starch",
            is_combination_product: false,
            release_type: "immediate",
            route: "",
            dosage_form: "",
            proposed_strength_amount: null,
            proposed_strength_unit: "",
            regulatory_market_context: "",
            selected_ob_application_number: "099999",
            selected_ob_product_number: "001",
            selected_ob_product_public_id: "ob-e2e-1",
            selected_ob_release_public_id: "release-e2e-1",
            selection_timestamp: "2026-01-02T00:00:00Z",
            selecting_user_email: "vp@example.com",
            selection_justification: "",
            status: "draft",
            created_at: "2026-01-01T00:00:00Z",
          }),
        );
      },
    );
    await page.route(
      /\/api\/regx\/v1\/formulations\/products\/product-e2e-1\/versions\/(\?[^/]*)?$/,
      jsonRoute(paginate([])),
    );

    await page.goto(`/formulations?tenant=${TENANT}`);
    await page.getByRole("link", { name: /new product record/i }).click();
    await expect(page).toHaveURL(/\/formulations\/new/);
    await page.getByLabel(/product code/i).fill("PROD-E2E");
    await page.getByLabel(/proposed product name/i).fill("Synthetic Tablet");
    await page.getByLabel(/active ingredient/i).fill("Synthetic Starch");
    await page.getByRole("button", { name: /^create$/i }).click();

    await expect(page).toHaveURL(/\/formulations\/product-e2e-1/);
    await expect(page.getByText(/No reference product selected/i)).toBeVisible();
    await page.getByRole("button", { name: /select reference product/i }).click();
    await page.getByLabel(/application number/i).fill("099999");
    await page.getByLabel(/product number/i).fill("001");
    await page.getByLabel(/orange book product id/i).fill("ob-e2e-1");
    await page.getByLabel(/fda release id/i).fill("release-e2e-1");

    // Submitting without the confirmation checkbox must not select anything.
    await page.getByRole("button", { name: /confirm selection/i }).click();
    await expect(page.getByText(/explicitly confirm/i)).toBeVisible();
    await expect(page.getByText(/No reference product selected/i)).toBeVisible();

    await page.getByLabel(/I confirm this is the correct reference product/i).check();
    await page.getByRole("button", { name: /confirm selection/i }).click();
    await expect(page.getByText(/Application 099999-001/i)).toBeVisible();
  });
});

test.describe("IID assessment preview", () => {
  async function mockPreview(page: import("@playwright/test").Page, body: unknown) {
    await page.route(/\/api\/regx\/v1\/iid-assessments\/preview\/$/, jsonRoute(body));
  }

  async function fillAndRun(page: import("@playwright/test").Page) {
    await mockCsrf(page);
    await page.getByLabel(/ingredient id/i).fill("ing-1");
    await page.getByLabel(/active fda release id/i).fill("rel-1");
    await page.getByLabel(/^route code/i).fill("oral");
    await page.getByLabel(/dosage form code/i).fill("tablet");
    await page.getByLabel(/proposed quantity per unit/i).fill("30");
    await page.getByLabel(/total dosage-unit weight/i).fill("500");
    await page.getByRole("button", { name: /run preview/i }).click();
  }

  test("exact match within precedent shows the required disclaimer and no automatic safety language", async ({
    page,
  }) => {
    await mockPreview(page, {
      match_status: "EXACT_MATCH",
      candidates: [
        {
          precedent_record_public_id: "prec-1",
          ingredient_name: "Synthetic Starch",
          route: "Oral",
          dosage_form: "Tablet",
          potency_amount: "50.000000",
          potency_unit: "milligram",
          maximum_daily_exposure: "200.000000",
          mde_unit: "milligram",
          calculability_status: "calculable",
        },
      ],
      selected_record: {
        precedent_record_public_id: "prec-1",
        ingredient_name: "Synthetic Starch",
        route: "Oral",
        dosage_form: "Tablet",
        potency_amount: "50.000000",
        potency_unit: "milligram",
        maximum_daily_exposure: "200.000000",
        mde_unit: "milligram",
        calculability_status: "calculable",
      },
      calculations: {
        unit_conversion: { status: "OK", ok: true },
        percentage_w_w: { status: "OK", value: "6", unit: "percent_w_w" },
        daily_exposure: { status: "OK", value: "120" },
        percentage_of_iid_potency: { status: "OK", value: "60", unit: "percent_of_potency" },
      },
      decision_status: "PASS_WITH_IID_PRECEDENT",
      decision_note:
        "Within selected FDA IID precedent. This is not an automatic safety determination or regulatory approval.",
      escalation_required: false,
    });

    await page.goto(`/iid-assessments/preview?tenant=${TENANT}`);
    await fillAndRun(page);

    await expect(page.getByText(/not an automatic safety determination or regulatory approval/i)).toBeVisible();
    const bodyText = (await page.textContent("body")) ?? "";
    for (const forbidden of [/\bSAFE\b/i, /FDA APPROVED/i, /AUTOMATICALLY ACCEPTABLE/i, /REGULATORILY CLEARED/i]) {
      expect(bodyText).not.toMatch(forbidden);
    }
  });

  test("multiple exact matches require explicit reviewer selection, never auto-picked", async ({ page }) => {
    await mockPreview(page, {
      match_status: "MULTIPLE_EXACT_MATCHES",
      candidates: [
        {
          precedent_record_public_id: "prec-low",
          ingredient_name: "Synthetic Starch",
          route: "Oral",
          dosage_form: "Tablet",
          potency_amount: "10.000000",
          potency_unit: "milligram",
          maximum_daily_exposure: null,
          mde_unit: null,
          calculability_status: "calculable",
        },
        {
          precedent_record_public_id: "prec-high",
          ingredient_name: "Synthetic Starch",
          route: "Oral",
          dosage_form: "Tablet",
          potency_amount: "500.000000",
          potency_unit: "milligram",
          maximum_daily_exposure: null,
          mde_unit: null,
          calculability_status: "calculable",
        },
      ],
      selected_record: null,
      calculations: {},
      decision_status: "REVIEW_REQUIRED",
      decision_note: "Multiple exact IID records match; a reviewer must select the precedent record to use.",
      escalation_required: true,
    });

    await page.goto(`/iid-assessments/preview?tenant=${TENANT}`);
    await fillAndRun(page);

    await expect(page.getByText(/Review required/i)).toBeVisible();
    await expect(page.getByRole("button", { name: /select this precedent/i })).toHaveCount(2);
  });

  test("route mismatch is shown distinctly and never treated as comparable", async ({ page }) => {
    await mockPreview(page, {
      match_status: "ROUTE_MISMATCH",
      candidates: [],
      selected_record: null,
      calculations: {},
      decision_status: "NOT_COMPARABLE",
      decision_note: "ROUTE_MISMATCH: route and dosage form must match exactly.",
      escalation_required: false,
    });

    await page.goto(`/iid-assessments/preview?tenant=${TENANT}`);
    await fillAndRun(page);
    await expect(page.getByText(/ROUTE MISMATCH/)).toBeVisible();
  });

  test("exceeding the IID precedent shows an escalation warning, never a pass", async ({ page }) => {
    await mockPreview(page, {
      match_status: "EXACT_MATCH",
      candidates: [],
      selected_record: {
        precedent_record_public_id: "prec-1",
        ingredient_name: "Synthetic Starch",
        route: "Oral",
        dosage_form: "Tablet",
        potency_amount: "50.000000",
        potency_unit: "milligram",
        maximum_daily_exposure: "200.000000",
        mde_unit: "milligram",
        calculability_status: "calculable",
      },
      calculations: {
        unit_conversion: { status: "OK", ok: true },
      },
      decision_status: "EXCEEDS_IID_PRECEDENT",
      decision_note:
        "Proposed amount per dosage unit exceeds the selected IID potency precedent. Justification and reviewer conclusion are mandatory; approval cannot be automatic.",
      escalation_required: true,
    });

    await page.goto(`/iid-assessments/preview?tenant=${TENANT}`);
    await fillAndRun(page);
    await expect(page.getByText(/Exceeds IID precedent/i)).toBeVisible();
    await expect(page.getByText(/Reviewer escalation required/i)).toBeVisible();
  });

  test("source provenance is visible on the selected IID precedent", async ({ page }) => {
    await mockPreview(page, {
      match_status: "EXACT_MATCH",
      candidates: [],
      selected_record: {
        precedent_record_public_id: "prec-1",
        ingredient_name: "Synthetic Starch",
        route: "Oral",
        dosage_form: "Tablet",
        potency_amount: "50.000000",
        potency_unit: "milligram",
        maximum_daily_exposure: "200.000000",
        mde_unit: "milligram",
        calculability_status: "calculable",
      },
      calculations: {},
      decision_status: "PASS_WITH_IID_PRECEDENT",
      decision_note:
        "Within selected FDA IID precedent. This is not an automatic safety determination or regulatory approval.",
      escalation_required: false,
    });

    await page.goto(`/iid-assessments/preview?tenant=${TENANT}`);
    await fillAndRun(page);
    await expect(page.getByTestId("provenance-label").filter({ hasText: "FDA SOURCE" }).first()).toBeVisible();
  });

  test("dosage-form mismatch is shown distinctly and never treated as comparable", async ({ page }) => {
    await mockPreview(page, {
      match_status: "DOSAGE_FORM_MISMATCH",
      candidates: [],
      selected_record: null,
      calculations: {},
      decision_status: "NOT_COMPARABLE",
      decision_note: "DOSAGE_FORM_MISMATCH: route and dosage form must match exactly.",
      escalation_required: false,
    });
    await page.goto(`/iid-assessments/preview?tenant=${TENANT}`);
    await fillAndRun(page);
    await expect(page.getByText(/DOSAGE-FORM MISMATCH/)).toBeVisible();
  });

  test("unit mismatch is shown when the proposed unit cannot be reconciled with the precedent", async ({
    page,
  }) => {
    await mockPreview(page, {
      match_status: "EXACT_MATCH",
      candidates: [],
      selected_record: {
        precedent_record_public_id: "prec-1",
        ingredient_name: "Synthetic Starch",
        route: "Oral",
        dosage_form: "Tablet",
        potency_amount: "50.000000",
        potency_unit: "milligram",
        maximum_daily_exposure: "200.000000",
        mde_unit: "milligram",
        calculability_status: "calculable",
      },
      calculations: {
        unit_conversion: { status: "UNIT_MISMATCH", ok: false },
      },
      decision_status: "NOT_COMPARABLE",
      decision_note: "Unit or basis could not be reconciled between the proposed formulation and the selected IID record.",
      escalation_required: false,
    });
    await page.goto(`/iid-assessments/preview?tenant=${TENANT}`);
    await fillAndRun(page);
    await expect(page.getByText(/Blocked: UNIT_MISMATCH/)).toBeVisible();
    await expect(page.getByText(/Not comparable/i)).toBeVisible();
  });

  test("missing-MDE shows review-required, never a fabricated MDE value", async ({ page }) => {
    await mockPreview(page, {
      match_status: "EXACT_MATCH",
      candidates: [],
      selected_record: {
        precedent_record_public_id: "prec-1",
        ingredient_name: "Synthetic Starch",
        route: "Oral",
        dosage_form: "Tablet",
        potency_amount: "50.000000",
        potency_unit: "milligram",
        maximum_daily_exposure: null,
        mde_unit: null,
        calculability_status: "calculable",
      },
      calculations: {
        unit_conversion: { status: "OK", ok: true },
        percentage_of_iid_potency: { status: "OK", value: "60", unit: "percent_of_potency" },
      },
      decision_status: "REVIEW_REQUIRED",
      decision_note: "Within selected IID potency precedent, but maximum daily exposure precedent is unavailable for comparison.",
      escalation_required: true,
    });
    await page.goto(`/iid-assessments/preview?tenant=${TENANT}`);
    await fillAndRun(page);
    await expect(page.getByText(/MDE UNAVAILABLE/)).toBeVisible();
    await expect(page.getByText(/Review required/i)).toBeVisible();
    await expect(page.getByText(/Reviewer escalation required/i)).toBeVisible();
  });

  test("percentage w/w and daily-exposure calculations are displayed with calculated provenance", async ({
    page,
  }) => {
    await mockPreview(page, {
      match_status: "EXACT_MATCH",
      candidates: [],
      selected_record: {
        precedent_record_public_id: "prec-1",
        ingredient_name: "Synthetic Starch",
        route: "Oral",
        dosage_form: "Tablet",
        potency_amount: "50.000000",
        potency_unit: "milligram",
        maximum_daily_exposure: "200.000000",
        mde_unit: "milligram",
        calculability_status: "calculable",
      },
      calculations: {
        unit_conversion: { status: "OK", ok: true },
        percentage_w_w: { status: "OK", value: "6", unit: "percent_w_w" },
        daily_exposure: { status: "OK", value: "120" },
      },
      decision_status: "PASS_WITH_IID_PRECEDENT",
      decision_note:
        "Within selected FDA IID precedent. This is not an automatic safety determination or regulatory approval.",
      escalation_required: false,
    });
    await page.goto(`/iid-assessments/preview?tenant=${TENANT}`);
    await fillAndRun(page);
    await expect(page.getByText(/Percentage w\/w/i)).toBeVisible();
    await expect(page.getByText("6 percent_w_w")).toBeVisible();
    await expect(page.getByText(/Daily exposure/i)).toBeVisible();
    await expect(page.getByText("120")).toBeVisible();
  });

  test("no automatic quantity defaulting -- proposed field never pre-fills from a precedent", async ({
    page,
  }) => {
    await page.goto(`/iid-assessments/preview?tenant=${TENANT}`);
    await expect(page.getByLabel(/proposed quantity per unit/i)).toHaveValue("");
  });

  test("an API error surfaces distinctly, not as a fabricated result", async ({ page }) => {
    await page.route(/\/api\/regx\/v1\/iid-assessments\/preview\/$/, (route) =>
      route.fulfill({ status: 400, contentType: "application/json", body: JSON.stringify({ detail: "Invalid ingredient identity." }) }),
    );
    await page.goto(`/iid-assessments/preview?tenant=${TENANT}`);
    await fillAndRun(page);
    await expect(page.getByText(/Invalid ingredient identity/i)).toBeVisible();
  });
});

test.describe("FDA release reconciliation screen", () => {
  test("shows counts and per-row reconciliation results", async ({ page }) => {
    await page.route(
      /\/api\/regx\/v1\/fda-data\/releases\/release-e2e-1\/reconciliation\.json$/,
      jsonRoute({
        release: { public_id: "release-e2e-1", dataset_type: "fda_iid", status: "registered" },
        counts: { expected: 2, extracted: 2, imported: 1, failed: 1 },
        results: [
          {
            public_id: "row-1",
            row_locator: "row:0",
            target_public_identifier: "target-1",
            result: "imported",
            reason_code: "",
            safe_detail: "",
          },
          {
            public_id: "row-2",
            row_locator: "row:1",
            target_public_identifier: null,
            result: "failed",
            reason_code: "potency_missing",
            safe_detail: "",
          },
        ],
      }),
    );
    await page.goto(`/fda-data/releases/release-e2e-1/reconciliation?tenant=${TENANT}`);
    await expect(page.getByText("row:0")).toBeVisible();
    await expect(page.getByText(/potency_missing/i)).toBeVisible();
  });

  test("a permission-denied reconciliation request shows a distinct error, not a blank page", async ({
    page,
  }) => {
    await page.route(
      /\/api\/regx\/v1\/fda-data\/releases\/release-e2e-1\/reconciliation\.json$/,
      (route) => route.fulfill({ status: 403, contentType: "application/json", body: JSON.stringify({ detail: "Forbidden" }) }),
    );
    await page.goto(`/fda-data/releases/release-e2e-1/reconciliation?tenant=${TENANT}`);
    await expect(page.getByText(/permission/i)).toBeVisible();
  });
});

test.describe("Terminology mapping review", () => {
  test("lists a proposed mapping and requires explicit confirmation to approve, never auto-approved", async ({
    page,
  }) => {
    await mockCsrf(page);
    let status = "proposed";
    await page.route(/\/api\/regx\/v1\/fda-data\/mappings\/(\?[^/]*)?$/, (route) =>
      route.fulfill(
        {
          status: 200,
          contentType: "application/json",
          body: JSON.stringify(
            paginate([
              {
                public_id: "mapping-e2e-1",
                mapping_type: "route",
                source_dataset: "fda_iid",
                source_raw_value: "ORAL",
                proposed_controlled_value: "Oral",
                status,
                is_current: true,
                reviewer_email: status === "approved" ? "vp@example.com" : null,
                reason: "",
                affected_record_count: 3,
                created_at: "2026-01-01T00:00:00Z",
              },
            ]),
          ),
        },
      ),
    );
    await page.route(
      /\/api\/regx\/v1\/fda-data\/mappings\/mapping-e2e-1\/approve\/$/,
      async (route) => {
        status = "approved";
        return route.fulfill(await jsonMock({ status: "approved" }));
      },
    );

    await page.goto(`/fda-data/mappings?tenant=${TENANT}`);
    await expect(page.getByText("ORAL", { exact: true })).toBeVisible();
    await expect(page.getByText("proposed", { exact: true })).toBeVisible();

    await page.getByRole("button", { name: /^approve$/i }).click();
    const dialog = page.getByRole("dialog");
    await expect(dialog).toBeVisible();

    await dialog.getByRole("button", { name: /^confirm$/i }).click();
    await expect(page.getByText("approved", { exact: true })).toBeVisible();
  });

  const SYNTHETIC_SUBSTANCE_MAPPING = {
    public_id: "substance-mapping-e2e-1",
    mapping_type: "substance",
    source_dataset: "fda_iid",
    source_raw_value: "SYNTHETIC-ACETAMINOPHEN",
    proposed_controlled_value: "Acetaminophen (synthetic)",
    status: "proposed",
    is_current: true,
    reviewer_email: null,
    reason: "",
    affected_record_count: 2,
    created_at: "2026-01-01T00:00:00Z",
    proposed_unii: "SYN0001",
    proposed_cas_number: "9005-25-8",
    mapping_method: "exact_unii",
    release_public_id: "release-e2e-1",
  };

  test("filters the mapping inventory to substance/UNII synonyms", async ({ page }) => {
    await mockCsrf(page);
    await page.route(/\/api\/regx\/v1\/fda-data\/mappings\/(\?[^/]*)?$/, (route) => {
      const url = new URL(route.request().url());
      const type = url.searchParams.get("type");
      const results = type === "substance" ? [SYNTHETIC_SUBSTANCE_MAPPING] : [];
      return route.fulfill(jsonRouteBody(paginate(results)));
    });

    await page.goto(`/fda-data/mappings?tenant=${TENANT}`);
    await page.getByRole("tab", { name: /substance/i }).click();
    await expect(page.getByText("SYNTHETIC-ACETAMINOPHEN")).toBeVisible();
    await expect(page.getByText("SYN0001")).toBeVisible();
  });

  test("inspects a proposed synonym mapping and opens the affected-record drill-down", async ({
    page,
  }) => {
    await mockCsrf(page);
    await page.route(/\/api\/regx\/v1\/fda-data\/mappings\/(\?[^/]*)?$/, (route) =>
      route.fulfill(jsonRouteBody(paginate([SYNTHETIC_SUBSTANCE_MAPPING]))),
    );
    await page.route(
      /\/api\/regx\/v1\/fda-data\/mappings\/substance-mapping-e2e-1\/$/,
      (route) => route.fulfill(jsonRouteBody(SYNTHETIC_SUBSTANCE_MAPPING)),
    );
    await page.route(
      /\/api\/regx\/v1\/fda-data\/mappings\/substance-mapping-e2e-1\/affected-records\/(\?[^/]*)?$/,
      (route) =>
        route.fulfill(
          jsonRouteBody(
            paginate([
              {
                record_public_id: "iid-record-e2e-1",
                dataset_type: "fda_iid",
                release_public_id: "release-e2e-1",
                source_row_locator: "row:0",
                raw_value: "SYNTHETIC-ACETAMINOPHEN",
                normalized_value: "Acetaminophen (synthetic)",
                mapping_status: "proposed",
                calculability_status: "calculable",
                blocked: false,
                reason_code: "calculable",
              },
            ]),
          ),
        ),
    );

    await page.goto(`/fda-data/mappings?tenant=${TENANT}`);
    await expect(page.getByText("SYNTHETIC-ACETAMINOPHEN")).toBeVisible();
    await page.getByRole("link", { name: /record\(s\)/i }).click();
    await expect(page).toHaveURL(/\/fda-data\/mappings\/substance-mapping-e2e-1/);
    await expect(page.getByRole("heading", { name: /affected records/i })).toBeVisible();
    // DETECT: no raw storage path or internal numeric ID anywhere on the
    // drill-down page.
    const bodyText = await page.locator("body").innerText();
    expect(bodyText).not.toContain("/var/");
    expect(bodyText).not.toMatch(/\bid["']?\s*:\s*\d+/);
  });

  test("approves a substance mapping via the type-less endpoint", async ({ page }) => {
    await mockCsrf(page);
    let status = "proposed";
    await page.route(/\/api\/regx\/v1\/fda-data\/mappings\/(\?[^/]*)?$/, (route) =>
      route.fulfill(
        jsonRouteBody(paginate([{ ...SYNTHETIC_SUBSTANCE_MAPPING, status }])),
      ),
    );
    await page.route(
      /\/api\/regx\/v1\/fda-data\/mappings\/substance-mapping-e2e-1\/approve\/$/,
      async (route) => {
        status = "approved";
        return route.fulfill(await jsonMock({ status: "approved" }));
      },
    );

    await page.goto(`/fda-data/mappings?tenant=${TENANT}`);
    await page.getByRole("tab", { name: /substance/i }).click();
    await expect(page.getByText("SYNTHETIC-ACETAMINOPHEN")).toBeVisible();
    await page.getByRole("button", { name: /^approve$/i }).click();
    await page.getByRole("dialog").getByRole("button", { name: /^confirm$/i }).click();
    await expect(page.getByText("approved", { exact: true })).toBeVisible();
  });

  test("rejects a substance mapping", async ({ page }) => {
    await mockCsrf(page);
    let status = "proposed";
    await page.route(/\/api\/regx\/v1\/fda-data\/mappings\/(\?[^/]*)?$/, (route) =>
      route.fulfill(
        jsonRouteBody(paginate([{ ...SYNTHETIC_SUBSTANCE_MAPPING, status }])),
      ),
    );
    await page.route(
      /\/api\/regx\/v1\/fda-data\/mappings\/substance-mapping-e2e-1\/reject\/$/,
      async (route) => {
        status = "rejected";
        return route.fulfill(await jsonMock({ status: "rejected" }));
      },
    );

    await page.goto(`/fda-data/mappings?tenant=${TENANT}`);
    await page.getByRole("tab", { name: /substance/i }).click();
    await expect(page.getByText("SYNTHETIC-ACETAMINOPHEN")).toBeVisible();
    await page.getByRole("button", { name: /^reject$/i }).click();
    await page.getByRole("dialog").getByRole("button", { name: /^confirm$/i }).click();
    await expect(page.getByText("rejected", { exact: true })).toBeVisible();
  });

  test("returns a substance mapping for correction", async ({ page }) => {
    await mockCsrf(page);
    let status = "under_review";
    await page.route(/\/api\/regx\/v1\/fda-data\/mappings\/(\?[^/]*)?$/, (route) =>
      route.fulfill(
        jsonRouteBody(paginate([{ ...SYNTHETIC_SUBSTANCE_MAPPING, status }])),
      ),
    );
    await page.route(
      /\/api\/regx\/v1\/fda-data\/mappings\/substance-mapping-e2e-1\/return\/$/,
      async (route) => {
        status = "returned";
        return route.fulfill(await jsonMock({ status: "returned" }));
      },
    );

    await page.goto(`/fda-data/mappings?tenant=${TENANT}`);
    await page.getByRole("tab", { name: /substance/i }).click();
    await expect(page.getByText("SYNTHETIC-ACETAMINOPHEN")).toBeVisible();
    await page.getByRole("button", { name: /return for correction/i }).click();
    await page.getByRole("dialog").getByRole("button", { name: /^confirm$/i }).click();
    await expect(page.getByText("returned", { exact: true })).toBeVisible();
  });

  test("a Doer cannot approve a mapping -- the API rejects it and the UI surfaces the error", async ({
    page,
  }) => {
    await mockCsrf(page);
    await page.route(/\/api\/regx\/v1\/fda-data\/mappings\/(\?[^/]*)?$/, (route) =>
      route.fulfill(jsonRouteBody(paginate([SYNTHETIC_SUBSTANCE_MAPPING]))),
    );
    await page.route(
      /\/api\/regx\/v1\/fda-data\/mappings\/substance-mapping-e2e-1\/approve\/$/,
      (route) =>
        route.fulfill(
          jsonRouteBody(
            { detail: "You do not have permission to perform this action." },
            403,
          ),
        ),
    );

    await page.goto(`/fda-data/mappings?tenant=${TENANT}`);
    await page.getByRole("tab", { name: /substance/i }).click();
    await expect(page.getByText("SYNTHETIC-ACETAMINOPHEN")).toBeVisible();
    await page.getByRole("button", { name: /^approve$/i }).click();
    await page.getByRole("dialog").getByRole("button", { name: /^confirm$/i }).click();
    await expect(page.getByRole("alert")).toBeVisible();
  });
});

test.describe("Orange Book filters and product detail", () => {
  const SYNTHETIC_OB_PRODUCT = {
    public_id: "ob-e2e-2",
    release: "release-e2e-1",
    application_number: "099999",
    application_type: "A",
    product_number: "002",
    trade_name: "Synthacet Forte",
    active_ingredient_raw: "SYNTHETIC-ACETAMINOPHEN",
    dosage_form_raw: "TABLET",
    route_raw: "ORAL",
    dosage_form_normalized: "Tablet",
    route_normalized: "Oral",
    strength_raw: "650MG",
    strength_amount: "650",
    strength_parse_status: "parsed",
    rld_flag: false,
    reference_standard_flag: false,
    te_code: "AB",
    approval_date: null,
    approval_date_text: "Jan 1, 2000",
    discontinued: true,
  };

  test("RLD filter narrows results to only RLD-flagged products", async ({ page }) => {
    await page.route(/\/api\/regx\/v1\/fda-data\/orange-book\/products\/(\?[^/]*)?$/, async (route) => {
      const url = new URL(route.request().url());
      if (url.searchParams.get("rld") === "true") {
        return route.fulfill(await jsonMock(paginate([])));
      }
      return route.fulfill(await jsonMock(paginate([SYNTHETIC_OB_PRODUCT])));
    });

    await page.goto(`/fda-data/orange-book?tenant=${TENANT}`);
    await page.getByRole("checkbox", { name: /RLD only/i }).check();
    await page.getByRole("button", { name: /^search$/i }).click();
    await expect(page.getByText(/No matching Orange Book products/i)).toBeVisible();
  });

  test("product detail shows FDA-sourced provenance and never implies auto-selection", async ({ page }) => {
    await page.route(
      /\/api\/regx\/v1\/fda-data\/orange-book\/products\/ob-e2e-2\/$/,
      jsonRoute(SYNTHETIC_OB_PRODUCT),
    );
    await page.goto(`/fda-data/orange-book/ob-e2e-2?tenant=${TENANT}`);
    await expect(page.getByRole("heading", { name: /Synthacet Forte/i })).toBeVisible();
    await expect(page.getByText(/never inferred from these flags/i)).toBeVisible();
  });
});

test.describe("Formulation version creation, component entry, and dosing regimen", () => {
  test("creates a product record via the standalone new-product route", async ({ page }) => {
    await mockCsrf(page);
    const product = {
      public_id: "product-e2e-2",
      product_code: "PROD-E2E-2",
      proposed_product_name: "Second Synthetic Tablet",
      active_ingredient: "Synthetic Starch",
      is_combination_product: false,
      release_type: "immediate",
      route: "",
      dosage_form: "",
      proposed_strength_amount: null,
      proposed_strength_unit: "",
      regulatory_market_context: "",
      selected_ob_application_number: "",
      selected_ob_product_number: "",
      selected_ob_product_public_id: null,
      selected_ob_release_public_id: null,
      selection_timestamp: null,
      selecting_user_email: null,
      selection_justification: "",
      status: "draft",
      created_at: "2026-01-01T00:00:00Z",
    };
    await page.route(/\/api\/regx\/v1\/formulations\/products\/$/, async (route) => {
      if (route.request().method() === "POST") return route.fulfill(await jsonMock(product, 201));
      return route.fulfill(await jsonMock(paginate([])));
    });
    await page.route(/\/api\/regx\/v1\/formulations\/products\/product-e2e-2\/$/, jsonRoute(product));
    await page.route(
      /\/api\/regx\/v1\/formulations\/products\/product-e2e-2\/versions\/(\?[^/]*)?$/,
      jsonRoute(paginate([])),
    );

    await page.goto(`/formulations?tenant=${TENANT}`);
    await page.getByRole("link", { name: /new product record/i }).click();
    await expect(page).toHaveURL(/\/formulations\/new/);

    await page.getByLabel(/product code/i).fill("PROD-E2E-2");
    await page.getByLabel(/proposed product name/i).fill("Second Synthetic Tablet");
    await page.getByLabel(/active ingredient/i).fill("Synthetic Starch");
    await page.getByRole("button", { name: /^create$/i }).click();

    await expect(page).toHaveURL(/\/formulations\/product-e2e-2/);
    await expect(page.getByRole("heading", { name: "Second Synthetic Tablet" })).toBeVisible();
  });

  test("creates a formulation version, then adds an inactive component and a dosing regimen", async ({
    page,
  }) => {
    await mockCsrf(page);
    const product = {
      public_id: "product-e2e-3",
      product_code: "PROD-E2E-3",
      proposed_product_name: "Third Synthetic Tablet",
      active_ingredient: "Synthetic Starch",
      is_combination_product: false,
      release_type: "immediate",
      route: "",
      dosage_form: "",
      proposed_strength_amount: null,
      proposed_strength_unit: "",
      regulatory_market_context: "",
      selected_ob_application_number: "",
      selected_ob_product_number: "",
      selected_ob_product_public_id: null,
      selected_ob_release_public_id: null,
      selection_timestamp: null,
      selecting_user_email: null,
      selection_justification: "",
      status: "draft",
      created_at: "2026-01-01T00:00:00Z",
    };
    const version = {
      public_id: "version-e2e-1",
      product: "product-e2e-3",
      version_number: 1,
      status: "draft",
      total_dosage_unit_weight: "500.000000",
      total_dosage_unit_weight_unit: "milligram",
      batch_size: null,
      batch_size_unit: "",
      overage_percentage: null,
      maximum_dosage_units_per_day: "4.0000",
      dosing_basis: "",
      rationale: "",
      created_at: "2026-01-01T00:00:00Z",
    };
    let versions: unknown[] = [];
    await page.route(/\/api\/regx\/v1\/formulations\/products\/product-e2e-3\/$/, jsonRoute(product));
    await page.route(
      /\/api\/regx\/v1\/formulations\/products\/product-e2e-3\/versions\/(\?[^/]*)?$/,
      async (route) => {
        if (route.request().method() === "POST") {
          versions = [version];
          return route.fulfill(await jsonMock(version, 201));
        }
        return route.fulfill(await jsonMock(paginate(versions)));
      },
    );
    await page.route(/\/api\/regx\/v1\/formulations\/versions\/version-e2e-1\/$/, jsonRoute(version));

    let components: unknown[] = [];
    await page.route(
      /\/api\/regx\/v1\/formulations\/versions\/version-e2e-1\/components\/$/,
      async (route) => {
        if (route.request().method() === "POST") {
          const body = route.request().postDataJSON();
          const component = {
            public_id: "component-e2e-1",
            component_type: body.component_type,
            ingredient_name: body.ingredient_name,
            resolved_ingredient_public_id: null,
            resolved_unii: "",
            function: "",
            grade: "",
            quantity_per_dosage_unit: body.quantity_per_dosage_unit,
            quantity_unit: body.quantity_unit,
            percentage_w_w_snapshot: null,
            quantity_per_batch: null,
            batch_quantity_unit: "",
            overage_amount: null,
            justification: "",
            specification_reference: "",
            evidence_document_reference: null,
            display_order: 0,
          };
          components = [component];
          return route.fulfill(await jsonMock(component, 201));
        }
        return route.fulfill(await jsonMock(components));
      },
    );

    let regimens: unknown[] = [];
    await page.route(
      /\/api\/regx\/v1\/formulations\/versions\/version-e2e-1\/dosing-regimens\/$/,
      async (route) => {
        if (route.request().method() === "POST") {
          const body = route.request().postDataJSON();
          const regimen = {
            public_id: "regimen-e2e-1",
            units_per_administration: body.units_per_administration,
            administrations_per_day: body.administrations_per_day,
            maximum_units_per_day: body.maximum_units_per_day,
            patient_population: "",
            basis: "",
            source_justification: "",
          };
          regimens = [regimen];
          return route.fulfill(await jsonMock(regimen, 201));
        }
        return route.fulfill(await jsonMock(regimens));
      },
    );

    await page.goto(`/formulations/product-e2e-3?tenant=${TENANT}`);
    await page.getByRole("button", { name: /create formulation version/i }).click();
    await page.getByLabel(/total dosage-unit weight/i).fill("500");
    await page.getByLabel(/^unit$/i).fill("milligram");
    await page.getByRole("button", { name: /^create version$/i }).click();

    await expect(page).toHaveURL(/\/versions\/version-e2e-1/);

    // Inactive component entry
    await page.getByRole("button", { name: /add component/i }).click();
    await page.getByLabel(/ingredient name/i).fill("Synthetic Starch");
    await page.getByLabel(/quantity per dosage unit/i).fill("30");
    await page.getByLabel(/^unit$/i).fill("milligram");
    await page.getByRole("button", { name: /^add$/i }).click();
    await expect(page.getByText("Synthetic Starch")).toBeVisible();

    // Dosing regimen entry
    await page.getByRole("button", { name: /add dosing regimen/i }).click();
    await page.getByLabel(/administrations per day/i).fill("4");
    await page.getByLabel(/maximum units per day/i).fill("4");
    await page.getByRole("button", { name: /^save$/i }).click();
    await expect(page.getByText(/unit\(s\) × 4\/day, max 4\/day/i)).toBeVisible();
  });
});
