import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import {
  Checksum,
  FREEZE_CONFIRM_NOTE,
  FROZEN_MEANS_NOTE,
  FrozenMeansNote,
  PackageStatusBadge,
  ScanStatusBadge,
  Unavailable,
  issueLabel,
} from "@/app/(regx)/submission-packages/package-primitives";

// ---------------------------------------------------------------------------
// Wording: frozen is internal, and never anything else
// ---------------------------------------------------------------------------
describe("Internal-only wording", () => {
  it("the frozen note says what frozen is not", () => {
    const note = FROZEN_MEANS_NOTE.toLowerCase();
    expect(note).toContain("internal regx package state");
    for (const denied of ["regulatory approval", "qa approval", "agency acceptance"]) {
      expect(note).toContain(denied);
    }
  });

  it("the freeze confirmation explains the exact-version consequence", () => {
    const note = FREEZE_CONFIRM_NOTE.toLowerCase();
    expect(note).toContain("exact document");
    expect(note).toContain("future document uploads will not change it");
    expect(note).toContain("cannot be reopened");
  });

  it("no status label borrows agency or approval language", () => {
    for (const status of ["draft", "in_review", "frozen", "cancelled"] as const) {
      const { unmount } = render(<PackageStatusBadge status={status} />);
      const text = screen.getByTestId("package-status-badge").textContent!.toLowerCase();
      for (const banned of ["approved", "accepted", "agency", "ready to file", "compliant"]) {
        expect(text).not.toContain(banned);
      }
      unmount();
    }
  });

  it("renders the standing note", () => {
    render(<FrozenMeansNote />);
    expect(screen.getByTestId("frozen-means-note")).toHaveTextContent(/internal RegX/i);
  });
});

// ---------------------------------------------------------------------------
// Badges carry words, not colour alone
// ---------------------------------------------------------------------------
describe("Badges", () => {
  it.each(["draft", "in_review", "frozen", "cancelled"] as const)(
    "package status %s has a text label",
    (status) => {
      render(<PackageStatusBadge status={status} />);
      const badge = screen.getByTestId("package-status-badge");
      expect(badge.textContent?.trim().length ?? 0).toBeGreaterThan(0);
      expect(badge).toHaveAttribute("data-status", status);
    }
  );

  it.each(["clean", "pending", "quarantined", "infected", "scan_failed"] as const)(
    "scan status %s has a text label",
    (status) => {
      render(<ScanStatusBadge status={status} />);
      expect(screen.getByTestId("scan-status-badge").textContent?.trim().length).toBeGreaterThan(0);
    }
  );

  it("maps every integrity code the backend can emit", () => {
    const codes = [
      "no_active_entries",
      "document_version_unavailable",
      "scan_not_cleared",
      "checksum_missing",
      "duplicate_path",
      "tenant_mismatch",
      "case_mismatch",
      "section_retired",
      "storage_unavailable",
      "too_many_entries",
      "too_large",
    ];
    for (const code of codes) {
      expect(issueLabel(code)).not.toBe(code);
    }
  });
});

// ---------------------------------------------------------------------------
// Restricted document data
// ---------------------------------------------------------------------------
describe("Restricted projection", () => {
  it("renders Unavailable rather than a blank", () => {
    render(<Unavailable testId="u" />);
    expect(screen.getByTestId("u")).toHaveTextContent("Unavailable");
  });

  it("an absent checksum is Unavailable, not an empty code block", () => {
    render(<Checksum value="" testId="c" />);
    expect(screen.getByTestId("c")).toHaveTextContent("Unavailable");
  });

  it("a checksum is abbreviated but carries the full value for copying", () => {
    const full = "a".repeat(64);
    render(<Checksum value={full} testId="c" />);
    const el = screen.getByTestId("c");
    expect(el).toHaveAttribute("title", full);
    expect(el.textContent).not.toBe(full);
  });
});

// ---------------------------------------------------------------------------
// The page
// ---------------------------------------------------------------------------
vi.mock("next/navigation", () => ({
  useParams: () => ({ publicId: "pkg-1" }),
  useSearchParams: () => new URLSearchParams("tenant=t"),
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
}));

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    ApiError: class extends Error {
      status: number;
      constructor(status: number, message = "err") {
        super(message);
        this.status = status;
      }
    },
    submissionPackages: {
      listForCase: vi.fn(),
      create: vi.fn(),
      get: vi.fn(),
      addEntry: vi.fn(),
      removeEntry: vi.fn(),
      reorderEntry: vi.fn(),
      submitForReview: vi.fn(),
      returnToDraft: vi.fn(),
      freeze: vi.fn(),
      cancel: vi.fn(),
      clone: vi.fn(),
      validate: vi.fn(),
      manifest: vi.fn(),
      exportUrl: (id: string) => `/api/regx/v1/submission-packages/${id}/export/`,
    },
  };
});

type PkgMocks = Record<
  keyof typeof import("@/lib/api")["submissionPackages"],
  ReturnType<typeof vi.fn>
>;

const PERMS = {
  can_view: true,
  can_create: true,
  can_edit: true,
  can_manage_entries: true,
  can_review: true,
  can_freeze: true,
  can_cancel: true,
  can_export: true,
};

function entry(over: Record<string, unknown> = {}) {
  return {
    public_id: "entry-1",
    sequence: 0,
    logical_path: "01-cover",
    export_filename: "report.pdf",
    display_name: "report.pdf",
    dossier_section_public_id: null,
    is_active: true,
    added_at: "2026-01-01T00:00:00Z",
    document: {
      document_public_id: "doc-1",
      document_version_public_id: "ver-1",
      version_number: 1,
      title: "Synthetic report",
      checksum_sha256: "b".repeat(64),
      size_bytes: 1024,
      mime_type: "application/pdf",
      scan_status: "clean",
    },
    ...over,
  };
}

function pkg(over: Record<string, unknown> = {}) {
  return {
    public_id: "pkg-1",
    name: "Synthetic package",
    description: "",
    status: "draft",
    revision_number: 1,
    case_public_id: "case-1",
    source_package_public_id: null,
    entry_count: 1,
    manifest_checksum: "",
    created_by: { public_id: "u1", full_name: "Author" },
    created_at: "2026-01-01T00:00:00Z",
    frozen_by: null,
    frozen_at: null,
    cancelled_at: null,
    permissions: PERMS,
    entries: [entry()],
    ...over,
  };
}

async function mount(detail: Record<string, unknown> = {}, integrity: Record<string, unknown> = {}) {
  const { submissionPackages } = await import("@/lib/api");
  const mocks = submissionPackages as unknown as PkgMocks;
  mocks.get.mockResolvedValue({ ...pkg(), ...detail });
  mocks.validate.mockResolvedValue({
    valid: true,
    issues: [],
    semantics: "internal_package_integrity",
    ...integrity,
  });

  const Page = (await import("@/app/(regx)/submission-packages/[publicId]/page")).default;
  render(<Page />);
  return mocks;
}

describe("Submission package page", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("lists entries with their exact version and checksum", async () => {
    await mount();
    await waitFor(() => expect(screen.getByTestId("entry-rows")).toBeInTheDocument());
    const rows = screen.getByTestId("entry-rows");
    expect(within(rows).getByTestId("entry-version")).toHaveTextContent("v1");
    expect(within(rows).getByTestId("entry-checksum")).toBeInTheDocument();
    expect(rows).toHaveTextContent("Synthetic report");
  });

  it("shows Unavailable for a document the caller may not see", async () => {
    await mount({ entries: [entry({ document: null })] });
    await waitFor(() =>
      expect(screen.getByTestId("entry-document-unavailable")).toHaveTextContent("Unavailable")
    );
    expect(screen.queryByTestId("entry-checksum")).not.toBeInTheDocument();
  });

  it("offers reorder and remove as buttons, with accessible names", async () => {
    await mount({ entries: [entry(), entry({ public_id: "entry-2", sequence: 1 })] });
    await waitFor(() => expect(screen.getByTestId("entry-rows")).toBeInTheDocument());
    const removes = screen.getAllByTestId("entry-remove");
    expect(removes[0]).toHaveAccessibleName(/Remove report.pdf/i);
    const moves = screen.getAllByTestId("entry-move-up");
    expect(moves[0]).toBeDisabled();
    expect(moves[1]).toBeEnabled();
  });

  it("adds an exact version and never offers a latest option", async () => {
    const user = userEvent.setup();
    const mocks = await mount();
    await waitFor(() => expect(screen.getByTestId("entry-add")).toBeInTheDocument());

    const body = document.body.textContent!.toLowerCase();
    expect(body).not.toContain("latest version");
    expect(body).toContain("exact");

    await user.type(screen.getByTestId("entry-version-input"), "ver-9");
    await user.click(screen.getByTestId("entry-add"));
    await waitFor(() =>
      expect(mocks.addEntry).toHaveBeenCalledWith("t", "pkg-1", {
        document_version_public_id: "ver-9",
        logical_path: "",
      })
    );
  });

  it("refuses to add without a version rather than guessing one", async () => {
    const user = userEvent.setup();
    const mocks = await mount();
    await waitFor(() => expect(screen.getByTestId("entry-add")).toBeInTheDocument());
    await user.click(screen.getByTestId("entry-add"));
    await waitFor(() =>
      expect(screen.getByTestId("package-error")).toHaveTextContent(/exact document version/i)
    );
    expect(mocks.addEntry).not.toHaveBeenCalled();
  });

  it("asks for confirmation before freezing and explains what freezing does", async () => {
    const user = userEvent.setup();
    const mocks = await mount({ status: "in_review" });
    await waitFor(() => expect(screen.getByTestId("freeze-package")).toBeInTheDocument());

    await user.click(screen.getByTestId("freeze-package"));
    const confirm = screen.getByTestId("freeze-confirm");
    expect(confirm).toHaveTextContent(/exact document versions/i);
    expect(confirm).toHaveTextContent(/cannot be reopened/i);
    expect(mocks.freeze).not.toHaveBeenCalled();

    await user.click(screen.getByTestId("freeze-confirm-yes"));
    await waitFor(() => expect(mocks.freeze).toHaveBeenCalledWith("t", "pkg-1"));
  });

  it("cancelling the confirmation freezes nothing", async () => {
    const user = userEvent.setup();
    const mocks = await mount({ status: "in_review" });
    await waitFor(() => expect(screen.getByTestId("freeze-package")).toBeInTheDocument());
    await user.click(screen.getByTestId("freeze-package"));
    await user.click(screen.getByTestId("freeze-confirm-no"));
    expect(mocks.freeze).not.toHaveBeenCalled();
    expect(screen.queryByTestId("freeze-confirm")).not.toBeInTheDocument();
  });

  it("a frozen package shows its manifest and offers export and clone", async () => {
    await mount({
      status: "frozen",
      manifest_checksum: "c".repeat(64),
      frozen_at: "2026-02-01T00:00:00Z",
    });
    await waitFor(() => expect(screen.getByTestId("manifest-summary")).toBeInTheDocument());
    expect(screen.getByTestId("manifest-checksum")).toBeInTheDocument();
    expect(screen.getByTestId("export-zip")).toHaveTextContent(/Export internal ZIP/i);
    expect(screen.getByTestId("clone-package")).toBeInTheDocument();
    expect(screen.getByTestId("frozen-means-note")).toBeInTheDocument();
  });

  it("a frozen package offers no way to change its contents", async () => {
    await mount({ status: "frozen", manifest_checksum: "c".repeat(64) });
    await waitFor(() => expect(screen.getByTestId("entry-rows")).toBeInTheDocument());
    expect(screen.queryByTestId("entry-add")).not.toBeInTheDocument();
    expect(screen.queryByTestId("entry-remove")).not.toBeInTheDocument();
    expect(screen.queryByTestId("freeze-package")).not.toBeInTheDocument();
    expect(screen.queryByTestId("return-to-draft")).not.toBeInTheDocument();
  });

  it("the export button never says publish or send", async () => {
    await mount({ status: "frozen", manifest_checksum: "c".repeat(64) });
    await waitFor(() => expect(screen.getByTestId("export-zip")).toBeInTheDocument());
    const label = screen.getByTestId("export-zip").textContent!.toLowerCase();
    for (const banned of ["publish", "send", "submit to", "generate submission", "agency"]) {
      expect(label).not.toContain(banned);
    }
  });

  it("hides controls the caller has no permission for", async () => {
    await mount({
      status: "in_review",
      permissions: { ...PERMS, can_freeze: false, can_manage_entries: false },
    });
    await waitFor(() => expect(screen.getByTestId("entry-rows")).toBeInTheDocument());
    expect(screen.queryByTestId("freeze-package")).not.toBeInTheDocument();
    expect(screen.queryByTestId("entry-add")).not.toBeInTheDocument();
  });

  it("shows integrity issues as readable reasons", async () => {
    await mount(
      {},
      { valid: false, issues: [{ code: "duplicate_path", entry_public_id: "entry-1", detail: null }] }
    );
    await waitFor(() =>
      expect(screen.getByTestId("integrity-issues")).toHaveTextContent(/same path/i)
    );
  });

  it("states that integrity is not a regulatory assessment", async () => {
    await mount();
    await waitFor(() => expect(screen.getByTestId("integrity-ok")).toBeInTheDocument());
    expect(screen.getByTestId("integrity-ok")).toHaveTextContent(/not a regulatory/i);
  });

  it("surfaces a load failure as an alert", async () => {
    const { submissionPackages } = await import("@/lib/api");
    const mocks = submissionPackages as unknown as PkgMocks;
    mocks.get.mockRejectedValue(new Error("boom"));
    mocks.validate.mockResolvedValue({ valid: true, issues: [], semantics: "x" });

    const Page = (await import("@/app/(regx)/submission-packages/[publicId]/page")).default;
    render(<Page />);
    await waitFor(() => expect(screen.getByTestId("package-error")).toBeInTheDocument());
  });
});
