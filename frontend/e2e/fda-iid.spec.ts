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

  test("register-release form does not auto-activate the new release", async ({ page }) => {
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
    let registered = false;
    await page.route(
      /\/api\/regx\/v1\/fda-data\/releases\/(\?[^/]*)?$/,
      async (route) => {
        if (route.request().method() === "GET") {
          return route.fulfill(await jsonMock(paginate(registered ? [newRelease] : [])));
        }
        registered = true;
        return route.fulfill(await jsonMock(newRelease, 201));
      },
    );

    await page.goto(`/fda-data/releases?tenant=${TENANT}`);
    await page.getByRole("button", { name: /register release/i }).click();
    await page.getByLabel(/source name/i).fill("New Synthetic Release");
    await page.getByLabel(/official source reference/i).fill("synthetic://ref");
    await page.getByRole("button", { name: /^register$/i }).click();

    const row = page.getByRole("row", { name: /New Synthetic Release/i });
    await expect(row.getByText(/registered/i)).toBeVisible();
    await expect(row.getByText(/^active$/i)).not.toBeVisible();
  });
});

async function jsonMock(body: unknown, status = 200) {
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

    await page.goto(`/formulations?tenant=${TENANT}`);
    await page.getByRole("button", { name: /new product record/i }).click();
    await page.getByLabel(/product code/i).fill("PROD-E2E");
    await page.getByLabel(/proposed product name/i).fill("Synthetic Tablet");
    await page.getByLabel(/active ingredient/i).fill("Synthetic Starch");
    await page.getByRole("button", { name: /^create$/i }).click();

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
});
