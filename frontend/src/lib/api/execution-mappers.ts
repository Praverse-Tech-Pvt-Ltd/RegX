/**
 * DTO → UI model mappers for ChecklistExecution and ChecklistResponse.
 *
 * Django returns snake_case JSON. The UI model uses camelCase throughout.
 * All mapping is centralised here — no scattered property fallbacks elsewhere.
 */

// ---------------------------------------------------------------------------
// Raw API DTOs (snake_case, exactly as Django serialises them)
// ---------------------------------------------------------------------------

export interface ChecklistVersionSummaryDTO {
  public_id: string;
  version_number: number;
  status: string;
}

export interface ChecklistExecutionDTO {
  public_id: string;
  status: string;
  checklist_version: ChecklistVersionSummaryDTO;
  formulation_version_public_id: string;
  // OQ-8: the governed subject component. `null` only for executions
  // created before the field existed.
  // Optional, not just nullable: a server predating OQ-8 omits the keys
  // entirely, and the mapper normalises both cases to null.
  subject_component_public_id?: string | null;
  subject_component_ingredient_name?: string | null;
  created_by_email: string | null;
  submitted_by_email: string | null;
  submitted_at: string | null;
  returned_by_email: string | null;
  returned_at: string | null;
  return_reason: string;
  approved_by_email: string | null;
  approved_at: string | null;
  rejected_by_email: string | null;
  rejected_at: string | null;
  cancelled_by_email: string | null;
  cancelled_at: string | null;
  /** Why an approved execution was superseded (older responses: absent). */
  supersede_reason?: string;
  /** Reinstating a superseded execution (VP only; older responses: absent). */
  reinstated_by_email?: string | null;
  reinstated_at?: string | null;
  reinstate_reason?: string;
  reviewer_conclusion_note: string;
  created_at: string;
  updated_at: string;
  /** Detail and action responses only: what this user may do now (display only). */
  available_actions?: string[];
}

/**
 * The governed CalculationStatus vocabulary, exactly as stored.
 *
 * NOT_COMPARABLE is deliberately absent: it is a `reason_code`, not a status.
 * A not-comparable engine result persists as `status: "error"` with
 * `reason_code: "NOT_COMPARABLE"`, so callers distinguish it by reason code.
 * `calculating` is reserved for a future async engine and is never written by
 * 4D-3, but it is part of the stored vocabulary so it is represented here.
 */
export type CalculationStatus = "data_required" | "calculating" | "complete" | "error";

const CALCULATION_STATUSES: readonly CalculationStatus[] = [
  "data_required",
  "calculating",
  "complete",
  "error",
];

export interface CalculationOutcomeSummaryDTO {
  outcome_public_id: string;
  status: string;
  value: string | null;
  unit: string | null;
  reason_code: string | null;
}

export interface ChecklistResponseDTO {
  public_id: string;
  question_public_id: string;
  data_source_type_snapshot: string;
  raw_value: unknown | null;
  is_not_applicable: boolean;
  not_applicable_reason: string | null;
  entered_by_email: string | null;
  entered_at: string | null;
  confirmed_by_email: string | null;
  confirmed_at: string | null;
  override_reason: string;
  system_derived_value: unknown | null;
  version: number;
  /** `5A-DEC-004` — server-derived governed applicability decision. */
  applicability_outcome?: string;
  /** Read-only projection of the governed CalculationOutcome; null when none. */
  calculation?: CalculationOutcomeSummaryDTO | null;
}

// ---------------------------------------------------------------------------
// UI models (camelCase, used by pages and components)
// ---------------------------------------------------------------------------

export interface ChecklistVersionSummary {
  publicId: string;
  versionNumber: number;
  status: string;
}

export interface ChecklistExecution {
  publicId: string;
  status: string;
  checklistVersion: ChecklistVersionSummary;
  formulationVersionPublicId: string;
  subjectComponentPublicId: string | null;
  subjectComponentIngredientName: string | null;
  createdByEmail: string | null;
  submittedByEmail: string | null;
  submittedAt: string | null;
  returnedByEmail: string | null;
  returnedAt: string | null;
  returnReason: string;
  approvedByEmail: string | null;
  approvedAt: string | null;
  rejectedByEmail: string | null;
  rejectedAt: string | null;
  cancelledByEmail: string | null;
  cancelledAt: string | null;
  supersedeReason: string;
  reinstatedByEmail: string | null;
  reinstatedAt: string | null;
  reinstateReason: string;
  reviewerConclusionNote: string;
  createdAt: string;
  updatedAt: string;
  /**
   * The actions this user may take now (submit_review, approve, return, reject,
   * cancel, supersede), from the server. Undefined when the response did not
   * carry it (list pages): the screen then falls back to the status alone.
   */
  availableActions?: string[];
}

export interface CalculationOutcomeSummary {
  outcomePublicId: string;
  status: CalculationStatus;
  /**
   * The current value, as the exact decimal string the backend persisted.
   * Kept as a string so no digit is lost to JS float conversion. Null for every
   * non-complete status — the backend only ever stores a value on `complete`,
   * so a previous result can never appear as the current one.
   */
  value: string | null;
  unit: string | null;
  /** Closed governed vocabulary (e.g. DATA_REQUIRED, NOT_COMPARABLE). */
  reasonCode: string | null;
}

export interface ChecklistResponse {
  publicId: string;
  questionPublicId: string;
  dataSourceTypeSnapshot: string;
  rawValue: unknown | null;
  isNotApplicable: boolean;
  notApplicableReason: string | null;
  /**
   * `5A-DEC-004` — the governed applicability decision, derived server-side
   * from persisted state (M4D3-PST-009). Never recomputed by the client: a
   * historical execution must keep reporting what it was assessed against.
   */
  applicabilityOutcome: string;
  enteredByEmail: string | null;
  enteredAt: string | null;
  confirmedByEmail: string | null;
  confirmedAt: string | null;
  overrideReason: string;
  systemDerivedValue: unknown | null;
  version: number;
  /**
   * The authoritative calculated result. Null when the response has no outcome
   * (every manual answer). This — never `rawValue` or `systemDerivedValue` — is
   * where a calculated result comes from.
   */
  calculation: CalculationOutcomeSummary | null;
}

// ---------------------------------------------------------------------------
// Mappers
// ---------------------------------------------------------------------------

export function toChecklistExecution(dto: ChecklistExecutionDTO): ChecklistExecution {
  return {
    publicId: dto.public_id,
    status: dto.status,
    checklistVersion: {
      publicId: dto.checklist_version.public_id,
      versionNumber: dto.checklist_version.version_number,
      status: dto.checklist_version.status,
    },
    formulationVersionPublicId: dto.formulation_version_public_id,
    // `?? null` rather than a bare read: a server that predates the field
    // omits it, and `undefined` would render as "undefined" in the UI.
    subjectComponentPublicId: dto.subject_component_public_id ?? null,
    subjectComponentIngredientName: dto.subject_component_ingredient_name ?? null,
    createdByEmail: dto.created_by_email,
    submittedByEmail: dto.submitted_by_email,
    submittedAt: dto.submitted_at,
    returnedByEmail: dto.returned_by_email,
    returnedAt: dto.returned_at,
    returnReason: dto.return_reason,
    approvedByEmail: dto.approved_by_email,
    approvedAt: dto.approved_at,
    rejectedByEmail: dto.rejected_by_email,
    rejectedAt: dto.rejected_at,
    cancelledByEmail: dto.cancelled_by_email,
    cancelledAt: dto.cancelled_at,
    supersedeReason: dto.supersede_reason ?? "",
    reinstatedByEmail: dto.reinstated_by_email ?? null,
    reinstatedAt: dto.reinstated_at ?? null,
    reinstateReason: dto.reinstate_reason ?? "",
    reviewerConclusionNote: dto.reviewer_conclusion_note,
    createdAt: dto.created_at,
    updatedAt: dto.updated_at,
    availableActions: dto.available_actions,
  };
}

function isCalculationStatus(value: string): value is CalculationStatus {
  return (CALCULATION_STATUSES as readonly string[]).includes(value);
}

export function toCalculationOutcomeSummary(
  dto: CalculationOutcomeSummaryDTO
): CalculationOutcomeSummary | null {
  // An unrecognised status means the backend vocabulary moved ahead of this
  // client. Treating it as "no result" is the safe reading: better to show
  // nothing than to render a regulated value under a status we cannot explain.
  if (!isCalculationStatus(dto.status)) return null;
  return {
    outcomePublicId: dto.outcome_public_id,
    status: dto.status,
    value: dto.value,
    unit: dto.unit,
    reasonCode: dto.reason_code,
  };
}

export function toChecklistResponse(dto: ChecklistResponseDTO): ChecklistResponse {
  return {
    publicId: dto.public_id,
    questionPublicId: dto.question_public_id,
    dataSourceTypeSnapshot: dto.data_source_type_snapshot,
    rawValue: dto.raw_value,
    isNotApplicable: dto.is_not_applicable,
    notApplicableReason: dto.not_applicable_reason,
    // Defaults to `no_rule` only for a payload predating the field; the server
    // always sends it, so this never invents an applicability claim.
    applicabilityOutcome: dto.applicability_outcome ?? "no_rule",
    enteredByEmail: dto.entered_by_email,
    enteredAt: dto.entered_at,
    confirmedByEmail: dto.confirmed_by_email,
    confirmedAt: dto.confirmed_at,
    overrideReason: dto.override_reason,
    systemDerivedValue: dto.system_derived_value,
    version: dto.version,
    calculation: dto.calculation ? toCalculationOutcomeSummary(dto.calculation) : null,
  };
}
