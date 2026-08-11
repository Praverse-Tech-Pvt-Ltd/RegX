/**
 * Milestone 4D-3 — client-visible calculation automation.
 *
 * The behaviour these tests pin down is the Option B contract: a governed PATCH
 * carrying the loaded expected_version, followed by a refetch of the WHOLE
 * response collection so transitively recalculated dependents refresh. The
 * frontend never recalculates and never issues a second "recalculate" request.
 */

import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  ApiError,
  type CalculationOutcomeSummary,
  type ChecklistResponse,
} from "@/lib/api";

const api = vi.hoisted(() => ({
  responsesList: vi.fn(),
  responsesUpdate: vi.fn(),
  versionsGet: vi.fn(),
}));

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...actual,
    iigChecklists: {
      ...actual.iigChecklists,
      versions: { ...actual.iigChecklists.versions, get: api.versionsGet },
      executions: {
        ...actual.iigChecklists.executions,
        responses: { list: api.responsesList, update: api.responsesUpdate },
      },
    },
  };
});

import { ChecklistResponses } from "@/app/iig-checklists/executions/[executionPublicId]/ChecklistResponses";

const TENANT = "alpha";
const EXECUTION = "exec-public-0001";
const VERSION = "version-public-0001";

const MANUAL_ID = "resp-manual-0001";
const CALC_ID = "resp-calculated-0001";
const FDA_ID = "resp-fda-0001";

function response(overrides: Partial<ChecklistResponse> & { publicId: string }): ChecklistResponse {
  return {
    questionPublicId: `q-${overrides.publicId}`,
    dataSourceTypeSnapshot: "user_required",
    rawValue: null,
    isNotApplicable: false,
    notApplicableReason: null,
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

function outcome(
  overrides: Partial<CalculationOutcomeSummary> = {}
): CalculationOutcomeSummary {
  return {
    outcomePublicId: "outcome-public-0001",
    status: "complete",
    value: "12.5000000000",
    unit: "gram",
    reasonCode: null,
    ...overrides,
  };
}

const manual = (version = 1, rawValue: unknown = "50") =>
  response({
    publicId: MANUAL_ID,
    dataSourceTypeSnapshot: "user_required",
    rawValue,
    version,
  });

const calculated = (version = 1, calculation: CalculationOutcomeSummary | null = null) =>
  response({
    publicId: CALC_ID,
    dataSourceTypeSnapshot: "system_calculated",
    // M4D3-MDL-006: calculated responses keep raw_value null at all times.
    rawValue: null,
    version,
    calculation,
  });

const fdaDefault = (version = 1) =>
  response({
    publicId: FDA_ID,
    dataSourceTypeSnapshot: "fda_derived_default",
    rawValue: "fda-value",
    version,
  });

const VERSION_PAYLOAD = {
  sections: [
    {
      public_id: "sec-1",
      code: "S1",
      title: "Section 1",
      description: "",
      display_order: 1,
      criticality: "standard",
      questions: [
        {
          public_id: `q-${MANUAL_ID}`,
          code: "Q_MANUAL",
          question_text: "Manual question",
          display_order: 1,
          answer_type: "short_text",
          data_source_classification: "user_required",
          criticality: "standard",
          required: true,
        },
        {
          public_id: `q-${CALC_ID}`,
          code: "Q_CALC",
          question_text: "Calculated question",
          display_order: 2,
          answer_type: "calculated_value",
          data_source_classification: "system_calculated",
          criticality: "standard",
          required: true,
        },
        {
          public_id: `q-${FDA_ID}`,
          code: "Q_FDA",
          question_text: "FDA default question",
          display_order: 3,
          answer_type: "short_text",
          data_source_classification: "fda_derived_default",
          criticality: "standard",
          required: true,
        },
      ],
    },
  ],
};

function renderResponses(executionStatus = "draft") {
  return render(
    <ChecklistResponses
      tenantSlug={TENANT}
      executionPublicId={EXECUTION}
      checklistVersionPublicId={VERSION}
      executionStatus={executionStatus}
    />
  );
}

beforeEach(() => {
  api.responsesList.mockReset();
  api.responsesUpdate.mockReset();
  api.versionsGet.mockReset();
  api.versionsGet.mockResolvedValue(VERSION_PAYLOAD);
});

describe("ChecklistResponses — governed editing and refresh", () => {
  it("keeps a manual response editable", async () => {
    api.responsesList.mockResolvedValue([manual()]);
    renderResponses();

    const row = await screen.findByTestId(`response-${MANUAL_ID}`);
    expect(row).toHaveAttribute("data-editable", "true");
    expect(within(row).getByRole("button", { name: /save/i })).toBeInTheDocument();
  });

  it("renders SYSTEM_CALCULATED read-only with no editable control or save path", async () => {
    api.responsesList.mockResolvedValue([calculated()]);
    renderResponses();

    const row = await screen.findByTestId(`response-${CALC_ID}`);
    expect(row).toHaveAttribute("data-editable", "false");
    expect(within(row).queryByRole("textbox")).toBeNull();
    expect(within(row).queryByRole("checkbox")).toBeNull();
    expect(within(row).queryByRole("button")).toBeNull();
    expect(screen.getByTestId(`readonly-${CALC_ID}`)).toBeInTheDocument();
  });

  it("offers no UI pathway that PATCHes a SYSTEM_CALCULATED response", async () => {
    api.responsesList.mockResolvedValue([calculated()]);
    renderResponses();
    await screen.findByTestId(`response-${CALC_ID}`);

    // Nothing clickable exists for a calculated response, so no update can be
    // issued from the UI even though the backend would also refuse it.
    expect(screen.queryAllByRole("button")).toHaveLength(0);
    expect(api.responsesUpdate).not.toHaveBeenCalled();
  });

  it("keeps FDA_DERIVED_DEFAULT server-owned and read-only", async () => {
    api.responsesList.mockResolvedValue([fdaDefault()]);
    renderResponses();

    const row = await screen.findByTestId(`response-${FDA_ID}`);
    expect(row).toHaveAttribute("data-editable", "false");
    expect(row).toHaveAttribute("data-classification", "fda_derived_default");
    expect(within(row).queryByRole("button")).toBeNull();
    // Must not be mistaken for a calculated response.
    expect(screen.queryByTestId(`readonly-${CALC_ID}`)).toBeNull();
  });

  it("sends expected_version from the loaded response and refetches afterwards", async () => {
    const user = userEvent.setup();
    api.responsesList
      .mockResolvedValueOnce([manual(4, "50"), calculated(2)])
      .mockResolvedValueOnce([manual(5, "75"), calculated(3)]);
    api.responsesUpdate.mockResolvedValue(manual(5, "75"));

    renderResponses();
    const row = await screen.findByTestId(`response-${MANUAL_ID}`);

    await user.clear(within(row).getByRole("textbox"));
    await user.type(within(row).getByRole("textbox"), "75");
    await user.click(within(row).getByRole("button", { name: /save/i }));

    await waitFor(() => expect(api.responsesUpdate).toHaveBeenCalledTimes(1));
    const payload = api.responsesUpdate.mock.calls[0]?.[3];
    expect(payload).toMatchObject({ expected_version: 4, raw_value: "75" });

    // Option B: the authoritative collection is re-read after the write.
    await waitFor(() => expect(api.responsesList).toHaveBeenCalledTimes(2));
  });

  it("refreshes transitively recalculated dependents from the refetch, not the PATCH body", async () => {
    const user = userEvent.setup();
    api.responsesList
      .mockResolvedValueOnce([manual(4), calculated(2)])
      // The cascade bumped the dependent calculated response server-side.
      .mockResolvedValueOnce([manual(5), calculated(7)]);
    api.responsesUpdate.mockResolvedValue(manual(5));

    renderResponses();
    const row = await screen.findByTestId(`response-${MANUAL_ID}`);
    await user.click(within(row).getByRole("button", { name: /save/i }));

    await waitFor(() =>
      expect(screen.getByTestId(`response-${CALC_ID}`)).toHaveAttribute("data-version", "7")
    );
  });

  it("uses the refreshed version on a second edit, never a cached one", async () => {
    const user = userEvent.setup();
    api.responsesList
      .mockResolvedValueOnce([manual(4)])
      .mockResolvedValueOnce([manual(5)])
      .mockResolvedValueOnce([manual(6)]);
    api.responsesUpdate.mockResolvedValue(manual(5));

    renderResponses();
    const row = await screen.findByTestId(`response-${MANUAL_ID}`);

    await user.click(within(row).getByRole("button", { name: /save/i }));
    await waitFor(() => expect(api.responsesList).toHaveBeenCalledTimes(2));

    await user.click(screen.getByRole("button", { name: /save/i }));
    await waitFor(() => expect(api.responsesUpdate).toHaveBeenCalledTimes(2));

    expect(api.responsesUpdate.mock.calls[0]?.[3]).toMatchObject({ expected_version: 4 });
    // N+1, straight from the refetch — not the stale 4.
    expect(api.responsesUpdate.mock.calls[1]?.[3]).toMatchObject({ expected_version: 5 });
  });

  it("refetches authoritative state and warns when the server reports a stale version", async () => {
    const user = userEvent.setup();
    api.responsesList
      .mockResolvedValueOnce([manual(4, "50")])
      .mockResolvedValueOnce([manual(9, "server-value")]);
    api.responsesUpdate.mockRejectedValue(new ApiError(409, "stale"));

    renderResponses();
    const row = await screen.findByTestId(`response-${MANUAL_ID}`);
    await user.clear(within(row).getByRole("textbox"));
    await user.type(within(row).getByRole("textbox"), "my-edit");
    await user.click(within(row).getByRole("button", { name: /save/i }));

    await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument());
    // Authoritative refetch happened...
    await waitFor(() => expect(api.responsesList).toHaveBeenCalledTimes(2));
    // ...and the rejected client value did not survive it.
    await waitFor(() =>
      expect(screen.getByRole("textbox")).toHaveValue("server-value")
    );
    expect(screen.getByTestId(`response-${MANUAL_ID}`)).toHaveAttribute("data-version", "9");
  });

  it("prevents a double submit while a save is in flight", async () => {
    const user = userEvent.setup();
    api.responsesList.mockResolvedValue([manual(4)]);
    let release: (v: ChecklistResponse) => void = () => {};
    api.responsesUpdate.mockImplementation(
      () =>
        new Promise<ChecklistResponse>((resolve) => {
          release = resolve;
        })
    );

    renderResponses();
    const row = await screen.findByTestId(`response-${MANUAL_ID}`);
    const button = within(row).getByRole("button", { name: /save/i });

    await user.click(button);
    await waitFor(() => expect(button).toBeDisabled());
    // A disabled control swallows the second click, so no second write starts.
    await user.click(button);

    expect(api.responsesUpdate).toHaveBeenCalledTimes(1);
    release(manual(5));
  });

  it("never issues a client-side recalculation request", async () => {
    const user = userEvent.setup();
    api.responsesList.mockResolvedValue([manual(4), calculated(2)]);
    api.responsesUpdate.mockResolvedValue(manual(5));

    renderResponses();
    const row = await screen.findByTestId(`response-${MANUAL_ID}`);
    await user.click(within(row).getByRole("button", { name: /save/i }));
    await waitFor(() => expect(api.responsesUpdate).toHaveBeenCalledTimes(1));

    // One governed write only. Recalculation is the backend's job; the client
    // learns about it by refetching, not by asking for it.
    expect(api.responsesUpdate).toHaveBeenCalledTimes(1);
    const calculatedWrites = api.responsesUpdate.mock.calls.filter(
      (call) => call[2] === CALC_ID
    );
    expect(calculatedWrites).toHaveLength(0);
  });

  it("offers no applicability control for a rule-governed question", async () => {
    api.responsesList.mockResolvedValue([manual(4)]);
    api.versionsGet.mockResolvedValue({
      sections: [
        {
          ...VERSION_PAYLOAD.sections[0],
          questions: [
            {
              ...VERSION_PAYLOAD.sections[0]!.questions[0]!,
              applicability_rule_public_id: "rule-public-0001",
            },
          ],
        },
      ],
    });
    renderResponses();

    const row = await screen.findByTestId(`response-${MANUAL_ID}`);
    // M4D3-APP-009: applicability is server-owned, so no control is offered.
    expect(within(row).queryByRole("checkbox")).toBeNull();
    expect(screen.getByTestId(`applicability-governed-${MANUAL_ID}`)).toBeInTheDocument();
    // The answer itself stays editable — APP-009 owns applicability, not the answer.
    expect(within(row).getByRole("textbox")).toBeInTheDocument();
  });

  it("omits the server-owned applicability fields from a rule-governed save", async () => {
    const user = userEvent.setup();
    api.responsesList.mockResolvedValue([manual(4)]);
    api.versionsGet.mockResolvedValue({
      sections: [
        {
          ...VERSION_PAYLOAD.sections[0],
          questions: [
            {
              ...VERSION_PAYLOAD.sections[0]!.questions[0]!,
              applicability_rule_public_id: "rule-public-0001",
            },
          ],
        },
      ],
    });
    api.responsesUpdate.mockResolvedValue(manual(5));

    renderResponses();
    const row = await screen.findByTestId(`response-${MANUAL_ID}`);
    await user.click(within(row).getByRole("button", { name: /save/i }));

    await waitFor(() => expect(api.responsesUpdate).toHaveBeenCalledTimes(1));
    const payload = api.responsesUpdate.mock.calls[0]?.[3] as Record<string, unknown>;
    // Their mere presence is refused by the server, so they must be absent.
    expect(payload).not.toHaveProperty("is_not_applicable");
    expect(payload).not.toHaveProperty("not_applicable_reason");
    expect(payload).toHaveProperty("expected_version", 4);
  });

  it("still sends applicability fields when no rule governs the question", async () => {
    const user = userEvent.setup();
    api.responsesList.mockResolvedValue([manual(4)]);
    api.responsesUpdate.mockResolvedValue(manual(5));

    renderResponses();
    const row = await screen.findByTestId(`response-${MANUAL_ID}`);
    await user.click(within(row).getByRole("button", { name: /save/i }));

    await waitFor(() => expect(api.responsesUpdate).toHaveBeenCalledTimes(1));
    const payload = api.responsesUpdate.mock.calls[0]?.[3] as Record<string, unknown>;
    expect(payload).toHaveProperty("is_not_applicable");
    expect(payload).toHaveProperty("not_applicable_reason");
  });

  it("does not offer editing once the execution leaves an editable status", async () => {
    api.responsesList.mockResolvedValue([manual(4)]);
    renderResponses("submitted_for_review");

    const row = await screen.findByTestId(`response-${MANUAL_ID}`);
    expect(row).toHaveAttribute("data-editable", "false");
    expect(within(row).queryByRole("button")).toBeNull();
  });
});

describe("ChecklistResponses — governed calculated-result display", () => {
  it("shows the current value for a complete outcome", async () => {
    api.responsesList.mockResolvedValue([calculated(2, outcome())]);
    renderResponses();

    const value = await screen.findByTestId("calculation-value");
    expect(value).toHaveAttribute("data-status", "complete");
    expect(value).toHaveTextContent("12.5000000000");
  });

  it("shows the unit alongside a complete value", async () => {
    api.responsesList.mockResolvedValue([calculated(2, outcome({ unit: "gram" }))]);
    renderResponses();

    expect(await screen.findByTestId("calculation-unit")).toHaveTextContent("gram");
  });

  it("omits the unit when the outcome has none", async () => {
    api.responsesList.mockResolvedValue([calculated(2, outcome({ unit: null }))]);
    renderResponses();

    await screen.findByTestId("calculation-value");
    expect(screen.queryByTestId("calculation-unit")).toBeNull();
  });

  it("renders DATA_REQUIRED as its own state with no value", async () => {
    api.responsesList.mockResolvedValue([
      calculated(
        2,
        outcome({ status: "data_required", value: null, unit: null, reasonCode: "DATA_REQUIRED" })
      ),
    ]);
    renderResponses();

    const state = await screen.findByTestId("calculation-state");
    expect(state).toHaveAttribute("data-status", "data_required");
    expect(state).toHaveTextContent("Data required");
    expect(screen.queryByTestId("calculation-value")).toBeNull();
  });

  it("renders NOT_COMPARABLE from the reason code, not a status", async () => {
    api.responsesList.mockResolvedValue([
      calculated(
        2,
        outcome({ status: "error", value: null, unit: null, reasonCode: "NOT_COMPARABLE" })
      ),
    ]);
    renderResponses();

    const state = await screen.findByTestId("calculation-state");
    expect(state).toHaveAttribute("data-status", "error");
    expect(state).toHaveAttribute("data-reason-code", "NOT_COMPARABLE");
    expect(state).toHaveTextContent("Not comparable");
  });

  it("renders a generic error safely without engine detail", async () => {
    api.responsesList.mockResolvedValue([
      calculated(
        2,
        outcome({
          status: "error",
          value: null,
          unit: null,
          reasonCode: "INPUT_RESOLUTION_FAILED",
        })
      ),
    ]);
    renderResponses();

    const state = await screen.findByTestId("calculation-state");
    expect(state).toHaveTextContent("Calculation unavailable");
    // A governed code may drive the label, but is not rendered as prose.
    expect(state).not.toHaveTextContent("INPUT_RESOLUTION_FAILED");
  });

  it("never treats systemDerivedValue as the calculated result", async () => {
    api.responsesList.mockResolvedValue([
      response({
        publicId: CALC_ID,
        dataSourceTypeSnapshot: "system_calculated",
        rawValue: null,
        // Neither of these is a result carrier; only `calculation` is.
        systemDerivedValue: "999-must-not-render",
        calculation: outcome({ value: "7.0000000000" }),
      }),
    ]);
    renderResponses();

    expect(await screen.findByTestId("calculation-value")).toHaveTextContent("7.0000000000");
    expect(screen.queryByText(/999-must-not-render/)).toBeNull();
  });

  it("replaces a complete value with DATA_REQUIRED after the cascade refetch", async () => {
    const user = userEvent.setup();
    api.responsesList
      .mockResolvedValueOnce([manual(4, "50"), calculated(2, outcome({ value: "42.0000000000" }))])
      // The user cleared the upstream answer; the cascade moved the dependent
      // outcome to data_required and dropped its value.
      .mockResolvedValueOnce([
        manual(5, ""),
        calculated(
          3,
          outcome({ status: "data_required", value: null, unit: null, reasonCode: "DATA_REQUIRED" })
        ),
      ]);
    api.responsesUpdate.mockResolvedValue(manual(5, ""));

    renderResponses();
    expect(await screen.findByTestId("calculation-value")).toHaveTextContent("42.0000000000");

    const row = screen.getByTestId(`response-${MANUAL_ID}`);
    await user.clear(within(row).getByRole("textbox"));
    await user.click(within(row).getByRole("button", { name: /save/i }));

    const state = await screen.findByTestId("calculation-state");
    expect(state).toHaveAttribute("data-status", "data_required");
    // The superseded result is gone from the screen entirely.
    expect(screen.queryByTestId("calculation-value")).toBeNull();
    expect(screen.queryByText(/42\.0000000000/)).toBeNull();
  });

  it("shows the new value after a second upstream change", async () => {
    const user = userEvent.setup();
    api.responsesList
      .mockResolvedValueOnce([manual(4), calculated(2, outcome({ value: "1.0000000000" }))])
      .mockResolvedValueOnce([manual(5), calculated(3, outcome({ value: "2.0000000000" }))])
      .mockResolvedValueOnce([manual(6), calculated(4, outcome({ value: "3.0000000000" }))]);
    api.responsesUpdate.mockResolvedValue(manual(5));

    renderResponses();
    expect(await screen.findByTestId("calculation-value")).toHaveTextContent("1.0000000000");

    await user.click(screen.getByRole("button", { name: /save/i }));
    await waitFor(() =>
      expect(screen.getByTestId("calculation-value")).toHaveTextContent("2.0000000000")
    );

    await user.click(screen.getByRole("button", { name: /save/i }));
    await waitFor(() =>
      expect(screen.getByTestId("calculation-value")).toHaveTextContent("3.0000000000")
    );
    expect(screen.queryByText(/1\.0000000000/)).toBeNull();
  });

  it("renders a calculated response with no outcome without inventing one", async () => {
    api.responsesList.mockResolvedValue([calculated(2, null)]);
    renderResponses();

    expect(await screen.findByTestId("calculation-unavailable")).toBeInTheDocument();
    expect(screen.queryByTestId("calculation-value")).toBeNull();
  });
});
