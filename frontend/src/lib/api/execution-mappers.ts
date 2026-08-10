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
  reviewer_conclusion_note: string;
  created_at: string;
  updated_at: string;
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
  reviewerConclusionNote: string;
  createdAt: string;
  updatedAt: string;
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
    reviewerConclusionNote: dto.reviewer_conclusion_note,
    createdAt: dto.created_at,
    updatedAt: dto.updated_at,
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
