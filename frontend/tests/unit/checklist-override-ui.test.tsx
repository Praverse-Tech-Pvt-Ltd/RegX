/**
 * Milestone 4D-4 — governed override UI.
 *
 * `4D4-DEC-011` gates the action on a dedicated permission, `4D4-DEC-010` on
 * classification, `4D4-DEC-003` on lifecycle, and `4D4-DEC-012` supplies the
 * capability flag. All four must hold before the action is offered.
 *
 * The capability flag is presentation only — the backend enforces authority
 * regardless — so these tests pin visibility and payload shape, never security.
 */

import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError, type ChecklistResponse } from "@/lib/api";

const api = vi.hoisted(() => ({
  responsesList: vi.fn(),
  responsesUpdate: vi.fn(),
  responsesOverride: vi.fn(),
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
        },
      },
    },
  };
});

import { ChecklistResponses } from "@/app/(regx)/iig-checklists/executions/[executionPublicId]/ChecklistResponses";

const TENANT = "alpha";
const EXECUTION = "exec-public-0001";
const VERSION = "version-public-0001";
const FDA_ID = "resp-fda-0001";

function response(
  overrides: Partial<ChecklistResponse> & { publicId: string }
): ChecklistResponse {
  return {
    questionPublicId: `q-${overrides.publicId}`,
    dataSourceTypeSnapshot: "user_required",
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

const FDA_RESPONSE = response({
  publicId: FDA_ID,
  dataSourceTypeSnapshot: "fda_derived_default",
  rawValue: { value: "fda-original" },
});

function versionWith(classification: string) {
  return {
    sections: [
      {
        questions: [
          {
            public_id: `q-${FDA_ID}`,
            code: "Q-FDA",
            question_text: "Synthetic FDA default",
            answer_type: "short_text",
            data_source_classification: classification,
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
  api.responsesList.mockResolvedValue([FDA_RESPONSE]);
  api.versionsGet.mockResolvedValue(versionWith("fda_derived_default"));
  api.capabilities.mockResolvedValue({
    can_override_response: true,
    can_enter_reviewer_conclusion: false,
  });
  api.responsesOverride.mockResolvedValue(FDA_RESPONSE);
});

describe("override UI visibility", () => {
  it("shows the override form to a capable user on an eligible response", async () => {
    renderResponses();
    expect(await screen.findByTestId(`override-form-${FDA_ID}`)).toBeInTheDocument();
  });

  it("hides the override form when the capability is false", async () => {
    api.capabilities.mockResolvedValue({
      can_override_response: false,
      can_enter_reviewer_conclusion: false,
    });
    renderResponses();
    await screen.findByTestId("checklist-responses");
    await waitFor(() =>
      expect(screen.queryByTestId(`override-form-${FDA_ID}`)).not.toBeInTheDocument()
    );
  });

  it("fails closed when the capability request errors", async () => {
    api.capabilities.mockRejectedValue(new Error("network"));
    renderResponses();
    await screen.findByTestId("checklist-responses");
    await waitFor(() =>
      expect(screen.queryByTestId(`override-form-${FDA_ID}`)).not.toBeInTheDocument()
    );
  });

  it.each([
    ["user_required"],
    ["system_calculated"],
    ["evidence_derived"],
    ["reviewer_confirmed"],
  ])("never offers override for %s", async (classification) => {
    api.responsesList.mockResolvedValue([
      response({
        publicId: FDA_ID,
        dataSourceTypeSnapshot: classification,
        rawValue: { value: "x" },
      }),
    ]);
    api.versionsGet.mockResolvedValue(versionWith(classification));
    renderResponses();
    await screen.findByTestId("checklist-responses");
    await waitFor(() =>
      expect(screen.queryByTestId(`override-form-${FDA_ID}`)).not.toBeInTheDocument()
    );
  });

  it.each([["submitted_for_review"], ["under_review"], ["approved"]])(
    "never offers override while the execution is %s",
    async (status) => {
      renderResponses(status);
      await screen.findByTestId("checklist-responses");
      await waitFor(() =>
        expect(screen.queryByTestId(`override-form-${FDA_ID}`)).not.toBeInTheDocument()
      );
    }
  );

  it("offers no clear-override control", async () => {
    renderResponses();
    await screen.findByTestId(`override-form-${FDA_ID}`);
    expect(screen.queryByText(/clear override/i)).not.toBeInTheDocument();
  });

  it("shows a recorded override reason when one exists", async () => {
    api.responsesList.mockResolvedValue([
      { ...FDA_RESPONSE, overrideReason: "Governed deviation." },
    ]);
    renderResponses();
    expect(await screen.findByTestId(`override-recorded-${FDA_ID}`)).toHaveTextContent(
      "Governed deviation."
    );
  });
});

describe("override submission", () => {
  it("requires a reason before the button is enabled", async () => {
    renderResponses();
    await screen.findByTestId(`override-form-${FDA_ID}`);
    expect(screen.getByTestId(`override-submit-${FDA_ID}`)).toBeDisabled();

    await userEvent.type(screen.getByLabelText(/Override reason for Q-FDA/i), "Because.");
    expect(screen.getByTestId(`override-submit-${FDA_ID}`)).toBeEnabled();
  });

  it("sends the governed payload and refetches authoritative state", async () => {
    renderResponses();
    await screen.findByTestId(`override-form-${FDA_ID}`);

    await userEvent.type(screen.getByLabelText(/Override value for Q-FDA/i), "corrected");
    await userEvent.type(
      screen.getByLabelText(/Override reason for Q-FDA/i),
      "Default disagrees with the source."
    );
    await userEvent.click(screen.getByTestId(`override-submit-${FDA_ID}`));

    await waitFor(() => expect(api.responsesOverride).toHaveBeenCalledTimes(1));
    expect(api.responsesOverride).toHaveBeenCalledWith(TENANT, EXECUTION, FDA_ID, {
      // Straight from the loaded response — never defaulted or synthesised.
      expected_version: 3,
      raw_value: { value: "corrected" },
      override_reason: "Default disagrees with the source.",
    });
    // Initial load plus the post-override authoritative refetch.
    expect(api.responsesList).toHaveBeenCalledTimes(2);
  });

  it("surfaces a governed 403 without claiming success", async () => {
    api.responsesOverride.mockRejectedValue(new ApiError(403, "override_permission_denied"));
    renderResponses();
    await screen.findByTestId(`override-form-${FDA_ID}`);

    await userEvent.type(screen.getByLabelText(/Override reason for Q-FDA/i), "Because.");
    await userEvent.click(screen.getByTestId(`override-submit-${FDA_ID}`));

    expect(await screen.findByRole("alert")).toHaveTextContent(/do not have permission/i);
  });

  it("refreshes and warns on a stale-version 409", async () => {
    api.responsesOverride.mockRejectedValue(new ApiError(409, "stale_expected_version"));
    renderResponses();
    await screen.findByTestId(`override-form-${FDA_ID}`);

    await userEvent.type(screen.getByLabelText(/Override reason for Q-FDA/i), "Because.");
    await userEvent.click(screen.getByTestId(`override-submit-${FDA_ID}`));

    expect(await screen.findByRole("alert")).toHaveTextContent(/changed since you loaded it/i);
    await waitFor(() => expect(api.responsesList).toHaveBeenCalledTimes(2));
  });
});
