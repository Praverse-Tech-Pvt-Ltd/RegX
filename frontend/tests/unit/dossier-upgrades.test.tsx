import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import {
  BlockingReason,
  ChangeTypeBadge,
  ItemStatusBadge,
  PlanStatusBadge,
  ReadyMeaningNote,
} from "@/app/(regx)/submission-dossiers/[publicId]/upgrade-badges";

// ---------------------------------------------------------------------------
// Vocabulary and accessibility of the diff labels
// ---------------------------------------------------------------------------
describe("Upgrade badges", () => {
  const CHANGE_TYPES = [
    "add_section",
    "retire_section",
    "update_title",
    "update_description",
    "update_required",
    "move_section",
    "reorder_section",
    "update_due_offset",
    "no_change",
    "conflict",
  ] as const;

  it("every change type carries a text label, not colour alone", () => {
    for (const changeType of CHANGE_TYPES) {
      const { unmount } = render(<ChangeTypeBadge changeType={changeType} />);
      const text = screen.getByTestId("change-type-badge").textContent ?? "";
      // Strip the decorative glyph: what remains must still say what it means.
      expect(text.replace(/[+\-~→↕=!]/g, "").trim().length).toBeGreaterThan(0);
      unmount();
    }
  });

  it("uses the labels a reviewer expects", () => {
    const cases: Array<[(typeof CHANGE_TYPES)[number], RegExp]> = [
      ["add_section", /Added/],
      ["retire_section", /Proposed retirement/],
      ["update_title", /Changed/],
      ["move_section", /Moved/],
      ["reorder_section", /Reordered/],
      ["conflict", /Conflict/],
      ["no_change", /No change/],
    ];
    for (const [changeType, pattern] of cases) {
      const { unmount } = render(<ChangeTypeBadge changeType={changeType} />);
      expect(screen.getByTestId("change-type-badge")).toHaveTextContent(pattern);
      unmount();
    }
  });

  it("never labels a proposed retirement as a deletion", () => {
    render(<ChangeTypeBadge changeType="retire_section" />);
    const text = screen.getByTestId("change-type-badge").textContent ?? "";
    expect(text.toLowerCase()).not.toContain("delet");
    expect(text.toLowerCase()).not.toContain("remov");
  });

  it("every item status carries a text label", () => {
    for (const status of ["proposed", "accepted", "rejected", "blocked", "applied"] as const) {
      const { unmount } = render(<ItemStatusBadge status={status} />);
      const text = screen.getByTestId("item-status-badge").textContent ?? "";
      expect(text.replace(/[○●×!✓]/g, "").trim().length).toBeGreaterThan(0);
      unmount();
    }
  });

  it("every plan status carries a text label and none says Approved", () => {
    for (const status of ["draft", "ready", "applied", "cancelled"] as const) {
      const { unmount } = render(<PlanStatusBadge status={status} />);
      const text = screen.getByTestId("plan-status-badge").textContent ?? "";
      expect(text.replace(/[◐●✓○]/g, "").trim().length).toBeGreaterThan(0);
      expect(text.toLowerCase()).not.toContain("approv");
      unmount();
    }
  });

  it("spells out what Ready means so it is not read as an approval", () => {
    render(<ReadyMeaningNote />);
    const note = screen.getByTestId("ready-meaning-note").textContent ?? "";
    expect(note).toMatch(/not a regulatory, QA or agency approval/i);
    expect(note).toMatch(/only the sections you accepted/i);
  });

  it("turns a coarse blocking code into a sentence a reviewer can act on", () => {
    const cases: Array<[string, RegExp]> = [
      ["has_open_blockers", /open blocker/i],
      ["has_resource_links", /linked documents/i],
      ["has_recorded_progress", /recorded work/i],
      ["has_active_children", /child sections/i],
      ["ambiguous_section_code", /added by hand/i],
      ["target_parent_unavailable", /not in this dossier/i],
    ];
    for (const [code, pattern] of cases) {
      const { unmount } = render(<BlockingReason reason={code} />);
      expect(screen.getByTestId("blocking-reason")).toHaveTextContent(pattern);
      unmount();
    }
  });

  it("falls back to a safe sentence for an unknown code rather than showing the raw code", () => {
    render(<BlockingReason reason="something_new_from_the_backend" />);
    const text = screen.getByTestId("blocking-reason").textContent ?? "";
    expect(text).toMatch(/manual review/i);
    expect(text).not.toContain("something_new_from_the_backend");
  });

  it("renders nothing when there is no blocking reason", () => {
    const { container } = render(<BlockingReason reason="" />);
    expect(container).toBeEmptyDOMElement();
  });
});

// ---------------------------------------------------------------------------
// The panel
// ---------------------------------------------------------------------------
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
    dossierUpgrades: {
      listForDossier: vi.fn(),
      get: vi.fn(),
      generate: vi.fn(),
      regenerate: vi.fn(),
      acceptItem: vi.fn(),
      rejectItem: vi.fn(),
      markReady: vi.fn(),
      apply: vi.fn(),
      cancel: vi.fn(),
    },
  };
});

const PERMS = {
  can_view: true,
  can_generate: true,
  can_review: true,
  can_apply: true,
  can_cancel: true,
};

function item(over: Record<string, unknown> = {}) {
  return {
    public_id: "item-1",
    change_type: "update_title",
    status: "proposed",
    section_code: "A",
    field_name: "title",
    before_value: "Section A",
    after_value: "Section A, revised",
    blocking_reason: "",
    requires_manual_review: false,
    dossier_section_public_id: "sec-a",
    target_section_public_id: "bp-a",
    sequence: 0,
    ...over,
  };
}

function plan(over: Record<string, unknown> = {}) {
  return {
    public_id: "plan-1",
    dossier_public_id: "dossier-1",
    status: "draft",
    notes: "",
    is_stale: false,
    source_version: { public_id: "v1", version_number: 1, status: "retired" },
    target_version: { public_id: "v2", version_number: 2, status: "active" },
    total_items: 1,
    actionable_items: 1,
    conflict_items: 0,
    accepted_items: 0,
    rejected_items: 0,
    blocked_items: 0,
    created_by: { public_id: "u1", full_name: "Author" },
    created_at: "2026-01-01T00:00:00Z",
    reviewed_at: null,
    applied_at: null,
    cancelled_at: null,
    ...over,
  };
}

// The mock above is an explicit allow-list, so name its keys explicitly too: a
// mapped type over a literal union keeps every entry required, where a string
// index signature would hand back `T | undefined` under noUncheckedIndexedAccess
// and quietly let a renamed client method typecheck as an absent mock.
type UpgradeMocks = Record<keyof typeof import("@/lib/api")["dossierUpgrades"], ReturnType<typeof vi.fn>>;

async function mount(listOver: Record<string, unknown> = {}, detailOver: Record<string, unknown> = {}) {
  const { dossierUpgrades } = await import("@/lib/api");
  const mocks = dossierUpgrades as unknown as UpgradeMocks;
  mocks.listForDossier.mockResolvedValue({
    results: [],
    current_version: { public_id: "v1", version_number: 1, status: "retired" },
    available_targets: [{ public_id: "v2", version_number: 2, status: "active" }],
    permissions: PERMS,
    ...listOver,
  });
  mocks.get.mockResolvedValue({ ...plan(), items: [item()], permissions: PERMS, ...detailOver });

  const { UpgradePanel } = await import(
    "@/app/(regx)/submission-dossiers/[publicId]/upgrade-panel"
  );
  render(
    <UpgradePanel tenantSlug="t" dossierPublicId="dossier-1" dossierTerminal={false} />
  );
  return mocks;
}

describe("UpgradePanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("states that a newer version never changes the dossier on its own", async () => {
    await mount();
    expect(await screen.findByTestId("tab-panel-upgrade")).toHaveTextContent(
      /never changes this dossier on its own/i
    );
  });

  it("shows the dossier's current version", async () => {
    await mount();
    expect(await screen.findByTestId("current-version")).toHaveTextContent("version 1");
  });

  it("offers a comparison when a newer version exists and no plan is open", async () => {
    await mount({ results: [] });
    expect(await screen.findByTestId("generate-plan")).toBeInTheDocument();
  });

  it("says so when there is nothing newer to compare against", async () => {
    await mount({ available_targets: [] });
    expect(await screen.findByTestId("no-targets")).toBeInTheDocument();
    expect(screen.queryByTestId("generate-plan")).not.toBeInTheDocument();
  });

  it("renders one diff row per proposed change with before and after", async () => {
    await mount({ results: [plan()] });
    const row = await screen.findByTestId("upgrade-row");
    expect(within(row).getByTestId("change-type-badge")).toHaveTextContent(/Changed/);
    expect(row).toHaveTextContent("Section A");
    expect(row).toHaveTextContent("Section A, revised");
  });

  it("offers accept and reject on a draft plan", async () => {
    await mount({ results: [plan()] });
    expect(await screen.findByTestId("accept-item")).toBeInTheDocument();
    expect(screen.getByTestId("reject-item")).toBeInTheDocument();
  });

  it("does not offer accept or reject on a blocked item", async () => {
    await mount(
      { results: [plan({ blocked_items: 1 })] },
      { items: [item({ status: "blocked", blocking_reason: "has_open_blockers" })] }
    );
    await screen.findByTestId("upgrade-row");
    expect(screen.queryByTestId("accept-item")).not.toBeInTheDocument();
    expect(screen.getByTestId("blocking-reason")).toHaveTextContent(/open blocker/i);
  });

  it("does not offer review controls to a caller the API says cannot review", async () => {
    await mount(
      { results: [plan()], permissions: { ...PERMS, can_review: false } },
      { permissions: { ...PERMS, can_review: false } }
    );
    await screen.findByTestId("upgrade-row");
    expect(screen.queryByTestId("accept-item")).not.toBeInTheDocument();
    expect(screen.queryByTestId("mark-ready")).not.toBeInTheDocument();
  });

  it("does not offer apply to a caller the API says cannot apply", async () => {
    await mount(
      { results: [plan({ status: "ready" })], permissions: { ...PERMS, can_apply: false } },
      { status: "ready", permissions: { ...PERMS, can_apply: false } }
    );
    await screen.findByTestId("open-plan");
    expect(screen.queryByTestId("apply-plan")).not.toBeInTheDocument();
  });

  it("does not offer apply while the plan is still a draft", async () => {
    await mount({ results: [plan()] });
    await screen.findByTestId("open-plan");
    expect(screen.queryByTestId("apply-plan")).not.toBeInTheDocument();
    expect(screen.getByTestId("mark-ready")).toBeInTheDocument();
  });

  it("warns that a stale plan must be regenerated", async () => {
    await mount({ results: [plan({ is_stale: true })] }, { is_stale: true });
    expect(await screen.findByTestId("plan-stale")).toHaveTextContent(/Regenerate before applying/i);
  });

  it("requires an explicit confirmation before applying", async () => {
    const user = userEvent.setup();
    const mocks = await mount(
      { results: [plan({ status: "ready", accepted_items: 1 })] },
      { status: "ready", accepted_items: 1 }
    );

    await user.click(await screen.findByTestId("apply-plan"));
    // The first click only asks. Nothing has been sent.
    expect(screen.getByTestId("apply-confirm")).toBeInTheDocument();
    expect(mocks.apply).not.toHaveBeenCalled();

    await user.click(screen.getByTestId("apply-confirm-no"));
    expect(mocks.apply).not.toHaveBeenCalled();
  });

  it("applies only after the confirmation is accepted, and reports what changed", async () => {
    const user = userEvent.setup();
    const mocks = await mount(
      { results: [plan({ status: "ready", accepted_items: 1 })] },
      { status: "ready", accepted_items: 1 }
    );
    mocks.apply.mockResolvedValue({
      public_id: "app-1",
      plan_public_id: "plan-1",
      dossier_public_id: "dossier-1",
      source_version_number: 1,
      target_version_number: 2,
      sections_added: 2,
      sections_retired: 1,
      sections_updated: 3,
      dossier_route: "/submission-dossiers/dossier-1",
    });

    await user.click(await screen.findByTestId("apply-plan"));
    await user.click(screen.getByTestId("apply-confirm-yes"));

    await waitFor(() => expect(mocks.apply).toHaveBeenCalledWith("t", "plan-1"));
    expect(await screen.findByTestId("upgrade-applied")).toHaveTextContent(
      "2 added, 3 updated, 1 retired"
    );
  });

  it("accepting an item calls only the accept endpoint, never apply", async () => {
    const user = userEvent.setup();
    const mocks = await mount({ results: [plan()] });
    mocks.acceptItem.mockResolvedValue(item({ status: "accepted" }));

    await user.click(await screen.findByTestId("accept-item"));
    await waitFor(() =>
      expect(mocks.acceptItem).toHaveBeenCalledWith("t", "plan-1", "item-1")
    );
    expect(mocks.apply).not.toHaveBeenCalled();
  });

  it("hides the no-change rows from the diff", async () => {
    await mount({ results: [plan()] }, { items: [item({ change_type: "no_change" })] });
    expect(await screen.findByTestId("no-differences")).toBeInTheDocument();
    expect(screen.queryByTestId("upgrade-row")).not.toBeInTheDocument();
  });

  it("surfaces a refused action as a readable message", async () => {
    const user = userEvent.setup();
    const { ApiError } = await import("@/lib/api");
    const mocks = await mount({ results: [plan()] });
    mocks.acceptItem.mockRejectedValue(new ApiError(409, "nope"));

    await user.click(await screen.findByTestId("accept-item"));
    expect(await screen.findByTestId("upgrade-error")).toHaveTextContent(
      /cannot be accepted/i
    );
  });
});
