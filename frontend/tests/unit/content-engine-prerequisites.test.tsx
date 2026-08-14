/**
 * Milestone 5A-P1 — the client half of two content-engine prerequisites.
 *
 * `5A-DEC-002`: a select answer stores a machine value, and the reviewer must
 * see the approved label for it. Showing the code puts an internal identifier
 * where regulated wording belongs; deriving a label from the code puts
 * *unapproved* wording there. Both are forbidden, so the label can only come
 * from the server-resolved vocabulary.
 *
 * `5A-DEC-004`: applicability is now actually evaluated, and the decision the
 * server made must be visible. The client never recomputes it — deciding
 * whether a regulated question applied is not the browser's job.
 *
 * No production option label or regulatory question appears here; every string
 * is synthetic.
 */

import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ChecklistResponse } from "@/lib/api";

const api = vi.hoisted(() => ({
  responsesList: vi.fn(),
  responsesUpdate: vi.fn(),
  responsesOverride: vi.fn(),
  responsesReviewerConclusion: vi.fn(),
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
  selectedOptionLabels,
} from "@/app/iig-checklists/executions/[executionPublicId]/ChecklistResponses";

const TENANT = "alpha";
const EXECUTION = "exec-public-0001";
const VERSION = "version-public-0001";
const SELECT_ID = "resp-select-0001";

function response(
  overrides: Partial<ChecklistResponse> & { publicId: string }
): ChecklistResponse {
  return {
    questionPublicId: `q-${overrides.publicId}`,
    dataSourceTypeSnapshot: "user_required",
    rawValue: null,
    isNotApplicable: false,
    notApplicableReason: null,
    applicabilityOutcome: "no_rule",
    enteredByEmail: null,
    enteredAt: null,
    confirmedByEmail: null,
    confirmedAt: null,
    overrideReason: "",
    systemDerivedValue: null,
    version: 1,
    calculation: null,
    ...overrides,
  };
}

function versionWith(answerType: string, options: unknown) {
  return {
    sections: [
      {
        questions: [
          {
            public_id: `q-${SELECT_ID}`,
            code: "Q-SEL",
            question_text: "Synthetic select question",
            answer_type: answerType,
            data_source_classification: "user_required",
            options,
          },
        ],
      },
    ],
  };
}

function renderResponses(status = "draft") {
  return render(
    <ChecklistResponses
      tenantSlug={TENANT}
      executionPublicId={EXECUTION}
      checklistVersionPublicId={VERSION}
      executionStatus={status}
    />
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  api.capabilities.mockResolvedValue({
    can_override_response: false,
    can_enter_reviewer_conclusion: false,
  });
});

describe("selectedOptionLabels — 5A-DEC-002", () => {
  const question = {
    public_id: "q",
    code: "Q",
    question_text: "",
    display_order: 1,
    answer_type: "single_select",
    data_source_classification: "user_required",
    criticality: "low",
    required: false,
    options: [
      { value: "OPT_A", label: "Synthetic option A" },
      { value: "OPT_B", label: "Synthetic option B" },
    ],
  };

  it("maps a single_select value to its approved label", () => {
    expect(selectedOptionLabels(question, { option: "OPT_A" })).toEqual([
      "Synthetic option A",
    ]);
  });

  it("maps every multi_select value, preserving the stored order", () => {
    expect(selectedOptionLabels(question, { options: ["OPT_B", "OPT_A"] })).toEqual([
      "Synthetic option B",
      "Synthetic option A",
    ]);
  });

  it("falls back to the value when the vocabulary has since changed", () => {
    // Better a visible code than a silently vanished regulated answer.
    expect(selectedOptionLabels(question, { option: "OPT_RETIRED" })).toEqual([
      "OPT_RETIRED",
    ]);
  });

  it("returns nothing for an unanswered response", () => {
    expect(selectedOptionLabels(question, null)).toEqual([]);
  });

  it("never invents a label when the server supplied no vocabulary", () => {
    // Deriving one here is exactly what 5A-DEC-002 forbids.
    const bare = { ...question, options: null };
    expect(selectedOptionLabels(bare, { option: "OPT_A" })).toEqual(["OPT_A"]);
  });
});

describe("select rendering", () => {
  it("shows the approved label, never the machine value", async () => {
    api.responsesList.mockResolvedValue([
      response({ publicId: SELECT_ID, rawValue: { option: "OPT_A" } }),
    ]);
    api.versionsGet.mockResolvedValue(
      versionWith("single_select", [{ value: "OPT_A", label: "Synthetic option A" }])
    );
    renderResponses();

    const rendered = await screen.findByTestId(`select-answer-${SELECT_ID}`);
    expect(rendered).toHaveTextContent("Synthetic option A");
    expect(rendered).not.toHaveTextContent("OPT_A");
  });

  it("joins multiple selected labels", async () => {
    api.responsesList.mockResolvedValue([
      response({ publicId: SELECT_ID, rawValue: { options: ["OPT_A", "OPT_B"] } }),
    ]);
    api.versionsGet.mockResolvedValue(
      versionWith("multi_select", [
        { value: "OPT_A", label: "Synthetic option A" },
        { value: "OPT_B", label: "Synthetic option B" },
      ])
    );
    renderResponses();

    const rendered = await screen.findByTestId(`select-answer-${SELECT_ID}`);
    expect(rendered).toHaveTextContent("Synthetic option A, Synthetic option B");
  });

  it("renders an em dash rather than an empty element when unanswered", async () => {
    api.responsesList.mockResolvedValue([response({ publicId: SELECT_ID })]);
    api.versionsGet.mockResolvedValue(
      versionWith("single_select", [{ value: "OPT_A", label: "Synthetic option A" }])
    );
    renderResponses();

    expect(await screen.findByTestId(`select-answer-${SELECT_ID}`)).toHaveTextContent("—");
  });
});

describe("applicability rendering — 5A-DEC-004", () => {
  function withOutcome(outcome: string) {
    api.responsesList.mockResolvedValue([
      response({ publicId: SELECT_ID, applicabilityOutcome: outcome }),
    ]);
    api.versionsGet.mockResolvedValue(versionWith("short_text", null));
  }

  it("shows a rule-determined not-applicable state", async () => {
    withOutcome("not_applicable");
    renderResponses();
    const badge = await screen.findByTestId(`applicability-${SELECT_ID}`);
    expect(badge).toHaveAttribute("data-outcome", "not_applicable");
    expect(badge).toHaveTextContent("Not applicable — determined by rule");
  });

  it("shows a review-required state", async () => {
    withOutcome("review_required");
    renderResponses();
    const badge = await screen.findByTestId(`applicability-${SELECT_ID}`);
    expect(badge).toHaveAttribute("data-outcome", "review_required");
    expect(badge).toHaveTextContent("Applicability requires review");
  });

  it.each(["applicable", "no_rule"])(
    "shows no badge for an unremarkable outcome (%s)",
    async (outcome) => {
      withOutcome(outcome);
      renderResponses();
      await screen.findByTestId("checklist-responses");
      await waitFor(() =>
        expect(screen.queryByTestId(`applicability-${SELECT_ID}`)).not.toBeInTheDocument()
      );
    }
  );

  it("renders the server's decision verbatim and recomputes nothing", async () => {
    // The response says not_applicable while the flag says otherwise — a state
    // the server would not produce. The client must still report what it was
    // told, because re-deriving applicability in the browser is precisely the
    // behaviour PST-008 forbids.
    api.responsesList.mockResolvedValue([
      response({
        publicId: SELECT_ID,
        applicabilityOutcome: "not_applicable",
        isNotApplicable: false,
      }),
    ]);
    api.versionsGet.mockResolvedValue(versionWith("short_text", null));
    renderResponses();

    expect(await screen.findByTestId(`applicability-${SELECT_ID}`)).toHaveAttribute(
      "data-outcome",
      "not_applicable"
    );
  });
});
