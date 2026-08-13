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

/**
 * Mirrors the backend gate in `enter_reviewer_conclusion()`: the service refuses
 * any other status with 409 `reviewer_conclusion_invalid_state`. A conclusion is
 * a review act, so it exists only while the execution is under review — never in
 * `draft`/`returned` (where it has not been submitted yet) and never after
 * `approved` (where the record is closed).
 */
const REVIEWER_CONCLUSION_STATUSES = new Set(["submitted_for_review"]);

/**
 * Matches the backend `MAX_REVIEWER_CONCLUSION_CHARS`, which bounds both the
 * execution-level note and this per-response raw_value.
 */
export const MAX_REVIEWER_CONCLUSION_CHARS = 4_000;

/**
 * Client-side echo of the governed text rules for a reviewer conclusion.
 *
 * §13 states the conclusion is free text, required, with a minimum length
 * enforced — but specifies **no numeric minimum**. None is invented here: the
 * requirement implemented is *meaningful non-empty*, exactly as the backend
 * enforces it (missing / empty / whitespace-only refused via `.strip()`). A
 * single meaningful character is a valid conclusion and must not be refused.
 *
 * The maximum is the pre-existing governed one, unchanged.
 *
 * This never replaces the server's decision — it only avoids a request that is
 * already known to be refused, and reports the same reason the server would.
 */
export function reviewerConclusionError(text: string): string | null {
  if (!text.trim()) return "A reviewer conclusion is required.";
  if (text.length > MAX_REVIEWER_CONCLUSION_CHARS) {
    return `A reviewer conclusion may not exceed ${MAX_REVIEWER_CONCLUSION_CHARS} characters.`;
  }
  return null;
}

/** An existing conclusion is amended, not entered; the backend then requires a reason. */
export function isReviewerConclusionAmendment(response: ChecklistResponse): boolean {
  return response.rawValue !== null && response.rawValue !== undefined;
}

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
   * `4D4-DEC-012`. Defaults to `false` so the action stays hidden until the
   * server has actually said yes — a failed capability fetch must not reveal it.
   * This is presentation only; `4D4-DEC-011` is enforced server-side regardless.
   */
  const [canOverride, setCanOverride] = useState(false);
  const [overridingId, setOverridingId] = useState<string | null>(null);
  const [overrideDrafts, setOverrideDrafts] = useState<
    Record<string, { value: string; reason: string }>
  >({});
  /**
   * `4D4-DEC-012` extension. Same fail-closed default as the override flag: the
   * action stays hidden until the server confirms it, so a failed capability
   * fetch cannot reveal a reviewer action to a Doer. Presentation only —
   * `PERM_REVIEW_EXECUTION` is enforced by the service regardless.
   */
  const [canEnterReviewerConclusion, setCanEnterReviewerConclusion] = useState(false);
  const [conclusionSavingId, setConclusionSavingId] = useState<string | null>(null);
  const [conclusionDrafts, setConclusionDrafts] = useState<
    Record<string, { text: string; correctionReason: string }>
  >({});

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
    iigChecklists
      .capabilities(tenantSlug)
      .then((caps) => {
        if (cancelled) return;
        setCanOverride(caps.can_override_response);
        setCanEnterReviewerConclusion(caps.can_enter_reviewer_conclusion);
      })
      // Fail closed: a capability the server did not confirm stays hidden.
      .catch(() => {
        if (cancelled) return;
        setCanOverride(false);
        setCanEnterReviewerConclusion(false);
      });
    return () => {
      cancelled = true;
    };
  }, [tenantSlug]);

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

  /**
   * `4D4-DEC-010` / `4D4-DEC-011` / `4D4-DEC-003` — all three conditions must
   * hold before the action is even offered. This mirrors the server's rules; it
   * does not replace them.
   */
  function canOfferOverride(response: ChecklistResponse): boolean {
    return (
      canOverride &&
      response.dataSourceTypeSnapshot === "fda_derived_default" &&
      EDITABLE_EXECUTION_STATUSES.has(executionStatus)
    );
  }

  async function submitOverride(response: ChecklistResponse) {
    if (overridingId !== null || savingId !== null) return;
    const draft = overrideDrafts[response.publicId] ?? { value: "", reason: "" };
    if (!draft.reason.trim()) {
      setSaveError("An override reason is required.");
      return;
    }

    setOverridingId(response.publicId);
    setSaveError(null);
    setNotice(null);
    try {
      const question = questions[response.questionPublicId];
      await iigChecklists.executions.responses.override(
        tenantSlug,
        executionPublicId,
        response.publicId,
        {
          expected_version: response.version,
          raw_value: toPayloadValue(question?.answer_type, draft.value),
          override_reason: draft.reason,
        }
      );
      // Authoritative refetch — the server may have cascaded dependent
      // calculations, and none of that is reconstructed client-side.
      await refresh();
      setOverrideDrafts((prev) => ({ ...prev, [response.publicId]: { value: "", reason: "" } }));
      setNotice("Override recorded. Calculated values refreshed.");
    } catch (err: unknown) {
      if (err instanceof ApiError && err.status === 409) {
        await refresh().catch(() => undefined);
        setSaveError(
          "This response changed since you loaded it. The current values have been refreshed — review them and try again."
        );
      } else if (err instanceof ApiError && err.status === 403) {
        setSaveError("You do not have permission to override this response.");
      } else if (err instanceof ApiError) {
        setSaveError(err.message || "Override failed.");
      } else {
        setSaveError("Override failed.");
      }
    } finally {
      setOverridingId(null);
    }
  }

  /**
   * All three governed conditions, mirroring `enter_reviewer_conclusion()`:
   * the capability (`PERM_REVIEW_EXECUTION`, never a hardcoded role name), the
   * answer type, and the lifecycle status. The server enforces each of them
   * independently; this only decides whether to offer the action.
   */
  function canOfferReviewerConclusion(question: ChecklistQuestion | undefined): boolean {
    return (
      canEnterReviewerConclusion &&
      question?.answer_type === REVIEWER_CONCLUSION &&
      REVIEWER_CONCLUSION_STATUSES.has(executionStatus)
    );
  }

  async function submitReviewerConclusion(response: ChecklistResponse) {
    // One governed write in flight at a time, across all three write paths.
    if (conclusionSavingId !== null || savingId !== null || overridingId !== null) return;
    const draft = conclusionDrafts[response.publicId] ?? { text: "", correctionReason: "" };

    const textError = reviewerConclusionError(draft.text);
    if (textError) {
      setSaveError(textError);
      return;
    }
    const amending = isReviewerConclusionAmendment(response);
    if (amending && !draft.correctionReason.trim()) {
      setSaveError("A correction reason is required when amending a reviewer conclusion.");
      return;
    }

    setConclusionSavingId(response.publicId);
    setSaveError(null);
    setNotice(null);
    try {
      // Exactly the fields the endpoint accepts. The text is sent as typed —
      // trimming it here would silently alter a regulated record; the backend
      // strips only to decide emptiness. `correction_reason` is omitted
      // entirely on first entry, where the service does not want it.
      const payload: Parameters<
        typeof iigChecklists.executions.responses.reviewerConclusion
      >[3] = {
        raw_value: { value: draft.text },
        // Straight from the loaded response, already a JSON integer —
        // `4D4-DEC-013` refuses "1", 1.0 and "1.0" rather than coercing them.
        expected_version: response.version,
      };
      if (amending) payload.correction_reason = draft.correctionReason;

      await iigChecklists.executions.responses.reviewerConclusion(
        tenantSlug,
        executionPublicId,
        response.publicId,
        payload
      );
      // The server owns the new version, provenance and history. Read the
      // authoritative collection back rather than patching local state, so the
      // next amendment sends the server's version and not a guessed one.
      await refresh();
      setConclusionDrafts((prev) => ({
        ...prev,
        [response.publicId]: { text: "", correctionReason: "" },
      }));
      setNotice("Reviewer conclusion recorded.");
    } catch (err: unknown) {
      if (err instanceof ApiError && err.status === 409) {
        // Either a stale version or an execution that left review. Both mean
        // our picture is out of date, so reload before saying anything, and
        // report the server's own governed reason rather than guessing which.
        await refresh().catch(() => undefined);
        setSaveError(
          err.message ||
            "This response changed since you loaded it. The current values have been refreshed — review them and try again."
        );
      } else if (err instanceof ApiError && err.status === 403) {
        setSaveError("You do not have permission to enter a reviewer conclusion.");
      } else if (err instanceof ApiError) {
        // Governed 400s (`reviewer_conclusion_empty`, `invalid_expected_version`,
        // `reviewer_conclusion_too_long`, …) surface the server's detail.
        setSaveError(err.message || "Reviewer conclusion failed.");
      } else {
        setSaveError("Reviewer conclusion failed.");
      }
    } finally {
      setConclusionSavingId(null);
    }
  }

  function setConclusionDraft(
    publicId: string,
    patch: Partial<{ text: string; correctionReason: string }>
  ) {
    setConclusionDrafts((prev) => ({
      ...prev,
      [publicId]: {
        text: prev[publicId]?.text ?? "",
        correctionReason: prev[publicId]?.correctionReason ?? "",
        ...patch,
      },
    }));
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

              {/* A reviewer_conclusion answer is governed by its own endpoint,
                  so the answer type decides the branch before classification
                  does: neither the ordinary editor nor the override form can
                  produce a payload this response would accept. */}
              {question?.answer_type === REVIEWER_CONCLUSION ? (
                <div data-testid={`reviewer-conclusion-${response.publicId}`}>
                  {/* The current conclusion is always shown, to every reader —
                      visibility is not gated on the capability to write one. */}
                  <p
                    data-testid={`reviewer-conclusion-current-${response.publicId}`}
                    style={{ margin: "0.25rem 0" }}
                  >
                    {toEditableText(response.rawValue) || "No reviewer conclusion recorded."}
                  </p>
                  {response.enteredByEmail && (
                    <p style={{ margin: "0.25rem 0", color: "#4b5563" }}>
                      Recorded by {response.enteredByEmail}
                    </p>
                  )}
                  {canOfferReviewerConclusion(question) && (
                    <div data-testid={`reviewer-conclusion-form-${response.publicId}`}>
                      <label>
                        {isReviewerConclusionAmendment(response)
                          ? "Amend reviewer conclusion"
                          : "Reviewer conclusion"}
                        <br />
                        <textarea
                          aria-label={`Reviewer conclusion for ${question?.code ?? response.publicId}`}
                          // The governed maximum, mirrored so the control cannot
                          // build a payload the server would refuse. There is no
                          // minLength: §13 specifies no numeric minimum.
                          maxLength={MAX_REVIEWER_CONCLUSION_CHARS}
                          value={conclusionDrafts[response.publicId]?.text ?? ""}
                          disabled={conclusionSavingId === response.publicId}
                          onChange={(e) =>
                            setConclusionDraft(response.publicId, { text: e.target.value })
                          }
                        />
                      </label>
                      {/* Only an amendment needs one — the service requires a
                          correction reason exactly when a conclusion already
                          exists, and rejects the write without it. */}
                      {isReviewerConclusionAmendment(response) && (
                        <label>
                          Correction reason (required)
                          <br />
                          <input
                            type="text"
                            required
                            aria-label={`Correction reason for ${question?.code ?? response.publicId}`}
                            value={conclusionDrafts[response.publicId]?.correctionReason ?? ""}
                            disabled={conclusionSavingId === response.publicId}
                            onChange={(e) =>
                              setConclusionDraft(response.publicId, {
                                correctionReason: e.target.value,
                              })
                            }
                          />
                        </label>
                      )}
                      <br />
                      <button
                        type="button"
                        data-testid={`reviewer-conclusion-submit-${response.publicId}`}
                        disabled={conclusionSavingId === response.publicId}
                        onClick={() => void submitReviewerConclusion(response)}
                      >
                        {conclusionSavingId === response.publicId
                          ? "Saving…"
                          : isReviewerConclusionAmendment(response)
                            ? "Amend Reviewer Conclusion"
                            : "Enter Reviewer Conclusion"}
                      </button>
                    </div>
                  )}
                </div>
              ) : isServerControlled(classification) ? (
                <div data-testid={`readonly-${response.publicId}`}>
                  {classification === "system_calculated" ? (
                    <CalculationResult calculation={response.calculation} />
                  ) : (
                    <>
                      <p style={{ margin: "0.25rem 0", color: "#4b5563" }}>
                        FDA-derived default. Server-owned and not editable here.
                      </p>
                      {response.overrideReason && (
                        <p
                          data-testid={`override-recorded-${response.publicId}`}
                          style={{ margin: "0.25rem 0", color: "#92400e" }}
                        >
                          Overridden. Reason: {response.overrideReason}
                        </p>
                      )}
                      {/* `4D4-DEC-010` gates this to FDA-derived defaults only, so
                          no other classification can reach it. There is
                          deliberately no clear-override control (§AC.4). */}
                      {canOfferOverride(response) && (
                        <div data-testid={`override-form-${response.publicId}`}>
                          <label>
                            Override value
                            <br />
                            <input
                              type="text"
                              aria-label={`Override value for ${question?.code ?? response.publicId}`}
                              value={overrideDrafts[response.publicId]?.value ?? ""}
                              disabled={overridingId === response.publicId}
                              onChange={(e) =>
                                setOverrideDrafts((prev) => ({
                                  ...prev,
                                  [response.publicId]: {
                                    value: e.target.value,
                                    reason: prev[response.publicId]?.reason ?? "",
                                  },
                                }))
                              }
                            />
                          </label>
                          <label>
                            Override reason (required)
                            <br />
                            <input
                              type="text"
                              required
                              aria-label={`Override reason for ${question?.code ?? response.publicId}`}
                              value={overrideDrafts[response.publicId]?.reason ?? ""}
                              disabled={overridingId === response.publicId}
                              onChange={(e) =>
                                setOverrideDrafts((prev) => ({
                                  ...prev,
                                  [response.publicId]: {
                                    value: prev[response.publicId]?.value ?? "",
                                    reason: e.target.value,
                                  },
                                }))
                              }
                            />
                          </label>
                          <button
                            type="button"
                            data-testid={`override-submit-${response.publicId}`}
                            disabled={
                              overridingId === response.publicId ||
                              !(overrideDrafts[response.publicId]?.reason ?? "").trim()
                            }
                            onClick={() => void submitOverride(response)}
                          >
                            {overridingId === response.publicId ? "Overriding…" : "Override"}
                          </button>
                        </div>
                      )}
                    </>
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
