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
  return true;
}

/** Render the stored raw_value for an input box without inventing a value. */
function toEditableText(rawValue: unknown): string {
  if (rawValue === null || rawValue === undefined) return "";
  if (typeof rawValue === "string") return rawValue;
  if (typeof rawValue === "number" || typeof rawValue === "boolean") return String(rawValue);
  return JSON.stringify(rawValue);
}

/**
 * Convert the edited text back to the shape the governed serializer expects.
 * Anything we cannot type confidently is sent through as a string and left for
 * the backend's central answer-type validation to accept or reject — the client
 * never widens what the server considers valid.
 */
export function toPayloadValue(answerType: string | undefined, text: string): unknown {
  if (text === "") return null;
  switch (answerType) {
    case "yes_no":
    case "yes_no_na":
      if (text === "true") return true;
      if (text === "false") return false;
      return text;
    case "integer": {
      const n = Number.parseInt(text, 10);
      return Number.isNaN(n) ? text : n;
    }
    default:
      return text;
  }
}

/** The reason code the backend uses for a not-comparable engine result. */
const REASON_NOT_COMPARABLE = "NOT_COMPARABLE";

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
      await iigChecklists.executions.responses.update(
        tenantSlug,
        executionPublicId,
        response.publicId,
        {
          // Straight from the loaded response — never defaulted or synthesised.
          expected_version: response.version,
          raw_value: toPayloadValue(
            questions[response.questionPublicId]?.answer_type,
            draft.text
          ),
          is_not_applicable: draft.isNotApplicable,
          not_applicable_reason: draft.notApplicableReason || null,
        }
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
                    <input
                      type="text"
                      aria-label={`Answer for ${question?.code ?? response.publicId}`}
                      value={draft.text}
                      disabled={busy || draft.isNotApplicable}
                      onChange={(e) => setDraft(response.publicId, { text: e.target.value })}
                    />
                  </label>
                  <br />
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
                            setDraft(response.publicId, { notApplicableReason: e.target.value })
                          }
                        />
                      </label>
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
