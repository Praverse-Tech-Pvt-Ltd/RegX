import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { buildTreeRows } from "@/lib/tree";
import { BlueprintTree } from "@/app/(regx)/dossier-blueprints/blueprint-tree";
import {
  ActiveMeaningNote,
  ArchivedBadge,
  RequiredBadge,
  VersionStatusBadge,
} from "@/app/(regx)/dossier-blueprints/status-badge";

function section(over: Record<string, unknown> = {}) {
  return {
    public_id: "s1",
    parent_public_id: null,
    section_code: "A",
    title: "Section A",
    description: "",
    sequence: 0,
    required: true,
    default_due_offset_days: null,
    is_retired: false,
    ...over,
  };
}

const OUTLINE = [
  section({ public_id: "a", section_code: "A", sequence: 0 }),
  section({ public_id: "a1", section_code: "A.1", parent_public_id: "a", sequence: 0 }),
  section({
    public_id: "a2",
    section_code: "A.2",
    parent_public_id: "a",
    sequence: 10,
    required: false,
  }),
  section({ public_id: "b", section_code: "B", sequence: 10 }),
  section({ public_id: "b1", section_code: "B.1", parent_public_id: "b", sequence: 0 }),
];

// ---------------------------------------------------------------------------
// The shared tree builder
// ---------------------------------------------------------------------------
describe("buildTreeRows — the algorithm shared with the dossier tree", () => {
  it("flattens depth-first with a depth on each row", () => {
    const rows = buildTreeRows(OUTLINE, new Set());
    expect(rows.map((r) => [r.section.section_code, r.depth])).toEqual([
      ["A", 0],
      ["A.1", 1],
      ["A.2", 1],
      ["B", 0],
      ["B.1", 1],
    ]);
  });

  it("orders siblings by sequence, not by input order", () => {
    const shuffled = [
      section({ public_id: "z", section_code: "Z", sequence: 30 }),
      section({ public_id: "y", section_code: "Y", sequence: 10 }),
      section({ public_id: "x", section_code: "X", sequence: 20 }),
    ];
    const rows = buildTreeRows(shuffled, new Set());
    expect(rows.map((r) => r.section.section_code)).toEqual(["Y", "X", "Z"]);
  });

  it("breaks a sequence tie deterministically rather than by fetch order", () => {
    const tied = [
      section({ public_id: "bbb", section_code: "Second", sequence: 0 }),
      section({ public_id: "aaa", section_code: "First", sequence: 0 }),
    ];
    const once = buildTreeRows(tied, new Set()).map((r) => r.section.section_code);
    const twice = buildTreeRows([...tied].reverse(), new Set()).map(
      (r) => r.section.section_code
    );
    expect(once).toEqual(twice);
  });

  it("collapsing hides descendants without dropping the parent", () => {
    const rows = buildTreeRows(OUTLINE, new Set(["a"]));
    expect(rows.map((r) => r.section.section_code)).toEqual(["A", "B", "B.1"]);
  });

  it("marks which rows have children", () => {
    const rows = buildTreeRows(OUTLINE, new Set());
    const byCode = Object.fromEntries(rows.map((r) => [r.section.section_code, r.hasChildren]));
    expect(byCode["A"]).toBe(true);
    expect(byCode["A.1"]).toBe(false);
  });

  it("treats an orphan as a root instead of silently dropping it", () => {
    // A filtered or partial list must still render everything it was given.
    const orphaned = [section({ public_id: "lonely", section_code: "L", parent_public_id: "gone" })];
    const rows = buildTreeRows(orphaned, new Set());
    expect(rows).toHaveLength(1);
    expect(rows[0]?.depth).toBe(0);
  });
});

// ---------------------------------------------------------------------------
// The tree component
// ---------------------------------------------------------------------------
describe("BlueprintTree", () => {
  it("renders a flat list with indentation rather than nested containers", () => {
    render(<BlueprintTree sections={OUTLINE as never} editable={false} />);
    const rows = screen.getAllByTestId("blueprint-tree-row");
    expect(rows).toHaveLength(5);
    // Every row is a direct child of the single list: depth is a style, not a
    // container, so a 500-section version does not build a 500-deep DOM.
    const list = screen.getByTestId("blueprint-tree-list");
    for (const row of rows) expect(row.parentElement).toBe(list);
  });

  it("exposes tree semantics with levels", () => {
    render(<BlueprintTree sections={OUTLINE as never} editable={false} />);
    const items = screen.getAllByRole("treeitem");
    expect(items[0]).toHaveAttribute("aria-level", "1");
    expect(items[1]).toHaveAttribute("aria-level", "2");
  });

  it("collapses and expands a parent", async () => {
    const user = userEvent.setup();
    render(<BlueprintTree sections={OUTLINE as never} editable={false} />);
    expect(screen.getAllByTestId("blueprint-tree-row")).toHaveLength(5);

    await user.click(screen.getByRole("button", { name: /collapse A$/i }));
    expect(screen.getAllByTestId("blueprint-tree-row")).toHaveLength(3);

    await user.click(screen.getByRole("button", { name: /expand A$/i }));
    expect(screen.getAllByTestId("blueprint-tree-row")).toHaveLength(5);
  });

  it("filters by code or title", async () => {
    const user = userEvent.setup();
    render(<BlueprintTree sections={OUTLINE as never} editable={false} />);
    await user.type(screen.getByTestId("blueprint-tree-search"), "B.1");
    const rows = screen.getAllByTestId("blueprint-tree-row");
    expect(rows).toHaveLength(1);
    expect(rows[0]).toHaveAttribute("data-section-code", "B.1");
  });

  it("shows an empty state when a search matches nothing", async () => {
    const user = userEvent.setup();
    render(<BlueprintTree sections={OUTLINE as never} editable={false} />);
    await user.type(screen.getByTestId("blueprint-tree-search"), "zzzz");
    expect(screen.getByTestId("blueprint-tree-empty")).toBeInTheDocument();
  });

  it("marks required and optional sections in text", () => {
    render(<BlueprintTree sections={OUTLINE as never} editable={false} />);
    const optionalRow = screen
      .getAllByTestId("blueprint-tree-row")
      .find((r) => r.getAttribute("data-section-code") === "A.2")!;
    expect(within(optionalRow).getByTestId("required-badge")).toHaveTextContent("Optional");
  });

  it("offers no editing controls on a read-only version", () => {
    render(<BlueprintTree sections={OUTLINE as never} editable={false} onReorder={vi.fn()} />);
    expect(screen.queryByTestId("move-up")).not.toBeInTheDocument();
    expect(screen.queryByTestId("retire-section")).not.toBeInTheDocument();
  });

  it("offers editing controls on a draft", () => {
    render(
      <BlueprintTree
        sections={OUTLINE as never}
        editable
        onReorder={vi.fn()}
        onRetire={vi.fn()}
      />
    );
    expect(screen.getAllByTestId("move-up").length).toBeGreaterThan(0);
  });

  it("does not offer to remove a section that still has children", () => {
    render(
      <BlueprintTree sections={OUTLINE as never} editable onReorder={vi.fn()} onRetire={vi.fn()} />
    );
    const parentRow = screen
      .getAllByTestId("blueprint-tree-row")
      .find((r) => r.getAttribute("data-section-code") === "A")!;
    const leafRow = screen
      .getAllByTestId("blueprint-tree-row")
      .find((r) => r.getAttribute("data-section-code") === "A.1")!;
    expect(within(parentRow).queryByTestId("retire-section")).not.toBeInTheDocument();
    expect(within(leafRow).getByTestId("retire-section")).toBeInTheDocument();
  });

  it("reports the direction when a row is moved", async () => {
    const user = userEvent.setup();
    const onReorder = vi.fn();
    render(<BlueprintTree sections={OUTLINE as never} editable onReorder={onReorder} />);
    await user.click(screen.getAllByTestId("move-down")[0]!);
    expect(onReorder).toHaveBeenCalledWith(expect.objectContaining({ section_code: "A" }), 1);
  });

  it("shows the due offset as a readable chip only when configured", () => {
    render(
      <BlueprintTree
        sections={
          [
            section({ public_id: "o", section_code: "O", default_due_offset_days: 30 }),
            section({ public_id: "n", section_code: "N", sequence: 10 }),
          ] as never
        }
        editable={false}
      />
    );
    expect(screen.getAllByTestId("offset-chip")).toHaveLength(1);
    expect(screen.getByTestId("offset-chip")).toHaveTextContent("30d");
  });
});

// ---------------------------------------------------------------------------
// Status vocabulary
// ---------------------------------------------------------------------------
describe("Blueprint status badges", () => {
  it("every version status carries a text label, not colour alone", () => {
    for (const status of ["draft", "active", "retired"] as const) {
      const { unmount } = render(<VersionStatusBadge status={status} />);
      const text = screen.getByTestId("version-status-badge").textContent ?? "";
      expect(text.replace(/[●◐○]/g, "").trim().length).toBeGreaterThan(0);
      unmount();
    }
  });

  it("labels active as Active, never Approved", () => {
    render(<VersionStatusBadge status="active" />);
    const text = screen.getByTestId("version-status-badge").textContent ?? "";
    expect(text).toContain("Active");
    expect(text.toLowerCase()).not.toContain("approv");
  });

  it("spells out what Active means so it is not read as an approval", () => {
    render(<ActiveMeaningNote />);
    const note = screen.getByTestId("active-meaning-note").textContent ?? "";
    expect(note).toMatch(/not a regulatory, QA or agency approval/i);
    expect(note).toMatch(/not a validated status/i);
  });

  it("renders required and optional distinctly in text", () => {
    const { unmount } = render(<RequiredBadge required />);
    expect(screen.getByTestId("required-badge")).toHaveTextContent("Required");
    unmount();
    render(<RequiredBadge required={false} />);
    expect(screen.getByTestId("required-badge")).toHaveTextContent("Optional");
  });

  it("renders an archived marker", () => {
    render(<ArchivedBadge />);
    expect(screen.getByTestId("archived-badge")).toHaveTextContent("Archived");
  });
});

// ---------------------------------------------------------------------------
// Provenance projection
// ---------------------------------------------------------------------------
vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    dossierBlueprints: { provenanceForDossier: vi.fn() },
  };
});

describe("BlueprintProvenanceLine", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  async function renderLine(payload: unknown) {
    const { dossierBlueprints } = await import("@/lib/api");
    (dossierBlueprints.provenanceForDossier as ReturnType<typeof vi.fn>).mockResolvedValue(
      payload
    );
    const { BlueprintProvenanceLine } = await import(
      "@/app/(regx)/submission-dossiers/[publicId]/blueprint-provenance"
    );
    render(<BlueprintProvenanceLine tenantSlug="t" dossierPublicId="d" />);
  }

  it("renders nothing for a dossier built by hand", async () => {
    await renderLine({ instantiated_from_blueprint: false });
    expect(screen.queryByTestId("blueprint-provenance")).not.toBeInTheDocument();
  });

  it("names the blueprint when the caller may see it", async () => {
    await renderLine({
      instantiated_from_blueprint: true,
      blueprint_name: "Synthetic outline A",
      version_number: 2,
    });
    const line = await screen.findByTestId("blueprint-provenance");
    expect(line).toHaveTextContent("Synthetic outline A");
    expect(line).toHaveTextContent("version 2");
    expect(line).toHaveAttribute("data-restricted", "false");
  });

  it("keeps the provenance but withholds the name when restricted", async () => {
    await renderLine({
      instantiated_from_blueprint: true,
      version_number: 3,
      restricted: true,
    });
    const line = await screen.findByTestId("blueprint-provenance");
    expect(line).toHaveTextContent(/controlled blueprint/i);
    expect(line).toHaveTextContent("version 3");
    expect(line).toHaveAttribute("data-restricted", "true");
  });

  it("stays silent rather than failing the page when provenance cannot be read", async () => {
    const { dossierBlueprints } = await import("@/lib/api");
    (dossierBlueprints.provenanceForDossier as ReturnType<typeof vi.fn>).mockRejectedValue(
      new Error("nope")
    );
    const { BlueprintProvenanceLine } = await import(
      "@/app/(regx)/submission-dossiers/[publicId]/blueprint-provenance"
    );
    render(<BlueprintProvenanceLine tenantSlug="t" dossierPublicId="d" />);
    expect(screen.queryByTestId("blueprint-provenance")).not.toBeInTheDocument();
  });
});
