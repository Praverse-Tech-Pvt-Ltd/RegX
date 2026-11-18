import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import "@testing-library/jest-dom/vitest";

import CasesPage from "@/app/(regx)/regulatory-cases/page";
import CaseDetailPage from "@/app/(regx)/regulatory-cases/[publicId]/page";
import { CaseStatusBadge } from "@/app/(regx)/regulatory-cases/status-badge";
import { ApiError } from "@/lib/api";

const push = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push }),
  useSearchParams: () => new URLSearchParams("tenant=alpha"),
  useParams: () => ({ publicId: "case-1" }),
}));

const listMock = vi.fn();
const getMock = vi.fn();
const createMock = vi.fn();
const completeMock = vi.fn();
const unlinkMock = vi.fn();
const linkMock = vi.fn();

/*
 * Errors must be instances of the MOCKED ApiError: the components branch on
 * `err instanceof ApiError`, so a look-alike class falls through to the generic
 * handler and the specific 404 / 409 paths never run.
 */
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
  regulatoryCases: {
    list: (...a: unknown[]) => listMock(...a),
    get: (...a: unknown[]) => getMock(...a),
    create: (...a: unknown[]) => createMock(...a),
    complete: (...a: unknown[]) => completeMock(...a),
    cancel: vi.fn(),
    linkTarget: (...a: unknown[]) => linkMock(...a),
    unlinkTarget: (...a: unknown[]) => unlinkMock(...a),
  },
}));

const PERMS = {
  can_edit: true,
  can_manage_links: true,
  can_complete: true,
  can_cancel: true,
  can_create: true,
};

function caseRow(over: Record<string, unknown> = {}) {
  return {
    public_id: "case-1",
    case_number: "RC-000001",
    title: "Stability data package",
    product_name: "Product X",
    product_code: "PX-1",
    market: "Synthetic Market",
    authority: "Synthetic Authority",
    submission_type: "Synthetic Type",
    status: "open",
    owner: { public_id: "u-1", full_name: "Case Owner" },
    target_date: "2026-06-01",
    description: "",
    created_by: { public_id: "u-1", full_name: "Case Owner" },
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    is_terminal: false,
    ...over,
  };
}

function detail(over: Record<string, unknown> = {}) {
  return {
    case: caseRow(),
    workflows: [],
    documents: [],
    checklists: [],
    summary: {
      documents: 0,
      workflows: 0,
      checklists: 0,
      workflows_open: 0,
      workflows_completed: 0,
      evidence_links: 0,
    },
    permissions: PERMS,
    ...over,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  listMock.mockResolvedValue({ results: [caseRow()], permissions: PERMS });
  getMock.mockResolvedValue(detail());
});

describe("Regulatory cases list", () => {
  it("renders cases with number, product and status", async () => {
    render(<CasesPage />);
    expect(await screen.findByTestId("cases-table")).toBeInTheDocument();
    expect(screen.getByText("RC-000001")).toBeInTheDocument();
    expect(screen.getByText("Product X")).toBeInTheDocument();
    expect(screen.getByTestId("case-status-badge")).toHaveAttribute("data-status", "open");
  });

  it("shows an empty state when there are no cases", async () => {
    listMock.mockResolvedValue({ results: [], permissions: PERMS });
    render(<CasesPage />);
    expect(await screen.findByTestId("cases-empty")).toBeInTheDocument();
  });

  it("hides the create control when the API says the caller cannot create", async () => {
    listMock.mockResolvedValue({
      results: [],
      permissions: { ...PERMS, can_create: false },
    });
    render(<CasesPage />);
    await screen.findByTestId("cases-empty");
    // Advisory only, but it must not invite an action the API will refuse.
    expect(screen.queryByTestId("new-case")).not.toBeInTheDocument();
  });

  it("surfaces a load failure rather than rendering an empty table", async () => {
    listMock.mockRejectedValue(apiError(500));
    render(<CasesPage />);
    expect(await screen.findByTestId("cases-error")).toBeInTheDocument();
  });

  it("filters by status through the API, not client-side", async () => {
    const user = userEvent.setup();
    render(<CasesPage />);
    await screen.findByTestId("cases-table");
    await user.selectOptions(screen.getByTestId("status-filter"), "completed");
    await waitFor(() =>
      expect(listMock).toHaveBeenCalledWith("alpha", expect.objectContaining({ status: "completed" }))
    );
  });
});

describe("Regulatory case detail", () => {
  it("renders the header with case identity", async () => {
    render(<CaseDetailPage />);
    expect(await screen.findByText("RC-000001")).toBeInTheDocument();
    expect(screen.getByText("Stability data package")).toBeInTheDocument();
    expect(screen.getByText("Synthetic Authority")).toBeInTheDocument();
  });

  it("shows summary counts", async () => {
    getMock.mockResolvedValue(
      detail({
        summary: {
          documents: 3,
          workflows: 2,
          checklists: 1,
          workflows_open: 1,
          workflows_completed: 1,
          evidence_links: 4,
        },
      })
    );
    render(<CaseDetailPage />);
    expect(await screen.findByTestId("stat-documents")).toHaveTextContent("3");
    expect(screen.getByTestId("stat-evidence")).toHaveTextContent("4");
  });

  it("shows a restricted marker instead of detail the caller may not see", async () => {
    getMock.mockResolvedValue(
      detail({
        documents: [
          {
            public_id: "l-1",
            label: "",
            linked_at: "2026-02-01T00:00:00Z",
            linked_by: { full_name: "Doer" },
            document_public_id: "d-1",
            restricted: true,
          },
        ],
        summary: { ...detail().summary, documents: 1 },
      })
    );
    const user = userEvent.setup();
    render(<CaseDetailPage />);
    await screen.findByTestId("tab-documents");
    await user.click(screen.getByTestId("tab-documents"));

    expect(await screen.findByTestId("link-restricted")).toBeInTheDocument();
    // No title is present to leak, and none is invented.
    expect(screen.queryByText(/Confidential/i)).not.toBeInTheDocument();
  });

  it("renders document detail when the caller is permitted", async () => {
    getMock.mockResolvedValue(
      detail({
        documents: [
          {
            public_id: "l-1",
            label: "",
            linked_at: "2026-02-01T00:00:00Z",
            linked_by: { full_name: "Doer" },
            document_public_id: "d-1",
            document: {
              title: "Stability Protocol SP-014",
              document_type: "other",
              status: "active",
              current_version_number: 3,
              scan_status: "clean",
            },
          },
        ],
      })
    );
    const user = userEvent.setup();
    render(<CaseDetailPage />);
    await user.click(await screen.findByTestId("tab-documents"));
    expect(await screen.findByText("Stability Protocol SP-014")).toBeInTheDocument();
  });

  it("hides link and unlink controls on a terminal case", async () => {
    getMock.mockResolvedValue(
      detail({ case: caseRow({ status: "completed", is_terminal: true }) })
    );
    const user = userEvent.setup();
    render(<CaseDetailPage />);
    await user.click(await screen.findByTestId("tab-documents"));
    expect(screen.queryByTestId("link-form")).not.toBeInTheDocument();
  });

  it("states plainly that completion is not a regulatory approval", async () => {
    getMock.mockResolvedValue(
      detail({ case: caseRow({ status: "completed", is_terminal: true }) })
    );
    render(<CaseDetailPage />);
    const note = await screen.findByTestId("case-terminal-note");
    expect(note).toHaveTextContent(/not a regulatory approval/i);
  });

  it("hides complete and cancel when the API withholds those permissions", async () => {
    getMock.mockResolvedValue(
      detail({ permissions: { ...PERMS, can_complete: false, can_cancel: false } })
    );
    render(<CaseDetailPage />);
    await screen.findByText("RC-000001");
    expect(screen.queryByTestId("complete-case")).not.toBeInTheDocument();
    expect(screen.queryByTestId("cancel-case")).not.toBeInTheDocument();
  });

  it("surfaces a 409 and keeps it visible after the reload", async () => {
    completeMock.mockRejectedValue(apiError(409));
    const user = userEvent.setup();
    render(<CaseDetailPage />);
    await user.click(await screen.findByTestId("complete-case"));
    // The message must survive the reload that follows -- load() clears errors
    // on success, so ordering matters.
    expect(await screen.findByTestId("case-error")).toHaveTextContent(/already been completed/i);
  });

  it("shows a not-found state rather than an empty shell", async () => {
    getMock.mockRejectedValue(apiError(404));
    render(<CaseDetailPage />);
    expect(await screen.findByTestId("case-not-found")).toBeInTheDocument();
  });

  it("explains that evidence belongs to workflows, not to the case", async () => {
    const user = userEvent.setup();
    render(<CaseDetailPage />);
    await user.click(await screen.findByTestId("tab-evidence"));
    expect(await screen.findByTestId("tab-panel-evidence")).toHaveTextContent(
      /recorded against workflow items/i
    );
  });
});

describe("CaseStatusBadge", () => {
  it("labels every status and never uses an approval-coloured fill", () => {
    for (const status of ["open", "on_hold", "completed", "cancelled"] as const) {
      const { unmount } = render(<CaseStatusBadge status={status} />);
      const badge = screen.getByTestId("case-status-badge");
      expect(badge).toHaveAttribute("data-status", status);
      // Nothing green: a completed case is not an approved submission.
      expect(badge.getAttribute("style")).not.toMatch(/#1a6b46|#eaf7f0/);
      unmount();
    }
  });

  it("does not fill any badge with the page surface colour", () => {
    // --panel #f4f8fe is the page background; a badge filled with it vanishes.
    for (const status of ["open", "on_hold", "completed", "cancelled"] as const) {
      const { unmount } = render(<CaseStatusBadge status={status} />);
      expect(screen.getByTestId("case-status-badge").getAttribute("style")).not.toMatch(
        /background:\s*rgb\(244,\s*248,\s*254\)/
      );
      unmount();
    }
  });
});
