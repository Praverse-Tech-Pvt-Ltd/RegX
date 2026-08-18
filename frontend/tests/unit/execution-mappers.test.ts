import { describe, it, expect } from "vitest";
import {
  toChecklistExecution,
  toChecklistResponse,
  type ChecklistExecutionDTO,
  type ChecklistResponseDTO,
} from "@/lib/api/execution-mappers";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeExecutionDTO(overrides: Partial<ChecklistExecutionDTO> = {}): ChecklistExecutionDTO {
  return {
    public_id: "exec-test-1",
    status: "draft",
    checklist_version: {
      public_id: "ver-test-1",
      version_number: 3,
      status: "active",
    },
    formulation_version_public_id: "fv-test-1",
    created_by_email: "doer@example.com",
    submitted_by_email: null,
    submitted_at: null,
    returned_by_email: null,
    returned_at: null,
    return_reason: "",
    approved_by_email: null,
    approved_at: null,
    rejected_by_email: null,
    rejected_at: null,
    cancelled_by_email: null,
    cancelled_at: null,
    reviewer_conclusion_note: "",
    created_at: "2026-01-15T10:00:00Z",
    updated_at: "2026-01-15T10:05:00Z",
    ...overrides,
  };
}

function makeResponseDTO(overrides: Partial<ChecklistResponseDTO> = {}): ChecklistResponseDTO {
  return {
    public_id: "resp-test-1",
    question_public_id: "q-test-1",
    data_source_type_snapshot: "user_required",
    raw_value: null,
    is_not_applicable: false,
    not_applicable_reason: null,
    entered_by_email: null,
    entered_at: null,
    confirmed_by_email: null,
    confirmed_at: null,
    override_reason: "",
    system_derived_value: null,
    version: 1,
    ...overrides,
  };
}

// ---------------------------------------------------------------------------
// toChecklistExecution
// ---------------------------------------------------------------------------

describe("toChecklistExecution", () => {
  it("maps top-level snake_case fields to camelCase", () => {
    const dto = makeExecutionDTO();
    const result = toChecklistExecution(dto);

    expect(result.publicId).toBe("exec-test-1");
    expect(result.status).toBe("draft");
    expect(result.formulationVersionPublicId).toBe("fv-test-1");
    expect(result.createdByEmail).toBe("doer@example.com");
    expect(result.createdAt).toBe("2026-01-15T10:00:00Z");
    expect(result.updatedAt).toBe("2026-01-15T10:05:00Z");
  });

  it("maps nested checklist_version to checklistVersion with camelCase fields", () => {
    const dto = makeExecutionDTO();
    const result = toChecklistExecution(dto);

    expect(result.checklistVersion).toBeDefined();
    expect(result.checklistVersion.publicId).toBe("ver-test-1");
    expect(result.checklistVersion.versionNumber).toBe(3);
    expect(result.checklistVersion.status).toBe("active");
    // No snake_case keys leak through
    const cv = result.checklistVersion as unknown as Record<string, unknown>;
    expect(cv["public_id"]).toBeUndefined();
    expect(cv["version_number"]).toBeUndefined();
  });

  it("maps nullable timestamp and reason fields correctly", () => {
    const dto = makeExecutionDTO({
      submitted_by_email: "sub@example.com",
      submitted_at: "2026-01-16T09:00:00Z",
      returned_by_email: "rev@example.com",
      returned_at: "2026-01-17T11:00:00Z",
      return_reason: "Fix Q3.",
      approved_by_email: "vp@example.com",
      approved_at: "2026-01-18T14:00:00Z",
      reviewer_conclusion_note: "Looks good.",
    });
    const result = toChecklistExecution(dto);

    expect(result.submittedByEmail).toBe("sub@example.com");
    expect(result.submittedAt).toBe("2026-01-16T09:00:00Z");
    expect(result.returnedByEmail).toBe("rev@example.com");
    expect(result.returnedAt).toBe("2026-01-17T11:00:00Z");
    expect(result.returnReason).toBe("Fix Q3.");
    expect(result.approvedByEmail).toBe("vp@example.com");
    expect(result.approvedAt).toBe("2026-01-18T14:00:00Z");
    expect(result.reviewerConclusionNote).toBe("Looks good.");
  });

  it("preserves null for fields that are null in the DTO", () => {
    const dto = makeExecutionDTO();
    const result = toChecklistExecution(dto);

    expect(result.submittedByEmail).toBeNull();
    expect(result.submittedAt).toBeNull();
    expect(result.returnedByEmail).toBeNull();
    expect(result.returnedAt).toBeNull();
    expect(result.approvedByEmail).toBeNull();
    expect(result.approvedAt).toBeNull();
    expect(result.rejectedByEmail).toBeNull();
    expect(result.rejectedAt).toBeNull();
    expect(result.cancelledByEmail).toBeNull();
    expect(result.cancelledAt).toBeNull();
  });

  it("no raw snake_case keys remain on the result", () => {
    const dto = makeExecutionDTO();
    const result = toChecklistExecution(dto) as unknown as Record<string, unknown>;

    const snakeKeys = Object.keys(result).filter((k) => k.includes("_"));
    expect(snakeKeys).toHaveLength(0);
  });

  it("maps rejected and cancelled terminal-state fields", () => {
    const dto = makeExecutionDTO({
      status: "rejected",
      rejected_by_email: "rev@example.com",
      rejected_at: "2026-01-20T12:00:00Z",
    });
    const result = toChecklistExecution(dto);

    expect(result.status).toBe("rejected");
    expect(result.rejectedByEmail).toBe("rev@example.com");
    expect(result.rejectedAt).toBe("2026-01-20T12:00:00Z");
  });
});

// ---------------------------------------------------------------------------
// toChecklistResponse
// ---------------------------------------------------------------------------

describe("toChecklistResponse", () => {
  it("maps snake_case fields to camelCase", () => {
    const dto = makeResponseDTO({
      entered_by_email: "doer@example.com",
      entered_at: "2026-01-15T11:00:00Z",
      version: 2,
    });
    const result = toChecklistResponse(dto);

    expect(result.publicId).toBe("resp-test-1");
    expect(result.questionPublicId).toBe("q-test-1");
    expect(result.dataSourceTypeSnapshot).toBe("user_required");
    expect(result.rawValue).toBeNull();
    expect(result.isNotApplicable).toBe(false);
    expect(result.notApplicableReason).toBeNull();
    expect(result.enteredByEmail).toBe("doer@example.com");
    expect(result.enteredAt).toBe("2026-01-15T11:00:00Z");
    expect(result.version).toBe(2);
  });

  it("preserves raw_value payload as-is", () => {
    const payload = { value: 42 };
    const dto = makeResponseDTO({ raw_value: payload });
    const result = toChecklistResponse(dto);

    expect(result.rawValue).toEqual(payload);
  });

  it("no raw snake_case keys remain on the result", () => {
    const dto = makeResponseDTO();
    const result = toChecklistResponse(dto) as unknown as Record<string, unknown>;

    const snakeKeys = Object.keys(result).filter((k) => k.includes("_"));
    expect(snakeKeys).toHaveLength(0);
  });
});

describe("toChecklistExecution — OQ-8 subject component", () => {
  it("maps the governed subject component and its ingredient name", () => {
    const result = toChecklistExecution(
      makeExecutionDTO({
        subject_component_public_id: "comp-oq8-1",
        subject_component_ingredient_name: "EXCIPIENT-ALPHA",
      })
    );
    expect(result.subjectComponentPublicId).toBe("comp-oq8-1");
    expect(result.subjectComponentIngredientName).toBe("EXCIPIENT-ALPHA");
  });

  it("normalises an explicit null, as a legacy execution reports", () => {
    const result = toChecklistExecution(
      makeExecutionDTO({
        subject_component_public_id: null,
        subject_component_ingredient_name: null,
      })
    );
    expect(result.subjectComponentPublicId).toBeNull();
    expect(result.subjectComponentIngredientName).toBeNull();
  });

  it("normalises absent keys to null rather than undefined", () => {
    // A server predating OQ-8 omits them entirely; undefined would render as
    // the string "undefined" in the table.
    const dto = makeExecutionDTO();
    delete dto.subject_component_public_id;
    delete dto.subject_component_ingredient_name;
    const result = toChecklistExecution(dto);
    expect(result.subjectComponentPublicId).toBeNull();
    expect(result.subjectComponentIngredientName).toBeNull();
  });
});
