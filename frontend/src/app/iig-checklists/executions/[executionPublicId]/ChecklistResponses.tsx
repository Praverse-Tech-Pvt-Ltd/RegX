"use client";

/**
 * Milestone 4D-3 — the client half of governed response editing.
 *
 * The contract this implements is deliberately thin (Option B):
 *
 *   edit a manual response
 *     -> PATCH with the expected_version of the response currently loaded
 *     -> the backend updates it and cascades to every dependent calculation
 *     -> we refetch the WHOLE authoritative response set
 *
 * Nothing here recalculates anything. There is no second "recalculate" request:
 * the cascade is a backend consequence of the update, and the refetch is how the
 * client learns the new state. Because recalculation is transitive (A -> B -> C)
 * and can be diamond-shaped (A -> B, A -> C, B+C -> D), refreshing only the
 * edited response would leave stale dependents on screen, so the refetch is
 * always the full collection.
 */

import { useCallback, useEffect, useState } from "react";
import {
  ApiError,
  iigChecklists,
  type CalculationOutcomeSummary,
  type ChecklistQuestion,
  type ChecklistResponse,
} from "@/lib/api";
import { ProvenanceLabel, type Provenance } from "@/components/ProvenanceLabel";

/** Mirrors the backend EDITABLE_EXECUTION_STATUSES. */
const EDITABLE_EXECUTION_STATUSES = new Set(["draft", "returned"]);

/**
 * Mirrors the backend SERVER_CONTROLLED_CLASSIFICATIONS. The server answers a
 * PATCH against either of these with 403 `server_controlled_value`; the UI must
 * respect that ownership rather than rely on the server to say no.
 */
const SERVER_CONTROLLED_CLASSIFICATIONS = new Set([
  "system_calculated",
  "fda_derived_default",
]);

/** Reviewer conclusions have their own governed endpoint, not this PATCH. */
const REVIEWER_CONCLUSION = "reviewer_conclusion";

const PROVENANCE_BY_CLASSIFICATION: Record<string, Provenance> = {
  fda_derived_default: "FDA_SOURCE",
  system_calculated: "CALCULATED",
  reviewer_confirmed: "REVIEWER_CONFIRMED",
  user_required: "USER_INPUT",
  evidence_derived: "USER_INPUT",
};

export function isServerControlled(classification: string): boolean {
  return SERVER_CONTROLLED_CLASSIFICATIONS.has(classification);
}

/** A response is client-editable only when the server would actually accept it. */
export function isEditableResponse(
  response: ChecklistResponse,
  question: ChecklistQuestion | undefined,
  executionStatus: string
): boolean {
  if (!EDITABLE_EXECUTION_STATUSES.has(executionStatus)) return false;
  if (isServerControlled(response.dataSourceTypeSnapshot)) return false;
  if (question?.answer_type === REVIEWER_CONCLUSION) return false;
  // Offer a control only where this editor can produce the exact governed
  // payload shape. An answer type it cannot serialize — or a question whose
  // metadata failed to load — is shown read-only rather than given a control
  // whose every save would be refused as invalid_raw_value_shape.
  if (!isEditableAnswerType(question?.answer_type)) return false;
  return true;
}

/**
 * Answer types this editor can serialize to the backend's canonical shape.
 *
 * `response_validation.py` gives every one of the 18 answer types an exact
 * accepted shape, and they are not uniform. These eight are the ones a single
 * value control can produce faithfully. The rest need a shape this editor has
 * no control for and are therefore rendered read-only rather than offered with
 * a control that could only ever produce a rejected payload:
 *
 *   quantity_with_unit                {"value": <decimal string>, "unit": <code>}
 *   single_select                     {"option": <code>}
 *   multi_select                      {"options": [<codes>]}     sorted, unique
 *   fda_record_reference              {"public_id", "record_type"}
 *   formulation_component_reference   {"public_id"}
 *   attachment_reference              {"document_version_public_id"}
 *
 * calculated_value, calculated_status and approval_metadata are never
 * client-writable at all, and reviewer_conclusion has its own endpoint.
 */
export const EDITABLE_ANSWER_TYPES = [
  "short_text",
  "long_narrative",
  "integer",
  "decimal",
  "percentage",
  "date",
  "yes_no",
  "yes_no_na",
] as const;

export type EditableAnswerType = (typeof EDITABLE_ANSWER_TYPES)[number];

export function isEditableAnswerType(answerType: string | undefined): boolean {
  return (EDITABLE_ANSWER_TYPES as readonly string[]).includes(answerType ?? "");
}

/** The closed vocabulary `yes_no_na` accepts — a string set, not a boolean. */
export const YES_NO_NA_OPTIONS = ["yes", "no", "not_applicable"] as const;

/**
 * The canonical `raw_value` envelope. Every type this editor supports carries a
 * single `value` key; the differences are in the inner JSON type.
 */
export interface RawValuePayload {
  value: string | number | boolean;
}

/**
 * Render a stored raw_value back into the edit control.
 *
 * Stored values are always enveloped, so the envelope is unwrapped here —
 * showing the raw JSON would put `{"value":"abc"}` in the text box and round-trip
 * it straight back to the server.
 */
function toEditableText(rawValue: unknown): string {
  if (rawValue === null || rawValue === undefined) return "";
  if (typeof rawValue === "object" && rawValue !== null && "value" in rawValue) {
    const inner = (rawValue as { value: unknown }).value;
    return inner === null || inner === undefined ? "" : String(inner);
  }
  if (typeof rawValue === "string") return rawValue;
  if (typeof rawValue === "number" || typeof rawValue === "boolean") return String(rawValue);
  return JSON.stringify(rawValue);
}

/**
 * Build the governed `raw_value` payload for an edited answer.
 *
 * The backend requires an envelope — `{"value": …}` — for every type this editor
 * supports, with an exact inner type per `response_validation.py`:
 *
 *   short_text / long_narrative   non-empty string
 *   decimal / percentage          decimal *string*, never a JS number, so no
 *                                 precision is lost on a regulated figure
 *   date                          "YYYY-MM-DD"
 *   integer                       JSON integer (a bool is explicitly refused)
 *   yes_no                        JSON **boolean**
 *   yes_no_na                     "yes" | "no" | "not_applicable" — a string
 *                                 vocabulary, deliberately not a boolean
 *
 * An empty edit clears the answer (`null`), which is what the governed service
 * expects for "no answer"; it is not the same as declaring the response N/A.
 *
 * An unparseable integer is forwarded as the typed-in string rather than being
 * coerced or silently dropped, so the backend reports the type error instead of
 * the client inventing a number the user did not enter.
 */
export function toPayloadValue(
  answerType: string | undefined,
  text: string
): RawValuePayload | null {
  if (text === "") return null;
  switch (answerType) {
    case "yes_no":
      // The control offers exactly "true"/"false", so this is total.
      return { value: text === "true" };
    case "yes_no_na":
      return { value: text };
    case "integer": {
      const parsed = Number.parseInt(text, 10);
      return { value: Number.isNaN(parsed) ? text : parsed };
    }
    default:
      // short_text, long_narrative, decimal, percentage and date are all
      // carried as strings on the wire.
      return { value: text };
  }
}

/** The reason code the backend uses for a not-comparable engine result. */
const REASON_NOT_COMPARABLE = "NOT_COMPARABLE";

/**
 * Is this question's applicability governed by a rule (M4D3-APP-008)?
 *
 * When it is, `is_not_applicable` and `not_applicable_reason` are server-owned:
 * the governed update service rejects a client-supplied value for either with
 * 403 `applicability_server_controlled` (M4D3-APP-009). The UI therefore offers
 * no applicability control and omits both fields from the payload — sending
 * them would fail every save, even one that only meant to change the answer.
 *
 * The answer itself stays editable: APP-009 owns applicability, not the answer.
 */
export function isApplicabilityRuleGoverned(question: ChecklistQuestion | undefined): boolean {
  return Boolean(question?.applicability_rule_public_id);
}

/**
 * Read-only rendering of a governed calculation outcome.
 *
 * The outcome is the single source of truth. `rawValue` is always null on a
 * calculated response and `systemDerivedValue` belongs to a different governed
 * concern, so neither is consulted here.
 *
 * A value is shown only for `complete`. Every other state renders its own label
 * and no number — the backend already stores null there, and this component
 * never keeps a previous result around, so a superseded value cannot be
 * presented as current.
 */
export function CalculationResult({ calculation }: { calculation: CalculationOutcomeSummary | null }) {
  if (calculation === null) {
    return (
      <p data-testid="calculation-unavailable" style={{ margin: "0.25rem 0", color: "#4b5563" }}>
        No calculated result available.
      </p>
    );
  }

  const { status, value, unit, reasonCode } = calculation;

  if (status === "complete") {
    return (
      <p data-testid="calculation-value" data-status="complete" style={{ margin: "0.25rem 0" }}>
        <strong>{value ?? "—"}</strong>
        {unit && <span data-testid="calculation-unit"> {unit}</span>}
      </p>
    );
  }

  // Distinguished by reason code, because NOT_COMPARABLE is not a status.
  const label =
    status === "data_required"
      ? "Data required"
      : status === "calculating"
        ? "Calculating"
        : reasonCode === REASON_NOT_COMPARABLE
          ? "Not comparable"
          : "Calculation unavailable";

  return (
    <p
      data-testid="calculation-state"
      data-status={status}
      data-reason-code={reasonCode ?? ""}
      style={{ margin: "0.25rem 0", color: "#4b5563" }}
    >
      {label}
    </p>
  );
}

interface Draft {
  text: string;
  isNotApplicable: boolean;
  notApplicableReason: string;
}

function draftFrom(response: ChecklistResponse): Draft {
  return {
    text: toEditableText(response.rawValue),
    isNotApplicable: response.isNotApplicable,
    notApplicableReason: response.notApplicableReason ?? "",
  };
}

export function ChecklistResponses({
  tenantSlug,
  executionPublicId,
  checklistVersionPublicId,
  executionStatus,
}: {
  tenantSlug: string;
  executionPublicId: string;
  checklistVersionPublicId: string;
  executionStatus: string;
}) {
  const [responses, setResponses] = useState<ChecklistResponse[]>([]);
  const [questions, setQuestions] = useState<Record<string, ChecklistQuestion>>({});
  const [drafts, setDrafts] = useState<Record<string, Draft>>({});
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [savingId, setSavingId] = useState<string | null>(null);

  /**
   * Refetch the authoritative response collection and rebuild every draft from
   * it. Rebuilding is what keeps `expected_version` honest: after a save the
   * next edit must send the *new* server version, never a remembered one.
   */
  const refresh = useCallback(async () => {
    const fresh = await iigChecklists.executions.responses.list(tenantSlug, executionPublicId);
    setResponses(fresh);
    setDrafts(Object.fromEntries(fresh.map((r) => [r.publicId, draftFrom(r)])));
    return fresh;
  }, [tenantSlug, executionPublicId]);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    Promise.all([
      iigChecklists.executions.responses.list(tenantSlug, executionPublicId),
      iigChecklists.versions
        .get(tenantSlug, checklistVersionPublicId)
        .catch(() => null),
    ])
      .then(([fresh, version]) => {
        if (cancelled) return;
        setResponses(fresh);
        setDrafts(Object.fromEntries(fresh.map((r) => [r.publicId, draftFrom(r)])));
        const byId: Record<string, ChecklistQuestion> = {};
        for (const section of version?.sections ?? []) {
          for (const q of section.questions ?? []) byId[q.public_id] = q;
        }
        setQuestions(byId);
      })
      .catch(() => {
        if (!cancelled) setLoadError("Failed to load responses.");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [tenantSlug, executionPublicId, checklistVersionPublicId]);

  async function save(response: ChecklistResponse) {
    // Double-submit guard: one governed write in flight at a time.
    if (savingId !== null) return;
    const draft = drafts[response.publicId];
    if (!draft) return;

    setSavingId(response.publicId);
    setSaveError(null);
    setNotice(null);
    try {
      const question = questions[response.questionPublicId];
      const payload: Parameters<typeof iigChecklists.executions.responses.update>[3] = {
        // Straight from the loaded response — never defaulted or synthesised.
        expected_version: response.version,
        raw_value: toPayloadValue(question?.answer_type, draft.text),
      };
      // M4D3-APP-009: omit the server-owned fields entirely for a rule-governed
      // response. Their mere presence is refused, so including them would break
      // an otherwise valid answer edit.
      if (!isApplicabilityRuleGoverned(question)) {
        payload.is_not_applicable = draft.isNotApplicable;
        payload.not_applicable_reason = draft.notApplicableReason || null;
      }
      await iigChecklists.executions.responses.update(
        tenantSlug,
        executionPublicId,
        response.publicId,
        payload
      );
      // Option B: the PATCH body describes only the edited response, so the
      // dependent calculations the backend just cascaded are read back here.
      await refresh();
      setNotice("Saved. Calculated values refreshed.");
    } catch (err: unknown) {
      if (err instanceof ApiError && err.status === 409) {
        // Stale version. Do not keep the submitted values on screen — reload
        // the governed state and let the user re-apply the edit deliberately.
        await refresh().catch(() => undefined);
        setSaveError(
          "This response changed since you loaded it. The current values have been refreshed — review them and try again."
        );
      } else if (err instanceof ApiError && err.status === 403) {
        setSaveError("This response is owned by the server and cannot be edited.");
      } else if (err instanceof ApiError) {
        setSaveError(err.message || "Save failed.");
      } else {
        setSaveError("Save failed.");
      }
    } finally {
      setSavingId(null);
    }
  }

  function setDraft(publicId: string, patch: Partial<Draft>) {
    setDrafts((prev) => {
      const current = prev[publicId];
      if (!current) return prev;
      return { ...prev, [publicId]: { ...current, ...patch } };
    });
  }

  if (loading) return <p>Loading responses…</p>;
  if (loadError) return <p style={{ color: "red" }}>{loadError}</p>;
  if (responses.length === 0) return <p>No responses.</p>;

  return (
    <div data-testid="checklist-responses">
      <h2>Responses</h2>
      {saveError && (
        <p role="alert" style={{ color: "red" }}>
          {saveError}
        </p>
      )}
      {notice && <p role="status">{notice}</p>}

      <ul style={{ listStyle: "none", padding: 0 }}>
        {responses.map((response) => {
          const question = questions[response.questionPublicId];
          const classification = response.dataSourceTypeSnapshot;
          const editable = isEditableResponse(response, question, executionStatus);
          const draft = drafts[response.publicId];
          const busy = savingId === response.publicId;
          const provenance = PROVENANCE_BY_CLASSIFICATION[classification];

          return (
            <li
              key={response.publicId}
              data-testid={`response-${response.publicId}`}
              data-classification={classification}
              data-editable={editable ? "true" : "false"}
              data-version={response.version}
              style={{ borderTop: "1px solid #e5e7eb", padding: "0.75rem 0" }}
            >
              <div>
                <strong>{question?.question_text ?? question?.code ?? "Response"}</strong>
                {provenance && <ProvenanceLabel kind={provenance} />}
              </div>

              {isServerControlled(classification) ? (
                <div data-testid={`readonly-${response.publicId}`}>
                  {classification === "system_calculated" ? (
                    <CalculationResult calculation={response.calculation} />
                  ) : (
                    <p style={{ margin: "0.25rem 0", color: "#4b5563" }}>
                      FDA-derived default. Server-owned and not editable here.
                    </p>
                  )}
                </div>
              ) : editable && draft ? (
                <div>
                  <label>
                    Answer
                    <br />
                    {question?.answer_type === "yes_no" ? (
                      // The backend requires a JSON boolean here, so the control
                      // offers exactly two values rather than free text.
                      <select
                        aria-label={`Answer for ${question?.code ?? response.publicId}`}
                        value={draft.text}
                        disabled={busy || draft.isNotApplicable}
                        onChange={(e) => setDraft(response.publicId, { text: e.target.value })}
                      >
                        <option value="">—</option>
                        <option value="true">Yes</option>
                        <option value="false">No</option>
                      </select>
                    ) : question?.answer_type === "yes_no_na" ? (
                      // Closed string vocabulary. Note this is the *answer*
                      // "not_applicable", which is a different concept from the
                      // response-level is_not_applicable applicability flag.
                      <select
                        aria-label={`Answer for ${question?.code ?? response.publicId}`}
                        value={draft.text}
                        disabled={busy || draft.isNotApplicable}
                        onChange={(e) => setDraft(response.publicId, { text: e.target.value })}
                      >
                        <option value="">—</option>
                        {YES_NO_NA_OPTIONS.map((option) => (
                          <option key={option} value={option}>
                            {option}
                          </option>
                        ))}
                      </select>
                    ) : (
                      <input
                        type="text"
                        aria-label={`Answer for ${question?.code ?? response.publicId}`}
                        value={draft.text}
                        disabled={busy || draft.isNotApplicable}
                        onChange={(e) => setDraft(response.publicId, { text: e.target.value })}
                      />
                    )}
                  </label>
                  <br />
                  {isApplicabilityRuleGoverned(question) ? (
                    <span
                      data-testid={`applicability-governed-${response.publicId}`}
                      style={{ color: "#4b5563" }}
                    >
                      Applicability is determined by a rule and is not editable here.
                    </span>
                  ) : (
                    <>
                      <label>
                        <input
                          type="checkbox"
                          aria-label={`Not applicable for ${question?.code ?? response.publicId}`}
                          checked={draft.isNotApplicable}
                          disabled={busy}
                          onChange={(e) =>
                            setDraft(response.publicId, { isNotApplicable: e.target.checked })
                          }
                        />{" "}
                        Not applicable
                      </label>
                      {draft.isNotApplicable && (
                        <>
                          <br />
                          <label>
                            Reason
                            <br />
                            <input
                              type="text"
                              aria-label={`Not applicable reason for ${question?.code ?? response.publicId}`}
                              value={draft.notApplicableReason}
                              disabled={busy}
                              onChange={(e) =>
                                setDraft(response.publicId, {
                                  notApplicableReason: e.target.value,
                                })
                              }
                            />
                          </label>
                        </>
                      )}
                    </>
                  )}
                  <br />
                  <button
                    type="button"
                    disabled={savingId !== null}
                    onClick={() => save(response)}
                  >
                    {busy ? "Saving…" : "Save"}
                  </button>
                </div>
              ) : (
                <p style={{ margin: "0.25rem 0", color: "#4b5563" }}>
                  {toEditableText(response.rawValue) || "—"}
                </p>
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}
