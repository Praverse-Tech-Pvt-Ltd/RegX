/**
 * Milestone 4D-4 — the per-response reviewer-conclusion UI.
 *
 * Two distinct concepts must not be confused: the execution-level
 * `reviewer_conclusion_note` carried by `approve()`, and the governed
 * per-response `REVIEWER_CONCLUSION` answer. This slice implements the second,
 * through its dedicated endpoint; `approve()` must never stand in for it.
 *
 * Gating here is presentation only. `PERM_REVIEW_EXECUTION` is enforced by
 * `enter_reviewer_conclusion()` regardless of what this component renders, so
 * these tests pin visibility and payload shape — never security.
 */

import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError, type ChecklistResponse } from "@/lib/api";

const api = vi.hoisted(() => ({
  responsesList: vi.fn(),
  responsesUpdate: vi.fn(),
  responsesOverride: vi.fn(),
  responsesReviewerConclusion: vi.fn(),
  executionsApprove: vi.fn(),
  versionsGet: vi.fn(),
  capabilities: vi.fn(),
}));

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...actual,
    iigChecklists: {
      ...actual.iigChecklists,
      capabilities: api.capabilities,
      versions: { ...actual.iigChecklists.versions, get: api.versionsGet },
      executions: {
        ...actual.iigChecklists.executions,
        approve: api.executionsApprove,
        responses: {
          list: api.responsesList,
          update: api.responsesUpdate,
          override: api.responsesOverride,
          reviewerConclusion: api.responsesReviewerConclusion,
        },
      },
    },
  };
});

import {
  ChecklistResponses,
  MAX_REVIEWER_CONCLUSION_CHARS,
  isReviewerConclusionAmendment,
  reviewerConclusionError,
} from "@/app/iig-checklists/executions/[executionPublicId]/ChecklistResponses";

const TENANT = "alpha";
const EXECUTION = "exec-public-0001";
const VERSION = "version-public-0001";
const CONCLUSION_ID = "resp-conclusion-0001";
const UNDER_REVIEW = "submitted_for_review";

function response(
  overrides: Partial<ChecklistResponse> & { publicId: string }
): ChecklistResponse {
  return {
    questionPublicId: `q-${overrides.publicId}`,
    dataSourceTypeSnapshot: "reviewer_confirmed",
    rawValue: null,
    isNotApplicable: false,
    notApplicableReason: null,
    // `5A-DEC-004` — always present at runtime; the mapper defaults it.
    applicabilityOutcome: "no_rule",
    enteredByEmail: null,
    enteredAt: null,
    confirmedByEmail: null,
    confirmedAt: null,
    overrideReason: "",
    systemDerivedValue: null,
    version: 3,
    calculation: null,
    ...overrides,
  };
}

const EMPTY_CONCLUSION = response({ publicId: CONCLUSION_ID });

const EXISTING_CONCLUSION = response({
  publicId: CONCLUSION_ID,
  rawValue: { value: "Reviewed against §13; acceptable." },
  enteredByEmail: "reviewer@example.com",
  version: 7,
});

function versionWith(answerType: string) {
  return {
    sections: [
      {
        questions: [
          {
            public_id: `q-${CONCLUSION_ID}`,
            code: "Q-CONC",
            question_text: "Reviewer conclusion",
            answer_type: answerType,
            data_source_classification: "reviewer_confirmed",
          },
        ],
      },
    ],
  };
}

function renderResponses(status = UNDER_REVIEW) {
  return render(
    <ChecklistResponses
      tenantSlug={TENANT}
      executionPublicId={EXECUTION}
      checklistVersionPublicId={VERSION}
      executionStatus={status}
    />
  );
}

/** The single governed call, unwrapped for assertion without optional chaining. */
function lastConclusionCall(): [string, string, string, Record<string, unknown>] {
  const calls = api.responsesReviewerConclusion.mock.calls;
  expect(calls).toHaveLength(1);
  return calls[0] as [string, string, string, Record<string, unknown>];
}

async function typeConclusion(text: string) {
  const user = userEvent.setup();
  const box = await screen.findByLabelText("Reviewer conclusion for Q-CONC");
  if (text) await user.type(box, text);
  await user.click(screen.getByTestId(`reviewer-conclusion-submit-${CONCLUSION_ID}`));
  return user;
}

beforeEach(() => {
  vi.clearAllMocks();
  api.responsesList.mockResolvedValue([EMPTY_CONCLUSION]);
  api.versionsGet.mockResolvedValue(versionWith("reviewer_conclusion"));
  api.capabilities.mockResolvedValue({
    can_override_response: false,
    can_enter_reviewer_conclusion: true,
  });
  api.responsesReviewerConclusion.mockResolvedValue(EXISTING_CONCLUSION);
});

describe("visibility and gating", () => {
  it("offers the Enter action to a capable reviewer under review", async () => {
    renderResponses();
    expect(
      await screen.findByTestId(`reviewer-conclusion-form-${CONCLUSION_ID}`)
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Enter Reviewer Conclusion" })).toBeInTheDocument();
  });

  it("hides the action from an unauthorized Doer", async () => {
    api.capabilities.mockResolvedValue({
      can_override_response: false,
      can_enter_reviewer_conclusion: false,
    });
    renderResponses();
    await screen.findByTestId("checklist-responses");
    await waitFor(() =>
      expect(
        screen.queryByTestId(`reviewer-conclusion-form-${CONCLUSION_ID}`)
      ).not.toBeInTheDocument()
    );
    // The existing conclusion stays readable — only writing is gated.
    expect(
      screen.getByTestId(`reviewer-conclusion-current-${CONCLUSION_ID}`)
    ).toBeInTheDocument();
  });

  it("fails closed when the capability fetch fails", async () => {
    api.capabilities.mockRejectedValue(new ApiError(500, "boom"));
    renderResponses();
    await screen.findByTestId("checklist-responses");
    await waitFor(() =>
      expect(
        screen.queryByTestId(`reviewer-conclusion-form-${CONCLUSION_ID}`)
      ).not.toBeInTheDocument()
    );
  });

  it.each(["draft", "returned", "approved", "rejected", "cancelled"])(
    "hides the action outside review (%s)",
    async (status) => {
      renderResponses(status);
      await screen.findByTestId("checklist-responses");
      await waitFor(() =>
        expect(
          screen.queryByTestId(`reviewer-conclusion-form-${CONCLUSION_ID}`)
        ).not.toBeInTheDocument()
      );
    }
  );

  it("does not offer the action on a non-reviewer_conclusion answer type", async () => {
    api.versionsGet.mockResolvedValue(versionWith("short_text"));
    renderResponses();
    await screen.findByTestId("checklist-responses");
    await waitFor(() =>
      expect(
        screen.queryByTestId(`reviewer-conclusion-form-${CONCLUSION_ID}`)
      ).not.toBeInTheDocument()
    );
  });

  it("never gates on a role name — only the capability flag flips visibility", async () => {
    // Same user, same lifecycle, same answer type; only the flag differs.
    api.capabilities.mockResolvedValue({
      can_override_response: true,
      can_enter_reviewer_conclusion: false,
    });
    const { unmount } = renderResponses();
    await screen.findByTestId("checklist-responses");
    await waitFor(() =>
      expect(
        screen.queryByTestId(`reviewer-conclusion-form-${CONCLUSION_ID}`)
      ).not.toBeInTheDocument()
    );
    unmount();

    api.capabilities.mockResolvedValue({
      can_override_response: false,
      can_enter_reviewer_conclusion: true,
    });
    renderResponses();
    expect(
      await screen.findByTestId(`reviewer-conclusion-form-${CONCLUSION_ID}`)
    ).toBeInTheDocument();
  });
});

describe("display of the current conclusion", () => {
  it("shows the recorded conclusion and who entered it", async () => {
    api.responsesList.mockResolvedValue([EXISTING_CONCLUSION]);
    renderResponses();
    const current = await screen.findByTestId(`reviewer-conclusion-current-${CONCLUSION_ID}`);
    expect(current).toHaveTextContent("Reviewed against §13; acceptable.");
    expect(screen.getByText(/reviewer@example\.com/)).toBeInTheDocument();
  });

  it("says so plainly when none exists", async () => {
    renderResponses();
    const current = await screen.findByTestId(`reviewer-conclusion-current-${CONCLUSION_ID}`);
    expect(current).toHaveTextContent("No reviewer conclusion recorded.");
  });

  it("offers Amend, not Enter, once one exists", async () => {
    api.responsesList.mockResolvedValue([EXISTING_CONCLUSION]);
    renderResponses();
    expect(
      await screen.findByRole("button", { name: "Amend Reviewer Conclusion" })
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Enter Reviewer Conclusion" })
    ).not.toBeInTheDocument();
  });

  it("offers no clear or delete action — §AC.4 defers it", async () => {
    api.responsesList.mockResolvedValue([EXISTING_CONCLUSION]);
    renderResponses();
    await screen.findByTestId(`reviewer-conclusion-form-${CONCLUSION_ID}`);
    expect(screen.queryByRole("button", { name: /clear|delete|remove/i })).not.toBeInTheDocument();
  });
});

describe("Enter workflow", () => {
  it("sends exactly raw_value and an integer expected_version from the loaded response", async () => {
    renderResponses();
    await typeConclusion("Acceptable.");

    await waitFor(() => expect(api.responsesReviewerConclusion).toHaveBeenCalledTimes(1));
    const [tenant, execution, responseId, payload] = lastConclusionCall();
    expect(tenant).toBe(TENANT);
    expect(execution).toBe(EXECUTION);
    expect(responseId).toBe(CONCLUSION_ID);
    expect(Object.keys(payload).sort()).toEqual(["expected_version", "raw_value"]);
    expect(payload.raw_value).toEqual({ value: "Acceptable." });
    expect(payload.expected_version).toBe(EMPTY_CONCLUSION.version);
    expect(Number.isInteger(payload.expected_version)).toBe(true);
    expect(typeof payload.expected_version).toBe("number");
  });

  it("sends no server-controlled provenance field", async () => {
    renderResponses();
    await typeConclusion("Acceptable.");

    await waitFor(() => expect(api.responsesReviewerConclusion).toHaveBeenCalled());
    const payload = lastConclusionCall()[3];
    for (const serverOwned of [
      "entered_by",
      "entered_at",
      "confirmed_by",
      "confirmed_at",
      "reviewer",
      "version",
      "history",
      "data_source_type_snapshot",
    ]) {
      expect(payload).not.toHaveProperty(serverOwned);
    }
  });

  it("does not use execution approve() as a substitute", async () => {
    renderResponses();
    await typeConclusion("Acceptable.");

    await waitFor(() => expect(api.responsesReviewerConclusion).toHaveBeenCalled());
    expect(api.executionsApprove).not.toHaveBeenCalled();
    expect(api.responsesUpdate).not.toHaveBeenCalled();
    expect(api.responsesOverride).not.toHaveBeenCalled();
  });

  it("refetches authoritative state after success rather than patching locally", async () => {
    renderResponses();
    await waitFor(() => expect(api.responsesList).toHaveBeenCalledTimes(1));

    api.responsesList.mockResolvedValue([EXISTING_CONCLUSION]);
    await typeConclusion("Acceptable.");

    // The refetch is what teaches the client the server's new version.
    await waitFor(() => expect(api.responsesList).toHaveBeenCalledTimes(2));
    await waitFor(() =>
      expect(screen.getByTestId(`reviewer-conclusion-current-${CONCLUSION_ID}`)).toHaveTextContent(
        "Reviewed against §13; acceptable."
      )
    );
    expect(await screen.findByRole("status")).toHaveTextContent("Reviewer conclusion recorded.");
  });
});

describe("Amend workflow", () => {
  beforeEach(() => {
    api.responsesList.mockResolvedValue([EXISTING_CONCLUSION]);
  });

  it("sends correction_reason with the amendment and the current version", async () => {
    const user = userEvent.setup();
    renderResponses();
    await user.type(
      await screen.findByLabelText("Reviewer conclusion for Q-CONC"),
      "Revised conclusion."
    );
    await user.type(
      screen.getByLabelText("Correction reason for Q-CONC"),
      "Cited the wrong section."
    );
    await user.click(screen.getByTestId(`reviewer-conclusion-submit-${CONCLUSION_ID}`));

    await waitFor(() => expect(api.responsesReviewerConclusion).toHaveBeenCalledTimes(1));
    const payload = lastConclusionCall()[3];
    expect(Object.keys(payload).sort()).toEqual([
      "correction_reason",
      "expected_version",
      "raw_value",
    ]);
    expect(payload.correction_reason).toBe("Cited the wrong section.");
    expect(payload.expected_version).toBe(EXISTING_CONCLUSION.version);
  });

  it("refuses an amendment without a correction reason, without calling the server", async () => {
    renderResponses();
    await typeConclusion("Revised conclusion.");

    expect(api.responsesReviewerConclusion).not.toHaveBeenCalled();
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "A correction reason is required when amending a reviewer conclusion."
    );
  });
});

describe("§13 text rules — meaningful non-empty, no invented numeric minimum", () => {
  it("refuses an empty conclusion without calling the server", async () => {
    renderResponses();
    await typeConclusion("");

    expect(api.responsesReviewerConclusion).not.toHaveBeenCalled();
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "A reviewer conclusion is required."
    );
  });

  it("refuses a whitespace-only conclusion without calling the server", async () => {
    renderResponses();
    await typeConclusion("    ");

    expect(api.responsesReviewerConclusion).not.toHaveBeenCalled();
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "A reviewer conclusion is required."
    );
  });

  it("accepts a meaningful one-character conclusion — §13 sets no numeric minimum", async () => {
    renderResponses();
    await typeConclusion("Y");

    await waitFor(() => expect(api.responsesReviewerConclusion).toHaveBeenCalledTimes(1));
    expect(lastConclusionCall()[3].raw_value).toEqual({ value: "Y" });
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("enforces the existing maximum and nothing else", () => {
    // No numeric minimum is invented: one meaningful character is valid.
    expect(reviewerConclusionError("Y")).toBeNull();
    expect(reviewerConclusionError("ab")).toBeNull();
    expect(reviewerConclusionError("x".repeat(MAX_REVIEWER_CONCLUSION_CHARS))).toBeNull();
    expect(reviewerConclusionError("x".repeat(MAX_REVIEWER_CONCLUSION_CHARS + 1))).toBe(
      `A reviewer conclusion may not exceed ${MAX_REVIEWER_CONCLUSION_CHARS} characters.`
    );
    expect(reviewerConclusionError("")).toBe("A reviewer conclusion is required.");
    expect(reviewerConclusionError("   \t\n ")).toBe("A reviewer conclusion is required.");
  });

  it("caps the control at the governed maximum with no minLength attribute", async () => {
    renderResponses();
    const box = await screen.findByLabelText("Reviewer conclusion for Q-CONC");
    expect(box).toHaveAttribute("maxLength", String(MAX_REVIEWER_CONCLUSION_CHARS));
    expect(box).not.toHaveAttribute("minLength");
  });

  it("treats a stored conclusion as an amendment, an absent one as first entry", () => {
    expect(isReviewerConclusionAmendment(EXISTING_CONCLUSION)).toBe(true);
    expect(isReviewerConclusionAmendment(EMPTY_CONCLUSION)).toBe(false);
  });
});

describe("governed error handling", () => {
  it("refetches and reports the server's reason on a stale 409", async () => {
    api.responsesReviewerConclusion.mockRejectedValue(
      new ApiError(409, "expected_version does not match current version. Reload and retry.")
    );
    renderResponses();
    await waitFor(() => expect(api.responsesList).toHaveBeenCalledTimes(1));

    api.responsesList.mockResolvedValue([EXISTING_CONCLUSION]);
    await typeConclusion("Acceptable.");

    // Stale means our picture is wrong: reload before saying anything.
    await waitFor(() => expect(api.responsesList).toHaveBeenCalledTimes(2));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "expected_version does not match current version."
    );
  });

  it("reports a governed 400 detail verbatim", async () => {
    api.responsesReviewerConclusion.mockRejectedValue(
      new ApiError(400, "expected_version must be a positive integer.")
    );
    renderResponses();
    await typeConclusion("Acceptable.");

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "expected_version must be a positive integer."
    );
  });

  it("reports a 403 as a permission refusal", async () => {
    api.responsesReviewerConclusion.mockRejectedValue(new ApiError(403, "forbidden"));
    renderResponses();
    await typeConclusion("Acceptable.");

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "You do not have permission to enter a reviewer conclusion."
    );
  });

  it("does not refetch or claim success when the write was refused", async () => {
    api.responsesReviewerConclusion.mockRejectedValue(new ApiError(400, "refused"));
    renderResponses();
    await waitFor(() => expect(api.responsesList).toHaveBeenCalledTimes(1));
    await typeConclusion("Acceptable.");

    await screen.findByRole("alert");
    expect(api.responsesList).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });
});
