"use client";

import { Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import {
  fdaData,
  iidAssessments,
  type AssessmentPreview,
  type ControlledTerm,
  type MatchCandidate,
  ApiError,
  isSignedOut,
} from "@/lib/api";
import { ProvenanceLabel } from "@/components/ProvenanceLabel";
import { QuantityMeaningSelect } from "@/components/QuantityMeaningSelect";
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
  const [ingredientName, setIngredientName] = useState("");
  const [routes, setRoutes] = useState<ControlledTerm[]>([]);
  const [dosageForms, setDosageForms] = useState<ControlledTerm[]>([]);
  const [routeCode, setRouteCode] = useState("");
  const [dosageFormCode, setDosageFormCode] = useState("");
  const [releaseId, setReleaseId] = useState("");
  const [proposedQty, setProposedQty] = useState("");
  const [proposedUnit, setProposedUnit] = useState("milligram");
  const [proposedMeaning, setProposedMeaning] = useState("");
  const [totalWeight, setTotalWeight] = useState("");
  const [totalWeightUnit, setTotalWeightUnit] = useState("milligram");
  const [maxUnitsPerDay, setMaxUnitsPerDay] = useState("");
  const [selectedRecordId, setSelectedRecordId] = useState<string | undefined>(undefined);

  const [preview, setPreview] = useState<AssessmentPreview | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // QA-05: a result belongs to the inputs it was run with. Any change to an
  // input clears it (and any error, and a chosen precedent), so the screen can
  // never show a result next to numbers it was not computed from.
  function clearResult() {
    setPreview(null);
    setError(null);
    setSelectedRecordId(undefined);
  }
  const edited =
    <T,>(set: (value: T) => void) =>
    (value: T) => {
      set(value);
      clearResult();
    };

  // What a user can actually know: route and dosage-form NAMES (the controlled
  // vocabularies, offered as suggestions), and which IID release is active.
  // Found on the real stack (2026-11-17): the form accepted only NCI codes and
  // UUIDs that no screen shows, so a user could not run a preview at all.
  useEffect(() => {
    if (!tenantSlug) return;
    let cancelled = false;
    const quietly = <T,>(load: () => Promise<T>, use: (value: T) => void) =>
      Promise.resolve()
        .then(load)
        .then((value) => {
          if (!cancelled) use(value);
        })
        .catch(() => undefined); // suggestions only: the form still works without them
    quietly(() => fdaData.controlledRoutes(tenantSlug), (list) => setRoutes(Array.isArray(list) ? list : []));
    quietly(() => fdaData.controlledDosageForms(tenantSlug), (list) => setDosageForms(Array.isArray(list) ? list : []));
    quietly(
      () => fdaData.releases.list(tenantSlug, { dataset_type: "fda_iid" }),
      (page) => {
        const active = (page?.results ?? []).find((r) => r.status === "active");
        if (active) setReleaseId((current) => current || active.public_id);
      },
    );
    return () => {
      cancelled = true;
    };
  }, [tenantSlug]);

  /** A typed name ("ORAL") or a code ("C38288") -> the code the API expects. */
  function toCode(typed: string, terms: ControlledTerm[]): string {
    const value = typed.trim();
    const hit = terms.find(
      (t) => t.canonical_label.toUpperCase() === value.toUpperCase() || t.code.toUpperCase() === value.toUpperCase(),
    );
    return hit ? hit.code : value;
  }

  async function runPreview(e?: React.FormEvent) {
    e?.preventDefault();
    if (!tenantSlug) return;
    if (!ingredientId.trim() && !ingredientName.trim()) {
      setError("Enter the ingredient name (as listed in the IID) or its ingredient ID.");
      return;
    }
    setLoading(true);
    setError(null);
    setPreview(null); // never show the previous result while (or after) this run fails
    try {
      const result = await iidAssessments.preview(tenantSlug, {
        ...(ingredientId.trim()
          ? { ingredient_public_id: ingredientId.trim() }
          : { substance_name: ingredientName.trim().toUpperCase() }),
        route_code: toCode(routeCode, routes),
        dosage_form_code: toCode(dosageFormCode, dosageForms),
        active_release_public_id: releaseId,
        proposed_quantity_per_unit: proposedQty,
        proposed_quantity_unit: proposedUnit,
        total_dosage_unit_weight: totalWeight,
        total_dosage_unit_weight_unit: totalWeightUnit,
        maximum_dosage_units_per_day: maxUnitsPerDay || undefined,
        selected_precedent_record_public_id: selectedRecordId,
        ...(proposedMeaning ? { proposed_quantity_expression_public_id: proposedMeaning } : {}),
      });
      setPreview(result);
    } catch (err) {
      if (isSignedOut(err)) {
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
            Ingredient name (as listed in the IID) <ProvenanceLabel kind="USER_INPUT" />
            <input
              value={ingredientName}
              onChange={(e) => edited(setIngredientName)(e.target.value)}
              placeholder="e.g. MAGNESIUM STEARATE"
              style={inputStyle}
            />
          </label>
          <label style={{ fontSize: 13 }}>
            Ingredient ID (optional, instead of the name)
            <input value={ingredientId} onChange={(e) => edited(setIngredientId)(e.target.value)} style={inputStyle} />
          </label>
          <label style={{ fontSize: 13 }}>
            Active FDA release ID
            <input value={releaseId} onChange={(e) => edited(setReleaseId)(e.target.value)} required style={inputStyle} />
          </label>
          <label style={{ fontSize: 13 }}>
            Route code (name or code, e.g. ORAL)
            <input
              value={routeCode}
              onChange={(e) => edited(setRouteCode)(e.target.value)}
              required
              list="iid-route-options"
              style={inputStyle}
            />
            <datalist id="iid-route-options">
              {routes.map((t) => (
                <option key={t.code} value={t.canonical_label} />
              ))}
            </datalist>
          </label>
          <label style={{ fontSize: 13 }}>
            Dosage form code (name or code, e.g. TABLET)
            <input
              value={dosageFormCode}
              onChange={(e) => edited(setDosageFormCode)(e.target.value)}
              required
              list="iid-dosage-form-options"
              style={inputStyle}
            />
            <datalist id="iid-dosage-form-options">
              {dosageForms.map((t) => (
                <option key={t.code} value={t.canonical_label} />
              ))}
            </datalist>
          </label>
          <label style={{ fontSize: 13 }}>
            Proposed quantity per unit
            <input
              value={proposedQty}
              onChange={(e) => edited(setProposedQty)(e.target.value)}
              required
              placeholder="Enter your own value — never pre-filled from IID"
              style={inputStyle}
            />
          </label>
          <label style={{ fontSize: 13 }}>
            Proposed quantity unit
            <input value={proposedUnit} onChange={(e) => edited(setProposedUnit)(e.target.value)} required style={inputStyle} />
          </label>
          <QuantityMeaningSelect
            tenantSlug={tenantSlug}
            label="What the proposed quantity means"
            value={proposedMeaning}
            onChange={(id, meaning) => {
              clearResult();
              setProposedMeaning(id);
              if (meaning?.family === "percentage") setProposedUnit("percent");
              else if (meaning?.numerator_unit) setProposedUnit(meaning.numerator_unit);
            }}
          />
          <label style={{ fontSize: 13 }}>
            Total dosage-unit weight
            <input value={totalWeight} onChange={(e) => edited(setTotalWeight)(e.target.value)} required style={inputStyle} />
          </label>
          <label style={{ fontSize: 13 }}>
            Total weight unit
            <input value={totalWeightUnit} onChange={(e) => edited(setTotalWeightUnit)(e.target.value)} required style={inputStyle} />
          </label>
          <label style={{ fontSize: 13 }}>
            Maximum dosage units/day
            <input value={maxUnitsPerDay} onChange={(e) => edited(setMaxUnitsPerDay)(e.target.value)} style={inputStyle} />
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
          <h2 style={{ fontSize: 16 }} data-testid="match-heading">
            {preview.match_reason_heading
              ? preview.match_reason_heading
              : `Match status: ${MATCH_STATUS_LABELS[preview.match_status] ?? preview.match_status}`}
          </h2>

          {preview.release_health && preview.release_health.unlinked_records > 0 && (
            <div
              data-testid="preview-release-health"
              style={{ border: "1px solid #e8c77a", background: "#fff8e6", borderRadius: 8, padding: "0.5rem 0.75rem", marginBottom: 12, fontSize: 13 }}
            >
              <strong>About the active IID release: </strong>
              {preview.release_health.message}
              {preview.release_health.operator_action && (
                <span> What to do: {preview.release_health.operator_action}</span>
              )}
            </div>
          )}

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
