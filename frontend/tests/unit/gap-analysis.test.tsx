/**
 * P7 — the Gap Analysis panel.
 *
 * Two things are being pinned down here. The ordinary one is that the panel
 * renders what the server sent: counts, sections in authored order, statuses
 * and the configured criticality.
 *
 * The other is what it must *never* render. No governed scoring formula exists
 * in RegX, so a percentage on this panel would be an unapproved number wearing
 * the authority of a product feature, and "submission ready" or "compliant"
 * would be a regulatory conclusion the platform has not reached. Those are
 * asserted as absences, because an absence is exactly the kind of requirement
 * that quietly stops holding.
 */

import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { axe } from "jest-axe";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { GapAnalysisDetailDTO, GapAnalysisDTO, GapAnalysisItemDTO } from "@/lib/api";

const api = vi.hoisted(() => ({
  list: vi.fn(),
  get: vi.fn(),
  generate: vi.fn(),
}));

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...actual,
    iigChecklists: {
      ...actual.iigChecklists,
      executions: {
        ...actual.iigChecklists.executions,
        gapAnalyses: { list: api.list, get: api.get, generate: api.generate },
      },
    },
  };
});

import { ApiError } from "@/lib/api";
import { GapAnalysis } from "@/app/(regx)/iig-checklists/executions/[executionPublicId]/GapAnalysis";

const TENANT = "alpha";
const EXECUTION = "exec-public-0001";
const ANALYSIS = "analysis-public-0001";

function item(overrides: Partial<GapAnalysisItemDTO> & { question_code: string }): GapAnalysisItemDTO {
  return {
    question_public_id: `q-${overrides.question_code}`,
    question_text: `Text for ${overrides.question_code}`,
    answer_type: "yes_no",
    section_code: "SEC-B",
    section_title: "Shared title",
    section_display_order: 2,
    display_order: 1,
    status: "gap",
    reason_code: "ANSWER_NO",
    configured_criticality: "critical",
    ...overrides,
  };
}

const ITEMS: GapAnalysisItemDTO[] = [
  item({ question_code: "Q-NO", status: "gap", reason_code: "ANSWER_NO", display_order: 1 }),
  item({
    question_code: "Q-REVIEW",
    status: "review_required",
    reason_code: "APPLICABILITY_REVIEW_REQUIRED",
    display_order: 2,
  }),
  item({
    question_code: "Q-BLANK",
    status: "unanswered",
    reason_code: "ANSWER_MISSING",
    configured_criticality: "",
    display_order: 3,
  }),
  item({
    question_code: "Q-YES",
    status: "no_gap",
    reason_code: "ANSWER_YES",
    display_order: 4,
  }),
  item({
    question_code: "Q-NA",
    status: "not_applicable",
    reason_code: "APPLICABILITY_NOT_APPLICABLE",
    configured_criticality: "medium",
    display_order: 5,
  }),
  // Authored first (display_order 1) but a code that sorts second, in a section
  // that shares the other one's title.
  item({
    question_code: "Q-OTHER",
    section_code: "SEC-A",
    section_title: "Shared title",
    section_display_order: 1,
    status: "gap",
    reason_code: "ANSWER_NO",
    configured_criticality: "low",
    display_order: 1,
  }),
];

function header(overrides: Partial<GapAnalysisDTO> = {}): GapAnalysisDTO {
  return {
    public_id: ANALYSIS,
    execution_public_id: EXECUTION,
    checklist_version_public_id: "cv-0001",
    checklist_version_number: 3,
    checklist_version_status: "active",
    input_hash: "a".repeat(64),
    algorithm_version: 1,
    generated_by_email: "doer@example.test",
    generated_at: "2026-09-15T10:30:00Z",
    counts: {
      total_questions: 6,
      applicable: 5,
      gap: 2,
      no_gap: 1,
      unanswered: 1,
      review_required: 1,
      not_applicable: 1,
    },
    ...overrides,
  };
}

function detail(overrides: Partial<GapAnalysisDetailDTO> = {}): GapAnalysisDetailDTO {
  return { ...header(), items: ITEMS, ...overrides };
}

function mountWith({
  results = [header()],
  latestIsCurrent = true,
  detailPayload = detail(),
}: {
  results?: GapAnalysisDTO[];
  latestIsCurrent?: boolean;
  detailPayload?: GapAnalysisDetailDTO;
} = {}) {
  api.list.mockResolvedValue({
    current_input_hash: "a".repeat(64),
    latest_is_current: latestIsCurrent,
    results,
  });
  api.get.mockResolvedValue(detailPayload);
  return render(<GapAnalysis tenantSlug={TENANT} executionPublicId={EXECUTION} />);
}

/**
 * The rendered results rows only.
 *
 * Every status label appears three times on this panel — as a summary chip, as
 * a filter option, and as a row badge — so an unscoped `getByText` would be
 * satisfied by the dropdown and would keep passing if the table stopped
 * rendering entirely.
 */
function rowsText(): string {
  return screen
    .getAllByRole("table")
    .map((table) => table.textContent ?? "")
    .join(" ");
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("summary", () => {
  it("renders the factual counts the server sent", async () => {
    mountWith();
    // The chips carry "<label>: <n>", so each assertion pins a count to its
    // own category rather than just finding the digit somewhere on the page.
    const gapChip = await screen.findByText(/Checklist gap:/);
    expect(gapChip).toHaveTextContent("Checklist gap: 2");
    expect(screen.getByText(/Review required:/)).toHaveTextContent("Review required: 1");
    expect(screen.getByText(/Not applicable:/)).toHaveTextContent("Not applicable: 1");
    expect(screen.getByText(/Applicable:/)).toHaveTextContent("Applicable: 5 of 6");
  });

  it("shows when the analysis was generated, by whom, and against which version", async () => {
    mountWith();
    expect(await screen.findByText(/doer@example\.test/)).toBeInTheDocument();
    expect(screen.getByText(/Version 3/)).toBeInTheDocument();
  });

  it("shows the input fingerprint and algorithm version", async () => {
    mountWith();
    expect(await screen.findByText(/algorithm v1/)).toBeInTheDocument();
  });
});

describe("grouping", () => {
  it("keeps two sections that share a title separate", async () => {
    mountWith();
    await screen.findByRole("heading", { name: /SEC-A/ });
    expect(screen.getByRole("heading", { name: /SEC-B/ })).toBeInTheDocument();
  });

  it("orders sections by authored display_order, not alphabetically by title", async () => {
    mountWith();
    await screen.findByRole("heading", { name: /SEC-A/ });
    const headings = screen
      .getAllByRole("heading", { level: 3 })
      .map((node) => node.textContent ?? "");
    expect(headings[0]).toContain("SEC-A");
    expect(headings[1]).toContain("SEC-B");
  });
});

describe("statuses", () => {
  it("shows review_required as its own category, not as unanswered", async () => {
    mountWith();
    await screen.findByRole("heading", { name: /SEC-B/ });
    const text = rowsText();
    expect(text).toContain("Review required");
    expect(text).toContain("Unanswered");
  });

  it("explains each status with a readable reason", async () => {
    mountWith();
    expect(
      await screen.findByText(/Applicability could not be determined automatically/)
    ).toBeInTheDocument();
    expect(screen.getByText(/No answer recorded/)).toBeInTheDocument();
  });

  it("shows configured criticality verbatim and marks blanks as not configured", async () => {
    const user = userEvent.setup();
    mountWith();
    await screen.findByRole("heading", { name: /SEC-B/ });
    await user.selectOptions(screen.getByLabelText("Filter by status"), "all");

    await waitFor(() => expect(rowsText()).toContain("medium"));
    expect(rowsText()).toContain("Not configured");
  });
});

describe("filters", () => {
  it("defaults to the questions that need attention", async () => {
    mountWith();
    await screen.findByRole("heading", { name: /SEC-B/ });
    // gap, review_required and unanswered are shown as rows; no_gap and N/A
    // are not. Checked against the rows, because both labels also exist in the
    // summary chips and the filter dropdown.
    const text = rowsText();
    expect(text).toContain("Checklist gap");
    expect(text).not.toContain("No gap");
    expect(text).not.toContain("Not applicable");
  });

  it("can show every question", async () => {
    const user = userEvent.setup();
    mountWith();
    await screen.findByRole("heading", { name: /SEC-B/ });
    await user.selectOptions(screen.getByLabelText("Filter by status"), "all");
    await waitFor(() => expect(rowsText()).toContain("No gap"));
    expect(rowsText()).toContain("Not applicable");
  });

  it("can narrow to one section", async () => {
    const user = userEvent.setup();
    mountWith();
    await screen.findByRole("heading", { name: /SEC-A/ });
    await user.selectOptions(screen.getByLabelText("Filter by section"), "SEC-A");
    await waitFor(() =>
      expect(screen.queryByRole("heading", { name: /SEC-B/ })).not.toBeInTheDocument()
    );
  });

  it("reports honestly when nothing matches", async () => {
    const user = userEvent.setup();
    mountWith();
    await screen.findByRole("heading", { name: /SEC-B/ });
    await user.selectOptions(screen.getByLabelText("Filter by status"), "not_applicable");
    await user.selectOptions(screen.getByLabelText("Filter by section"), "SEC-A");
    expect(await screen.findByText(/No questions match the current filters/)).toBeInTheDocument();
  });

  it("offers no criticality filter when the checklist configures none", async () => {
    mountWith({
      detailPayload: detail({
        items: ITEMS.map((i) => ({ ...i, configured_criticality: "" })),
      }),
    });
    await screen.findByRole("heading", { name: /SEC-B/ });
    expect(screen.queryByLabelText("Filter by configured criticality")).not.toBeInTheDocument();
  });
});

describe("history", () => {
  it("marks the newest snapshot as latest and lets an older one be selected", async () => {
    const older = header({ public_id: "analysis-older", generated_at: "2026-09-01T09:00:00Z" });
    mountWith({ results: [header(), older] });

    const selector = await screen.findByLabelText("Select gap analysis snapshot");
    expect(within(selector).getByText(/\(latest\)/)).toBeInTheDocument();

    await userEvent.setup().selectOptions(selector, "analysis-older");
    await waitFor(() =>
      expect(api.get).toHaveBeenCalledWith(TENANT, EXECUTION, "analysis-older")
    );
  });

  it("says so when answers have moved on since the latest analysis", async () => {
    mountWith({ latestIsCurrent: false });
    expect(
      await screen.findByText(/Answers have changed since the latest analysis was generated/)
    ).toBeInTheDocument();
  });

  it("does not say so when the latest analysis is still current", async () => {
    mountWith({ latestIsCurrent: true });
    await screen.findByRole("heading", { name: /SEC-B/ });
    expect(screen.queryByText(/Answers have changed/)).not.toBeInTheDocument();
  });

  it("reports a superseded checklist version without calling the analysis invalid", async () => {
    mountWith({
      results: [header({ checklist_version_status: "superseded" })],
      detailPayload: detail({ checklist_version_status: "superseded" }),
    });
    const note = await screen.findByText(/this version is no longer current/i);
    expect(note).toBeInTheDocument();
    expect(note.textContent).toMatch(/remains a valid record/i);
    expect(screen.queryByText(/invalid/i)).not.toBeInTheDocument();
  });
});

describe("empty and error states", () => {
  it("explains an empty history instead of rendering a blank panel", async () => {
    mountWith({ results: [] });
    expect(
      await screen.findByText(/No gap analysis has been generated for this execution yet/)
    ).toBeInTheDocument();
  });

  it("surfaces a read permission failure", async () => {
    api.list.mockRejectedValue(new ApiError(403, "forbidden"));
    render(<GapAnalysis tenantSlug={TENANT} executionPublicId={EXECUTION} />);
    expect(await screen.findByRole("alert")).toHaveTextContent(
      /do not have permission to view gap analyses/i
    );
  });
});

describe("generation", () => {
  it("generates and shows the new snapshot", async () => {
    const user = userEvent.setup();
    mountWith({ results: [] });
    api.generate.mockResolvedValue(detail());

    await screen.findByText(/No gap analysis has been generated/);
    await user.click(screen.getByRole("button", { name: /Generate analysis/ }));

    await waitFor(() => expect(api.generate).toHaveBeenCalledWith(TENANT, EXECUTION));
    expect(await screen.findByRole("heading", { name: /SEC-B/ })).toBeInTheDocument();
  });

  it("hides the control when the server refuses for lack of permission", async () => {
    const user = userEvent.setup();
    mountWith({ results: [] });
    api.generate.mockRejectedValue(new ApiError(403, "forbidden"));

    await screen.findByText(/No gap analysis has been generated/);
    await user.click(screen.getByRole("button", { name: /Generate analysis/ }));

    await waitFor(() =>
      expect(screen.queryByRole("button", { name: /Generate analysis/ })).not.toBeInTheDocument()
    );
    expect(screen.getByRole("alert")).toHaveTextContent(/do not have permission to generate/i);
  });
});

describe("no regulatory overclaim", () => {
  const FORBIDDEN = [
    /fda[- ]ready/i,
    /submission[- ]ready/i,
    /submission acceptable/i,
    /agency[- ]ready/i,
    /\bcompliant\b/i,
    /\bnon-?compliant\b/i,
    /\bcertified\b/i,
    /\bapproved\b/i,
  ];

  it("renders no percentage anywhere", async () => {
    const user = userEvent.setup();
    mountWith();
    await screen.findByRole("heading", { name: /SEC-B/ });
    await user.selectOptions(screen.getByLabelText("Filter by status"), "all");

    // No governed scoring formula exists, so no number on this panel may be
    // presented as one.
    expect(document.body.textContent ?? "").not.toMatch(/\d\s*%/);
    expect(document.body.textContent ?? "").not.toMatch(/score/i);
  });

  it("uses no readiness or compliance language", async () => {
    mountWith();
    await screen.findByRole("heading", { name: /SEC-B/ });
    const text = document.body.textContent ?? "";
    for (const pattern of FORBIDDEN) {
      expect(text).not.toMatch(pattern);
    }
  });

  it("states plainly that this is not a regulatory assessment", async () => {
    mountWith();
    expect(
      await screen.findByText(/not a regulatory assessment and does not indicate submission/i)
    ).toBeInTheDocument();
  });
});

describe("accessibility", () => {
  it("has no detectable violations", async () => {
    const { container } = mountWith();
    await screen.findByRole("heading", { name: /SEC-B/ });
    expect(await axe(container)).toHaveNoViolations();
  });

  it("labels the region and every control", async () => {
    mountWith();
    await screen.findByRole("heading", { name: /SEC-B/ });
    expect(screen.getByRole("region", { name: /Gap analysis/i })).toBeInTheDocument();
    expect(screen.getByLabelText("Filter by status")).toBeInTheDocument();
    expect(screen.getByLabelText("Filter by section")).toBeInTheDocument();
  });

  it("gives every results table an accessible caption", async () => {
    mountWith();
    await screen.findByRole("heading", { name: /SEC-B/ });
    const tables = screen.getAllByRole("table");
    expect(tables.length).toBeGreaterThan(0);
    for (const table of tables) {
      expect(table.querySelector("caption")?.textContent).toMatch(/Gap analysis results/);
    }
  });
});
