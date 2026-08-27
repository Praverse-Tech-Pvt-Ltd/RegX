import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import {
  INTERNAL_ONLY_NOTE,
  InternalReadinessBadge,
  SeverityBadge,
  SummaryCard,
  EmptyState,
  MaybeLink,
  reasonLabel,
} from "@/app/(regx)/submission-operations/ops-primitives";

// ---------------------------------------------------------------------------
// The distinction the whole screen turns on
// ---------------------------------------------------------------------------
describe("Null is not zero", () => {
  it("a restricted card says Unavailable and never renders a number", () => {
    render(<SummaryCard testId="c" label="Linked documents" value={null} />);
    const card = screen.getByTestId("c");
    expect(card).toHaveAttribute("data-restricted", "true");
    expect(card).toHaveTextContent(/Unavailable/);
    expect(card.textContent).not.toMatch(/\b0\b/);
  });

  it("a permitted card showing none renders 0, which is a different answer", () => {
    render(<SummaryCard testId="c" label="Linked documents" value={0} />);
    const card = screen.getByTestId("c");
    expect(card).toHaveAttribute("data-restricted", "false");
    expect(card).toHaveTextContent("0");
    expect(card).not.toHaveTextContent(/Unavailable/);
  });

  it("a restricted card explains why rather than looking broken", () => {
    render(<SummaryCard testId="c" label="Workflows" value={null} />);
    expect(screen.getByTestId("c")).toHaveTextContent(/do not have permission/i);
  });

  it("empty and restricted are different messages", () => {
    const { unmount } = render(
      <EmptyState
        testId="e"
        restricted={false}
        emptyMessage="No cases yet."
        restrictedMessage="You do not have permission to view cases."
      />
    );
    expect(screen.getByTestId("e")).toHaveTextContent("No cases yet.");
    unmount();

    render(
      <EmptyState
        testId="e"
        restricted
        emptyMessage="No cases yet."
        restrictedMessage="You do not have permission to view cases."
      />
    );
    expect(screen.getByTestId("e")).toHaveTextContent(/do not have permission/i);
  });
});

// ---------------------------------------------------------------------------
// Wording
// ---------------------------------------------------------------------------
describe("Internal-only wording", () => {
  it("every readiness label says Internally, never a bare Ready", () => {
    for (const value of [
      "internally_ready",
      "internally_partially_ready",
      "internally_not_ready",
    ]) {
      const { unmount } = render(<InternalReadinessBadge value={value} />);
      expect(screen.getByTestId("internal-readiness")).toHaveTextContent(/Internally/);
      unmount();
    }
  });

  it("no readiness label claims submission, agency or regulatory status", () => {
    for (const value of [
      "internally_ready",
      "internally_partially_ready",
      "internally_not_ready",
      "no_required_sections",
    ]) {
      const { unmount } = render(<InternalReadinessBadge value={value} />);
      const text = screen.getByTestId("internal-readiness").textContent!.toLowerCase();
      for (const banned of ["submission ready", "agency", "compliant", "approved", "filing"]) {
        expect(text).not.toContain(banned);
      }
      unmount();
    }
  });

  it("a restricted readiness renders Unavailable, not a neutral badge", () => {
    render(<InternalReadinessBadge value={null} />);
    expect(screen.getByTestId("readiness-unavailable")).toHaveTextContent("Unavailable");
  });

  it("the standing disclaimer names what the dashboard is not", () => {
    const note = INTERNAL_ONLY_NOTE.toLowerCase();
    expect(note).toContain("internal regx operational status only");
    for (const claim of ["agency acceptance", "regulatory approval", "submission validity"]) {
      expect(note).toContain(claim);
    }
  });
});

// ---------------------------------------------------------------------------
// Severity is never colour alone
// ---------------------------------------------------------------------------
describe("Severity badges", () => {
  it.each(["blocked", "overdue", "attention", "informational"] as const)(
    "%s carries a text label",
    (severity) => {
      render(<SeverityBadge severity={severity} />);
      const badge = screen.getByTestId("severity-badge");
      expect(badge.textContent?.trim().length ?? 0).toBeGreaterThan(0);
      expect(badge).toHaveAttribute("data-severity", severity);
    }
  );

  it("uses operational words, never regulatory severity vocabulary", () => {
    for (const severity of ["blocked", "overdue", "attention", "informational"] as const) {
      const { unmount } = render(<SeverityBadge severity={severity} />);
      const text = screen.getByTestId("severity-badge").textContent!.toLowerCase();
      for (const banned of ["major", "deficiency", "critical deficiency", "agency"]) {
        expect(text).not.toContain(banned);
      }
      unmount();
    }
  });

  it("maps every reason code the backend can emit to readable copy", () => {
    const codes = [
      "open_blocker",
      "required_section_blocked",
      "overdue_required_section",
      "workflow_rejected",
      "due_soon_required_section",
      "workflow_waiting_review",
      "required_section_not_started",
      "blocked_upgrade_plan",
      "stale_upgrade_plan",
      "dossier_on_hold",
      "case_with_no_dossier",
    ];
    for (const code of codes) {
      expect(reasonLabel(code)).not.toBe(code);
      expect(reasonLabel(code).length).toBeGreaterThan(0);
    }
  });
});

// ---------------------------------------------------------------------------
// Links only where the caller can follow them
// ---------------------------------------------------------------------------
describe("Linking", () => {
  it("renders a link when a destination is visible", () => {
    render(
      <MaybeLink testId="l" href="/submission-dossiers/abc?tenant=t">
        Section A
      </MaybeLink>
    );
    expect(screen.getByTestId("l").tagName).toBe("A");
  });

  it("renders plain text when the destination is hidden", () => {
    render(
      <MaybeLink testId="l" href={null}>
        Section A
      </MaybeLink>
    );
    const el = screen.getByTestId("l");
    expect(el.tagName).not.toBe("A");
    expect(el).toHaveTextContent("Section A");
  });
});

// ---------------------------------------------------------------------------
// The page
// ---------------------------------------------------------------------------
vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams("tenant=t"),
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  useParams: () => ({}),
}));

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    submissionOperations: {
      overview: vi.fn(),
      attention: vi.fn(),
      cases: vi.fn(),
      dossiers: vi.fn(),
      owners: vi.fn(),
      recentActivity: vi.fn(),
    },
  };
});

type OpsMocks = Record<
  keyof typeof import("@/lib/api")["submissionOperations"],
  ReturnType<typeof vi.fn>
>;

const FULL_OVERVIEW = {
  cases: { open: 2, on_hold: 1, completed: 0, cancelled: 0 },
  dossiers: { open: 3, on_hold: 0, completed: 1, cancelled: 0 },
  sections: {
    required_total: 10,
    required_complete: 4,
    required_blocked: 2,
    required_overdue: 3,
    required_due_soon: 1,
    required_not_started: 5,
  },
  blockers: { open: 2 },
  workflows: { waiting_review: 1, rejected: 1, overdue: 0 },
  documents: { linked: 12 },
  checklists: { incomplete: 0 },
  upgrades: { open: 2, blocked: 1, stale: 1 },
  restricted_modules: [],
  due_soon_days: 7,
  generated_at: "2026-08-27T00:00:00Z",
  semantics: "internal_operational",
};

function attentionRow(over: Record<string, unknown> = {}) {
  return {
    reason_code: "required_section_blocked",
    severity: "blocked",
    resource_type: "dossier_section",
    resource_public_id: "sec-1",
    resource_label: "A.1",
    case_public_id: "case-1",
    dossier_public_id: "dossier-1",
    due_date: null,
    operational_state: "blocked",
    ...over,
  };
}

async function mount(over: Record<string, unknown> = {}) {
  const { submissionOperations } = await import("@/lib/api");
  const mocks = submissionOperations as unknown as OpsMocks;
  mocks.overview.mockResolvedValue({ ...FULL_OVERVIEW, ...(over.overview ?? {}) });
  mocks.attention.mockResolvedValue({
    results: (over.attention as unknown[]) ?? [attentionRow()],
    count: 1,
    truncated: Boolean(over.truncated),
  });
  mocks.cases.mockResolvedValue(
    over.cases ?? {
      count: 1,
      results: [
        {
          public_id: "case-1",
          case_number: "C-001",
          title: "Synthetic case",
          status: "open",
          target_date: null,
          owner: null,
          last_activity_at: "2026-08-27T00:00:00Z",
          dossiers: { total: 1, open: 1 },
          sections: {
            required_total: 4,
            required_complete: 1,
            blocked: 1,
            overdue: 2,
            due_soon: 0,
          },
          open_blockers: 1,
          internal_readiness: "internally_not_ready",
          workflow_attention: 0,
          upgrade_attention: 0,
        },
      ],
    }
  );
  mocks.dossiers.mockResolvedValue(over.dossiers ?? { count: 0, results: [] });
  mocks.owners.mockResolvedValue(over.owners ?? { count: 0, results: [] });
  mocks.recentActivity.mockResolvedValue(over.activity ?? { count: 0, results: [] });

  const Page = (await import("@/app/(regx)/submission-operations/page")).default;
  render(<Page />);
  return mocks;
}

describe("Submission operations page", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders the summary cards from the overview", async () => {
    await mount();
    await waitFor(() => expect(screen.getByTestId("summary-cards")).toBeInTheDocument());
    expect(screen.getByTestId("card-open-cases")).toHaveTextContent("2");
    expect(screen.getByTestId("card-blocked-sections")).toHaveTextContent("2");
    expect(screen.getByTestId("card-overdue-sections")).toHaveTextContent("3");
  });

  it("shows the standing internal-only note", async () => {
    await mount();
    await waitFor(() =>
      expect(screen.getByTestId("internal-only-note")).toHaveTextContent(
        /internal RegX operational status only/i
      )
    );
  });

  it("labels a restricted module Unavailable rather than zero", async () => {
    await mount({
      overview: { documents: null, workflows: null, restricted_modules: ["documents", "workflows"] },
    });
    await waitFor(() =>
      expect(screen.getByTestId("card-waiting-review")).toHaveAttribute(
        "data-restricted",
        "true"
      )
    );
    const card = screen.getByTestId("card-waiting-review");
    expect(card).toHaveTextContent(/Unavailable/);
    expect(card.textContent).not.toMatch(/\b0\b/);
  });

  it("renders the attention queue in the order the API returned", async () => {
    await mount({
      attention: [
        attentionRow({ resource_public_id: "s1", resource_label: "A.1", severity: "blocked" }),
        attentionRow({
          resource_public_id: "s2",
          resource_label: "A.2",
          severity: "overdue",
          reason_code: "overdue_required_section",
          due_date: "2026-08-01",
        }),
        attentionRow({
          resource_public_id: "s3",
          resource_label: "A.3",
          severity: "attention",
          reason_code: "due_soon_required_section",
          due_date: "2026-08-30",
        }),
      ],
    });
    await waitFor(() => expect(screen.getByTestId("attention-rows")).toBeInTheDocument());
    const badges = within(screen.getByTestId("attention-rows")).getAllByTestId(
      "severity-badge"
    );
    expect(badges.map((b) => b.getAttribute("data-severity"))).toEqual([
      "blocked",
      "overdue",
      "attention",
    ]);
  });

  it("says nothing needs attention rather than showing an empty table", async () => {
    await mount({ attention: [] });
    await waitFor(() =>
      expect(screen.getByTestId("attention-empty")).toHaveTextContent(/Nothing currently needs/i)
    );
  });

  it("distinguishes a restricted case panel from an empty one", async () => {
    await mount({ cases: { results: null, count: null, restricted: true } });
    await waitFor(() =>
      expect(screen.getByTestId("cases-empty")).toHaveAttribute("data-restricted", "true")
    );
    expect(screen.getByTestId("cases-empty")).toHaveTextContent(/permission to view cases/i);
  });

  it("switches detail panels without losing the summary", async () => {
    const user = userEvent.setup();
    await mount({
      owners: {
        count: 1,
        results: [
          {
            owner: { public_id: "u1", full_name: "Ana Doer" },
            unassigned: false,
            required_total: 3,
            outstanding: 2,
            blocked: 1,
            overdue: 1,
          },
        ],
      },
    });
    await waitFor(() => expect(screen.getByTestId("tab-owners")).toBeInTheDocument());
    await user.click(screen.getByTestId("tab-owners"));
    await waitFor(() => expect(screen.getByTestId("owner-rows")).toHaveTextContent("Ana Doer"));
    expect(screen.getByTestId("card-open-cases")).toBeInTheDocument();
  });

  it("re-queries when the severity filter changes", async () => {
    const user = userEvent.setup();
    const mocks = await mount();
    await waitFor(() => expect(mocks.attention).toHaveBeenCalled());
    mocks.attention.mockClear();

    await user.selectOptions(screen.getByTestId("severity-filter"), "blocked");
    await waitFor(() =>
      expect(mocks.attention).toHaveBeenCalledWith("t", { severity: "blocked" })
    );
  });

  it("warns when the queue was truncated rather than implying completeness", async () => {
    await mount({ truncated: true });
    await waitFor(() =>
      expect(screen.getByTestId("attention-truncated")).toHaveTextContent(/more exist/i)
    );
  });

  it("surfaces a load failure as an alert", async () => {
    const { submissionOperations } = await import("@/lib/api");
    const mocks = submissionOperations as unknown as OpsMocks;
    mocks.overview.mockRejectedValue(new Error("boom"));
    mocks.attention.mockResolvedValue({ results: [], count: 0, truncated: false });
    mocks.cases.mockResolvedValue({ count: 0, results: [] });
    mocks.dossiers.mockResolvedValue({ count: 0, results: [] });
    mocks.owners.mockResolvedValue({ count: 0, results: [] });
    mocks.recentActivity.mockResolvedValue({ count: 0, results: [] });

    const Page = (await import("@/app/(regx)/submission-operations/page")).default;
    render(<Page />);
    await waitFor(() => expect(screen.getByTestId("ops-error")).toBeInTheDocument());
  });
});
