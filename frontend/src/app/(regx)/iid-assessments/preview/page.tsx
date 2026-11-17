"use client";

import { Suspense, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import { iidAssessments, type AssessmentPreview, type MatchCandidate, ApiError } from "@/lib/api";
import { ProvenanceLabel } from "@/components/ProvenanceLabel";
import { PercentValue } from "@/components/PercentValue";
import { isPercentUnit } from "@/lib/percent";

// Human-readable labels for every match/decision status the backend can
// return. Never SAFE / FDA APPROVED / AUTOMATICALLY ACCEPTABLE /
// REGULATORILY CLEARED -- those words do not appear anywhere below.
const MATCH_STATUS_LABELS: Record<string, string> = {
  EXACT_MATCH: "Exact match",
  MULTIPLE_EXACT_MATCHES: "Multiple exact matches — selection required",
  INGREDIENT_AMBIGUOUS: "Ingredient identity ambiguous — review required",
  ROUTE_MISMATCH: "ROUTE MISMATCH",
  DOSAGE_FORM_MISMATCH: "DOSAGE-FORM MISMATCH",
  NO_MATCHING_IID_PRECEDENT: "NO MATCHING IID PRECEDENT",
  POTENCY_UNAVAILABLE: "FDA VALUE UNAVAILABLE (potency)",
  MDE_UNAVAILABLE: "MDE UNAVAILABLE",
  UNIT_MISMATCH: "UNIT MISMATCH",
  NOT_COMPARABLE: "Not comparable",
  REVIEW_REQUIRED: "Review required",
};

const DECISION_STATUS_LABELS: Record<string, string> = {
  PASS_WITH_IID_PRECEDENT: "Within IID precedent",
  REVIEW_REQUIRED: "Review required",
  EXCEEDS_IID_PRECEDENT: "Exceeds IID precedent",
  NO_MATCH: "No matching precedent",
  NOT_COMPARABLE: "Not comparable",
};

const DECISION_COLOURS: Record<string, string> = {
  PASS_WITH_IID_PRECEDENT: "#1a6b46",
  REVIEW_REQUIRED: "#8a5a10",
  EXCEEDS_IID_PRECEDENT: "#8f2c20",
  NO_MATCH: "#66768b",
  NOT_COMPARABLE: "#66768b",
};

function CandidateRow({ candidate, selectable, onSelect }: { candidate: MatchCandidate; selectable: boolean; onSelect: () => void }) {
  return (
    <tr style={{ borderBottom: "1px solid #f4f8fe" }}>
      <td style={{ padding: "8px 10px" }}>{candidate.ingredient_name}</td>
      <td style={{ padding: "8px 10px" }}>
        {candidate.potency_amount ?? "FDA VALUE UNAVAILABLE"} {candidate.potency_unit ?? ""}{" "}
        <ProvenanceLabel kind="FDA_SOURCE" />
      </td>
      <td style={{ padding: "8px 10px" }}>
        {candidate.maximum_daily_exposure ?? "MDE UNAVAILABLE"} {candidate.mde_unit ?? ""}
      </td>
      <td style={{ padding: "8px 10px" }}>
        {selectable && (
          <button onClick={onSelect} style={{ ...smallButtonStyle, padding: "4px 10px" }}>
            Select this precedent
          </button>
        )}
      </td>
    </tr>
  );
}

function CalculationBlock({ label, calc }: { label: string; calc: Record<string, unknown> | undefined }) {
  if (!calc) return null;
  const ok = calc.status === "OK";
  return (
    <div style={{ marginBottom: 8, fontSize: 13 }}>
      <strong>{label}</strong> <ProvenanceLabel kind="CALCULATED" />
      {ok ? (
        <span style={{ marginLeft: 8 }}>
          {isPercentUnit(calc.unit) ? <PercentValue value={calc.value} /> : String(calc.value)}{" "}
          {calc.unit ? String(calc.unit) : ""}
        </span>
      ) : (
        <span style={{ marginLeft: 8, color: "#8a5a10" }}>Blocked: {String(calc.status)}</span>
      )}
    </div>
  );
}

/**
 * The unit conversion result has its own shape (`ok`, `converted_value`,
 * `converted_unit`, `reason_code` -- `unit_conversion.ConversionResult` in the
 * backend), not the `status`/`value` shape of the other calculations. Read
 * through CalculationBlock it always showed "Blocked: undefined".
 */
function ConversionBlock({ calc }: { calc: Record<string, unknown> | undefined }) {
  if (!calc) return null;
  return (
    <div style={{ marginBottom: 8, fontSize: 13 }}>
      <strong>Unit conversion</strong> <ProvenanceLabel kind="CALCULATED" />
      {calc.ok === true ? (
        <span style={{ marginLeft: 8 }}>
          {String(calc.original_value)} {String(calc.original_unit ?? "")} ={" "}
          {String(calc.converted_value)} {String(calc.converted_unit ?? "")}
        </span>
      ) : (
        <span style={{ marginLeft: 8, color: "#8a5a10" }}>
          Blocked: {String(calc.reason_code ?? "UNIT_NOT_CONVERTIBLE")}
        </span>
      )}
    </div>
  );
}

const COMPARISON_RESULT_TEXT: Record<string, string> = {
  at_or_below: "at or below the IID value",
  above: "above the IID value",
};

/**
 * The like-for-like comparison (`iid_assessment/comparison.py`): the only
 * path that decides whether the proposed amount and the IID record's limit
 * can be compared. The label and the reason text are the backend's own, shown
 * as sent, so the wording is defined in one place.
 */
function ComparisonBlock({ calc }: { calc: Record<string, unknown> | undefined }) {
  if (!calc) return null;
  const sourceRow = (calc.iid_source_row ?? {}) as Record<string, unknown>;
  return (
    <div
      data-testid="potency-comparison"
      style={{ marginBottom: 16, fontSize: 13, border: "1px solid #dce7f4", borderRadius: 8, padding: "0.75rem 1rem" }}
    >
      <strong>Like-for-like comparison</strong> <ProvenanceLabel kind="CALCULATED" />
      {calc.comparable === true ? (
        <>
          <p style={{ margin: "6px 0 0" }}>
            Proposed {String(calc.proposed_value)} {String(calc.unit ?? "")} is{" "}
            <strong>{COMPARISON_RESULT_TEXT[String(calc.result)] ?? String(calc.result)}</strong>{" "}
            of {String(calc.iid_value)} {String(calc.unit ?? "")}.
          </p>
          <p style={{ margin: "4px 0 0", color: "#66768b" }}>
            Conversion: {String(calc.conversion || "none needed")}
            {calc.rounded_for_display === true && " (proposed value rounded for display only)"}
          </p>
          {calc.label ? (
            <p style={{ margin: "4px 0 0", color: "#8a5a10", fontWeight: 600 }}>{String(calc.label)}</p>
          ) : null}
        </>
      ) : (
        <p style={{ margin: "6px 0 0", color: "#8a5a10" }}>
          {String(calc.reason ?? calc.reason_code ?? "cannot compare")}
        </p>
      )}
      {sourceRow.source_row_locator ? (
        <p style={{ margin: "4px 0 0", color: "#66768b" }}>
          IID source row: {String(sourceRow.source_row_locator)}
        </p>
      ) : null}
    </div>
  );
}

function IidPreviewInner() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const tenantSlug = searchParams.get("tenant") ?? "";

  const [ingredientId, setIngredientId] = useState("");
  const [routeCode, setRouteCode] = useState("");
  const [dosageFormCode, setDosageFormCode] = useState("");
  const [releaseId, setReleaseId] = useState("");
  const [proposedQty, setProposedQty] = useState("");
  const [proposedUnit, setProposedUnit] = useState("milligram");
  const [totalWeight, setTotalWeight] = useState("");
  const [totalWeightUnit, setTotalWeightUnit] = useState("milligram");
  const [maxUnitsPerDay, setMaxUnitsPerDay] = useState("");
  const [selectedRecordId, setSelectedRecordId] = useState<string | undefined>(undefined);

  const [preview, setPreview] = useState<AssessmentPreview | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function runPreview(e?: React.FormEvent) {
    e?.preventDefault();
    if (!tenantSlug) return;
    setLoading(true);
    setError(null);
    try {
      const result = await iidAssessments.preview(tenantSlug, {
        ingredient_public_id: ingredientId,
        route_code: routeCode,
        dosage_form_code: dosageFormCode,
        active_release_public_id: releaseId,
        proposed_quantity_per_unit: proposedQty,
        proposed_quantity_unit: proposedUnit,
        total_dosage_unit_weight: totalWeight,
        total_dosage_unit_weight_unit: totalWeightUnit,
        maximum_dosage_units_per_day: maxUnitsPerDay || undefined,
        selected_precedent_record_public_id: selectedRecordId,
      });
      setPreview(result);
    } catch (err) {
      if (err instanceof ApiError && (err.status === 403 || err.status === 401)) {
        router.push(`/signin?next=${encodeURIComponent(window.location.pathname + window.location.search)}`);
      } else {
        setError(err instanceof ApiError ? err.message : "Preview failed.");
      }
    } finally {
      setLoading(false);
    }
  }

  if (!tenantSlug) {
    return (
      <main style={{ maxWidth: 800, margin: "2rem auto", padding: "0 1rem" }}>
        <p role="alert" style={{ color: "#c0392b" }}>
          Select a tenant first.
        </p>
        <Link href="/tenants">Go to tenants</Link>
      </main>
    );
  }

  return (
    <main style={{ maxWidth: 900, margin: "2rem auto", padding: "0 1rem" }}>
      <h1 style={{ margin: "0 0 0.25rem" }}>IID Assessment Preview</h1>
      <p style={{ fontSize: 13, color: "#66768b", marginTop: 0, marginBottom: "1rem" }}>
        Comparing your proposed formulation quantity against a selected FDA IID precedent
        record. This preview is not a regulatory decision and does not determine safety or
        approval — see the disclaimer on any &quot;within precedent&quot; result below.
      </p>

      <form onSubmit={runPreview} style={{ border: "1px solid #dce7f4", borderRadius: 8, padding: "1rem", marginBottom: "1.5rem" }}>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8, marginBottom: 8 }}>
          <label style={{ fontSize: 13 }}>
            Ingredient ID <ProvenanceLabel kind="USER_INPUT" />
            <input value={ingredientId} onChange={(e) => setIngredientId(e.target.value)} required style={inputStyle} />
          </label>
          <label style={{ fontSize: 13 }}>
            Active FDA release ID
            <input value={releaseId} onChange={(e) => setReleaseId(e.target.value)} required style={inputStyle} />
          </label>
          <label style={{ fontSize: 13 }}>
            Route code
            <input value={routeCode} onChange={(e) => setRouteCode(e.target.value)} required style={inputStyle} />
          </label>
          <label style={{ fontSize: 13 }}>
            Dosage form code
            <input value={dosageFormCode} onChange={(e) => setDosageFormCode(e.target.value)} required style={inputStyle} />
          </label>
          <label style={{ fontSize: 13 }}>
            Proposed quantity per unit
            <input
              value={proposedQty}
              onChange={(e) => setProposedQty(e.target.value)}
              required
              placeholder="Enter your own value — never pre-filled from IID"
              style={inputStyle}
            />
          </label>
          <label style={{ fontSize: 13 }}>
            Proposed quantity unit
            <input value={proposedUnit} onChange={(e) => setProposedUnit(e.target.value)} required style={inputStyle} />
          </label>
          <label style={{ fontSize: 13 }}>
            Total dosage-unit weight
            <input value={totalWeight} onChange={(e) => setTotalWeight(e.target.value)} required style={inputStyle} />
          </label>
          <label style={{ fontSize: 13 }}>
            Total weight unit
            <input value={totalWeightUnit} onChange={(e) => setTotalWeightUnit(e.target.value)} required style={inputStyle} />
          </label>
          <label style={{ fontSize: 13 }}>
            Maximum dosage units/day
            <input value={maxUnitsPerDay} onChange={(e) => setMaxUnitsPerDay(e.target.value)} style={inputStyle} />
          </label>
        </div>
        <button type="submit" disabled={loading} style={smallButtonStyle}>
          {loading ? "Running preview…" : "Run preview"}
        </button>
      </form>

      {error && (
        <p role="alert" style={{ color: "#c0392b" }}>
          {error}
        </p>
      )}

      {preview && (
        <section aria-label="Assessment result">
          <h2 style={{ fontSize: 16 }}>
            Match status: {MATCH_STATUS_LABELS[preview.match_status] ?? preview.match_status}
          </h2>

          {preview.match_status === "MULTIPLE_EXACT_MATCHES" && (
            <div style={{ marginBottom: 16 }}>
              <p style={{ fontSize: 13, color: "#8a5a10" }}>
                Multiple exact IID precedent records match. You must select one — the system
                never picks the highest or most favourable value automatically.
              </p>
              <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
                <thead>
                  <tr style={{ borderBottom: "1px solid #dce7f4", textAlign: "left" }}>
                    <th style={{ padding: "6px 10px" }}>Ingredient</th>
                    <th style={{ padding: "6px 10px" }}>Potency</th>
                    <th style={{ padding: "6px 10px" }}>MDE</th>
                    <th style={{ padding: "6px 10px" }} />
                  </tr>
                </thead>
                <tbody>
                  {preview.candidates.map((c) => (
                    <CandidateRow
                      key={c.precedent_record_public_id}
                      candidate={c}
                      selectable
                      onSelect={() => {
                        setSelectedRecordId(c.precedent_record_public_id);
                        runPreview();
                      }}
                    />
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {preview.selected_record && (
            <div style={{ marginBottom: 16, fontSize: 13 }}>
              <strong>Selected IID precedent</strong> <ProvenanceLabel kind="FDA_SOURCE" />
              <p style={{ margin: "4px 0 0" }}>
                {preview.selected_record.ingredient_name} — {preview.selected_record.potency_amount ?? "FDA VALUE UNAVAILABLE"}{" "}
                {preview.selected_record.potency_unit ?? ""} potency,{" "}
                {preview.selected_record.maximum_daily_exposure ?? "MDE UNAVAILABLE"}{" "}
                {preview.selected_record.mde_unit ?? ""} MDE
              </p>
            </div>
          )}

          <div style={{ marginBottom: 16 }}>
            <ComparisonBlock calc={preview.calculations.potency_comparison} />
            <h3 style={{ fontSize: 14 }}>Calculations</h3>
            <ConversionBlock calc={preview.calculations.unit_conversion} />
            <CalculationBlock label="Percentage w/w" calc={preview.calculations.percentage_w_w} />
            <CalculationBlock label="Daily exposure" calc={preview.calculations.daily_exposure} />
            <CalculationBlock label="Percentage of IID potency" calc={preview.calculations.percentage_of_iid_potency} />
            <CalculationBlock label="Difference from IID potency" calc={preview.calculations.difference_from_iid_potency} />
            <CalculationBlock label="Percentage of IID MDE" calc={preview.calculations.percentage_of_iid_mde} />
            <CalculationBlock label="Difference from IID MDE" calc={preview.calculations.difference_from_iid_mde} />
          </div>

          <div
            role="status"
            style={{
              border: `1px solid ${DECISION_COLOURS[preview.decision_status] ?? "#66768b"}`,
              borderRadius: 8,
              padding: "1rem",
            }}
          >
            <p style={{ margin: "0 0 4px", fontWeight: 700, color: DECISION_COLOURS[preview.decision_status] ?? "#314155" }}>
              {DECISION_STATUS_LABELS[preview.decision_status] ?? preview.decision_status}
            </p>
            <p style={{ margin: 0, fontSize: 13 }}>{preview.decision_note}</p>
            {preview.escalation_required && (
              <p style={{ margin: "8px 0 0", fontSize: 13, color: "#8a5a10", fontWeight: 600 }}>
                Reviewer escalation required before proceeding.
              </p>
            )}
          </div>
        </section>
      )}
    </main>
  );
}

const inputStyle: React.CSSProperties = {
  display: "block",
  width: "100%",
  marginTop: 4,
  padding: "6px 8px",
  border: "1px solid #dce7f4",
  borderRadius: 4,
  boxSizing: "border-box",
};

const smallButtonStyle: React.CSSProperties = {
  background: "#045e8f",
  color: "#fff",
  border: "none",
  borderRadius: 6,
  padding: "8px 16px",
  cursor: "pointer",
  fontWeight: 600,
  fontSize: 13,
};

export default function IidPreviewPage() {
  return (
    <Suspense>
      <IidPreviewInner />
    </Suspense>
  );
}
