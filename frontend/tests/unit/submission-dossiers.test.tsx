import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import "@testing-library/jest-dom/vitest";

import DossierPage from "@/app/(regx)/submission-dossiers/[publicId]/page";
import {
  ReadinessBadge,
  SectionStatusBadge,
  BlockerIndicator,
} from "@/app/(regx)/submission-dossiers/readiness-badge";
import { SectionTree, buildRows } from "@/app/(regx)/submission-dossiers/section-tree";
import { ApiError } from "@/lib/api";

const push = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push }),
  useSearchParams: () => new URLSearchParams("tenant=alpha"),
  useParams: () => ({ publicId: "dossier-1" }),
}));

const getMock = vi.fn();
const getSectionMock = vi.fn();
const completeMock = vi.fn();
const createSectionMock = vi.fn();

/* Errors must be instances of the MOCKED ApiError: the component branches on
 * `err instanceof ApiError`, so a look-alike falls through to the generic
 * handler and the specific 404 / 409 paths never run. */
function apiError(status: number): Error {
  return new (ApiError as unknown as new (s: number, m?: string) => Error)(status, "err");
}

vi.mock("@/lib/api", () => ({
  isSignedOut: (e: { status?: number } | undefined) => e?.status === 401,
  loadError: (e: { status?: number; message?: string } | undefined, fallback: string) =>
    e?.status === 403 ? (e.message ?? fallback) : fallback,
  ApiError: class extends Error {
    status: number;
    constructor(status: number, message = "err") {
      super(message);
      this.status = status;
    }
  },
  submissionDossiers: {
    get: (...a: unknown[]) => getMock(...a),
    getSection: (...a: unknown[]) => getSectionMock(...a),
    complete: (...a: unknown[]) => completeMock(...a),
    cancel: vi.fn(),
    createSection: (...a: unknown[]) => createSectionMock(...a),
    updateSection: vi.fn(),
    createBlocker: vi.fn(),
    resolveBlocker: vi.fn(),
    linkTarget: vi.fn(),
    unlinkTarget: vi.fn(),
    listForCase: vi.fn(),
    create: vi.fn(),
  },
  // Milestone 10 added a blueprint provenance line to this page. The mock is an
  // explicit allow-list, so a client the page genuinely uses has to appear here
  // or every test in the file fails on the import. Resolving to "not from a
  // blueprint" keeps these tests about the dossier workspace.
  dossierBlueprints: {
    provenanceForDossier: () => Promise.resolve({ instantiated_from_blueprint: false }),
  },
}));

const PERMS = {
  can_create: true,
  can_edit: true,
  can_manage_sections: true,
  can_manage_links: true,
  can_manage_blockers: true,
  can_complete: true,
  can_cancel: true,
};

function section(over: Record<string, unknown> = {}) {
  return {
    public_id: "s-1",
    parent_public_id: null,
    section_code: "1",
    title: "Quality overall summary",
    description: "",
    notes: "",
    sequence: 0,
    required: true,
    status: "not_started",
    readiness: "not_ready",
    readiness_reason: "no_supporting_work",
    owner: null,
    due_date: null,
    is_retired: false,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...over,
  };
}

function detail(over: Record<string, unknown> = {}) {
  return {
    dossier: {
      public_id: "dossier-1",
      regulatory_case_public_id: "case-1",
      title: "Initial submission",
      description: "",
      status: "open",
      owner: null,
      target_date: null,
      created_by: null,
      created_at: "2026-01-01T00:00:00Z",
      updated_at: "2026-01-01T00:00:00Z",
      is_terminal: false,
    },
    sections: [section()],
    summary: {
      total_sections: 1,
      required_sections: 1,
      ready: 0,
      partially_ready: 0,
      not_ready: 1,
      not_applicable: 0,
      open_blockers: 0,
      overall_readiness: "not_ready",
      overall_reason: "no_supporting_work",
    },
    module_counts: { workflow_evidence_links: 0 },
    permissions: PERMS,
    ...over,
  };
}

function sectionDetail(over: Record<string, unknown> = {}) {
  return {
    section: section(),
    children: [],
    documents: [],
    workflows: [],
    checklists: [],
    blockers: [],
    module_counts: { workflow_evidence_links: 0 },
    permissions: PERMS,
    ...over,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  getMock.mockResolvedValue(detail());
  getSectionMock.mockResolvedValue(sectionDetail());
});

describe("Dossier workspace", () => {
  it("renders the header with internal readiness, not an approval claim", async () => {
    render(<DossierPage />);
    expect(await screen.findByText("Initial submission")).toBeInTheDocument();
    expect(screen.getByText(/internal readiness/i)).toBeInTheDocument();
    expect(screen.queryByText(/approved|agency|compliant/i)).not.toBeInTheDocument();
  });

  it("shows summary counts", async () => {
    getMock.mockResolvedValue(
      detail({
        summary: {
          total_sections: 7,
          required_sections: 5,
          ready: 2,
          partially_ready: 1,
          not_ready: 3,
          not_applicable: 1,
          open_blockers: 4,
          overall_readiness: "partially_ready",
          overall_reason: "section_not_complete",
        },
      })
    );
    render(<DossierPage />);
    expect(await screen.findByTestId("stat-total")).toHaveTextContent("7");
    expect(screen.getByTestId("stat-blockers")).toHaveTextContent("4");
  });

  it("renders a withheld module count as an em dash, never zero", async () => {
    getMock.mockResolvedValue(detail({ module_counts: { workflow_evidence_links: null } }));
    render(<DossierPage />);
    const stat = await screen.findByTestId("stat-evidence");
    expect(stat).toHaveTextContent("—");
    expect(stat).not.toHaveTextContent("0");
  });

  it("hides structural controls on a terminal dossier", async () => {
    getMock.mockResolvedValue(
      detail({ dossier: { ...detail().dossier, status: "completed", is_terminal: true } })
    );
    render(<DossierPage />);
    await screen.findByTestId("dossier-terminal-note");
    expect(screen.queryByTestId("add-section")).not.toBeInTheDocument();
    expect(screen.queryByTestId("complete-dossier")).not.toBeInTheDocument();
  });

  it("states plainly that completion is not a regulatory approval", async () => {
    getMock.mockResolvedValue(
      detail({ dossier: { ...detail().dossier, status: "completed", is_terminal: true } })
    );
    render(<DossierPage />);
    expect(await screen.findByTestId("dossier-terminal-note")).toHaveTextContent(
      /not a regulatory approval/i
    );
  });

  it("hides complete and cancel when the API withholds them", async () => {
    getMock.mockResolvedValue(
      detail({ permissions: { ...PERMS, can_complete: false, can_cancel: false } })
    );
    render(<DossierPage />);
    await screen.findByText("Initial submission");
    expect(screen.queryByTestId("complete-dossier")).not.toBeInTheDocument();
    expect(screen.queryByTestId("cancel-dossier")).not.toBeInTheDocument();
  });

  it("surfaces a 409 and keeps it visible after the reload", async () => {
    completeMock.mockRejectedValue(apiError(409));
    const user = userEvent.setup();
    render(<DossierPage />);
    await user.click(await screen.findByTestId("complete-dossier"));
    expect(await screen.findByTestId("dossier-error")).toHaveTextContent(/not internally ready/i);
  });

  it("shows a not-found state rather than an empty shell", async () => {
    getMock.mockRejectedValue(apiError(404));
    render(<DossierPage />);
    expect(await screen.findByTestId("dossier-not-found")).toBeInTheDocument();
  });

  it("shows an empty outline state", async () => {
    getMock.mockResolvedValue(detail({ sections: [] }));
    render(<DossierPage />);
    expect(await screen.findByTestId("sections-empty")).toBeInTheDocument();
  });

  it("selecting a section loads its detail panel", async () => {
    const user = userEvent.setup();
    render(<DossierPage />);
    await user.click(await screen.findByTestId("select-s-1"));
    await waitFor(() => expect(getSectionMock).toHaveBeenCalledWith("alpha", "s-1"));
    expect(await screen.findByTestId("section-panel")).toBeInTheDocument();
  });

  it("shows a restricted marker rather than inventing detail", async () => {
    getSectionMock.mockResolvedValue(
      sectionDetail({
        documents: [
          {
            public_id: "l-1",
            purpose: "",
            linked_at: "2026-02-01T00:00:00Z",
            linked_by: null,
            document_public_id: "d-1",
            restricted: true,
          },
        ],
      })
    );
    const user = userEvent.setup();
    render(<DossierPage />);
    await user.click(await screen.findByTestId("select-s-1"));
    await user.click(await screen.findByTestId("section-tab-documents"));
    expect(await screen.findByTestId("link-restricted")).toHaveTextContent(/access restricted/i);
  });
});

describe("Section tree", () => {
  const tree = [
    section({ public_id: "a", section_code: "1", sequence: 0 }),
    section({ public_id: "b", section_code: "1.1", parent_public_id: "a", sequence: 0 }),
    section({ public_id: "c", section_code: "2", sequence: 10 }),
  ];

  it("orders by sequence and nests by parent, not by parsing the code", () => {
    const rows = buildRows(tree as never, new Set());
    expect(rows.map((r) => r.section.section_code)).toEqual(["1", "1.1", "2"]);
    expect(rows.map((r) => r.depth)).toEqual([0, 1, 0]);
  });

  it("collapsing hides descendants by filtering, not unmounting a subtree", () => {
    const rows = buildRows(tree as never, new Set(["a"]));
    expect(rows.map((r) => r.section.section_code)).toEqual(["1", "2"]);
  });

  it("renders every row as a sibling so a 500-section outline stays flat", () => {
    render(<SectionTree sections={tree as never} />);
    const items = screen.getAllByTestId("section-row");
    expect(items).toHaveLength(3);
    // All three share one parent element: depth is padding, not nesting.
    const parents = new Set(items.map((el) => el.parentElement));
    expect(parents.size).toBe(1);
  });

  it("filters by code or title through the search box", async () => {
    const user = userEvent.setup();
    render(<SectionTree sections={tree as never} />);
    await user.type(screen.getByTestId("section-search"), "1.1");
    expect(screen.getAllByTestId("section-row")).toHaveLength(1);
  });

  it("reports when nothing matches instead of rendering an empty list", async () => {
    const user = userEvent.setup();
    render(<SectionTree sections={tree as never} />);
    await user.type(screen.getByTestId("section-search"), "zzzz");
    expect(screen.getByTestId("sections-no-match")).toBeInTheDocument();
  });

  it("exposes tree semantics for assistive technology", () => {
    render(<SectionTree sections={tree as never} />);
    expect(screen.getByRole("tree")).toBeInTheDocument();
    const items = screen.getAllByRole("treeitem");
    expect(items[0]).toHaveAttribute("aria-level", "1");
    expect(items[1]).toHaveAttribute("aria-level", "2");
    expect(items[0]).toHaveAttribute("aria-expanded", "true");
  });

  it("shows an empty state when there are no sections", () => {
    render(<SectionTree sections={[]} />);
    expect(screen.getByTestId("sections-empty")).toBeInTheDocument();
  });
});

describe("Readiness badges", () => {
  it("never communicates readiness by colour alone", () => {
    for (const r of ["ready", "partially_ready", "not_ready", "not_applicable"] as const) {
      const { unmount } = render(<ReadinessBadge readiness={r} />);
      const badge = screen.getByTestId("readiness-badge");
      expect(badge).toHaveAttribute("data-readiness", r);
      // A text label is always present, so colour is never the only signal.
      expect(badge.textContent?.replace(/[●◐○–]/g, "").trim().length).toBeGreaterThan(0);
      unmount();
    }
  });

  it("uses no approval-coloured fill for READY", () => {
    render(<ReadinessBadge readiness="ready" />);
    // Nothing green: READY is internal readiness, not an agency decision.
    expect(screen.getByTestId("readiness-badge").getAttribute("style")).not.toMatch(
      /#1a6b46|#eaf7f0/
    );
  });

  it("labels every section status", () => {
    for (const s of [
      "not_started",
      "in_progress",
      "blocked",
      "complete",
      "not_applicable",
    ] as const) {
      const { unmount } = render(<SectionStatusBadge status={s} />);
      expect(screen.getByTestId("section-status-badge")).toHaveAttribute("data-status", s);
      unmount();
    }
  });

  it("renders nothing when there are no blockers", () => {
    const { container } = render(<BlockerIndicator count={0} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("pluralises the blocker count", () => {
    render(<BlockerIndicator count={1} />);
    expect(screen.getByTestId("blocker-indicator")).toHaveTextContent("1 blocker");
  });
});
