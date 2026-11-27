// The IID preview never changes the unit the user typed (owner rule, 2026-11-26; validation
// report 2026-11-25, N-3). Typing 0.077 gram and then choosing "mg per dose unit" must be
// refused with the API's message, never compared as 0.077 mg ("at or below").
//
// API mocked with page.route, as in the other specs. The mock applies the server's rule
// (backend fda_data.controlled_units.stated_amount_problem): with the "mg per dose unit"
// meaning, the amount must be entered in mg (or milligram); otherwise 400 on
// proposed_quantity_unit. A request it accepts gets an "at or below" result, so the old
// behaviour (the page rewriting "gram" to "mg") makes this test fail on the result.
import { test, expect, type Route } from "@playwright/test";

const TENANT = "alpha";
const API = "http://localhost:8000";

const json = (body: unknown, status = 200) => (route: Route) =>
  route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });

const MEANINGS = {
  meanings: [
    { public_id: "m-mg-dose", label: "mg per dose unit", family: "mass", basis: "per_dose_unit", numerator_unit: "mg" },
    { public_id: "m-pct-ww", label: "%w/w", family: "percentage", basis: "w_w", numerator_unit: null },
  ],
};

const AT_OR_BELOW = {
  match_status: "EXACT_MATCH",
  candidates: [],
  selected_record: null,
  calculations: {
    unit_conversion: { ok: true, original_value: "0.077000", original_unit: "mg", converted_value: "0.077", converted_unit: "milligram", reason_code: null },
    potency_comparison: {
      comparable: true, result: "at_or_below", proposed_value: "0.077", iid_value: "70", unit: "mg per dose unit",
      reason: "compared like for like (same family and basis)", label: "technically comparable (not regulatorily approved)",
    },
  },
  decision_status: "REVIEW_REQUIRED",
  decision_note: "Within selected IID potency precedent, but maximum daily exposure precedent is unavailable for comparison.",
  escalation_required: true,
};

test.describe("IID preview keeps the typed unit", () => {
  test("0.077 gram + 'mg per dose unit' is refused with a clear message, never 'at or below'", async ({ page }) => {
    const sent: Record<string, unknown>[] = [];
    await page.route(`${API}/api/regx/v1/auth/csrf/`, json({ csrfToken: "e2e-csrf-token" }));
    await page.route(/\/api\/regx\/v1\/fda-data\/controlled-units\/meanings\/$/, json(MEANINGS));
    await page.route(/\/api\/regx\/v1\/iid-assessments\/preview\/$/, async (route) => {
      const body = route.request().postDataJSON() as Record<string, unknown>;
      sent.push(body);
      const unit = String(body.proposed_quantity_unit ?? "").trim().toLowerCase();
      if (body.proposed_quantity_expression_public_id === "m-mg-dose" && !["mg", "milligram", "milligrams"].includes(unit)) {
        return json(
          { error: { status: 400, detail: { proposed_quantity_unit: [`the amount must be entered in 'mg', the unit this meaning states (got '${body.proposed_quantity_unit}')`] } } },
          400,
        )(route);
      }
      return json(AT_OR_BELOW)(route);
    });

    await page.goto(`/iid-assessments/preview?tenant=${TENANT}`);
    await page.getByLabel(/ingredient id/i).fill("ing-1");
    await page.getByLabel(/active fda release id/i).fill("rel-1");
    await page.getByLabel(/^route code/i).fill("oral");
    await page.getByLabel(/dosage form code/i).fill("tablet");
    await page.getByLabel(/proposed quantity per unit/i).fill("0.077");
    await page.getByLabel(/proposed quantity unit/i).fill("gram");
    await page.getByLabel(/what the proposed quantity means/i).selectOption({ label: "mg per dose unit" });
    await expect(page.getByLabel(/proposed quantity unit/i)).toHaveValue("gram");
    await page.getByLabel(/total dosage-unit weight/i).fill("250");
    await page.getByRole("button", { name: /run preview/i }).click();

    await expect(page.getByText("the amount must be entered in 'mg', the unit this meaning states (got 'gram')")).toBeVisible();
    await expect(page.getByLabel(/proposed quantity unit/i)).toHaveAttribute("aria-invalid", "true");
    await expect(page.getByLabel(/proposed quantity unit/i)).toHaveValue("gram");
    await expect(page.getByTestId("potency-comparison")).toHaveCount(0);
    await expect(page.locator("body")).not.toContainText(/at or below/i);
    expect(sent).toHaveLength(1);
    expect(sent[0]?.proposed_quantity_unit).toBe("gram");
  });
});
