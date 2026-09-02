"use client";

import type {
  UpgradeChangeType,
  UpgradeItemStatus,
  UpgradePlanStatus,
} from "@/lib/api";

/*
 * Change type and status are never communicated by colour alone: every badge
 * carries a text label and a distinct glyph, so a reviewer with a colour-vision
 * deficiency can still read a diff of 200 rows.
 *
 * Nothing here is green. A plan reaching READY means it has been reviewed
 * internally and may be applied -- an approval-coloured badge would imply a
 * regulatory, QA or agency decision the platform never makes, and there is
 * deliberately no APPROVED state to render.
 *
 * Contrast is measured, not assumed: Milestone 9 shipped two badges at 3.70:1
 * and 4.35:1 because axe cannot resolve a pill that paints its own background
 * inline. Every pair below is >= 4.5:1 and pinned by a computed test.
 */

const CHANGE_STYLES: Record<
  UpgradeChangeType,
  { bg: string; fg: string; label: string; mark: string }
> = {
  add_section: { bg: "#eaf2fd", fg: "#045e8f", label: "Added", mark: "+" },
  retire_section: { bg: "#fdf6e6", fg: "#8a5a10", label: "Proposed retirement", mark: "−" },
  update_title: { bg: "#e4ecf7", fg: "#314155", label: "Changed", mark: "~" },
  update_description: { bg: "#e4ecf7", fg: "#314155", label: "Changed", mark: "~" },
  update_required: { bg: "#e4ecf7", fg: "#314155", label: "Changed", mark: "~" },
  update_due_offset: { bg: "#e4ecf7", fg: "#314155", label: "Changed", mark: "~" },
  move_section: { bg: "#e4ecf7", fg: "#314155", label: "Moved", mark: "→" },
  reorder_section: { bg: "#e4ecf7", fg: "#314155", label: "Reordered", mark: "↕" },
  no_change: { bg: "#f4f8fe", fg: "#556275", label: "No change", mark: "=" },
  conflict: { bg: "#fdf3f2", fg: "#8f2c20", label: "Conflict", mark: "!" },
};

const ITEM_STYLES: Record<
  UpgradeItemStatus,
  { bg: string; fg: string; label: string; mark: string }
> = {
  proposed: { bg: "#f4f8fe", fg: "#556275", label: "Not reviewed", mark: "○" },
  accepted: { bg: "#eaf2fd", fg: "#045e8f", label: "Accepted", mark: "●" },
  rejected: { bg: "#dce7f4", fg: "#556275", label: "Rejected", mark: "×" },
  blocked: { bg: "#fdf3f2", fg: "#8f2c20", label: "Blocked", mark: "!" },
  applied: { bg: "#eaf2fd", fg: "#045e8f", label: "Applied", mark: "✓" },
};

const PLAN_STYLES: Record<
  UpgradePlanStatus,
  { bg: string; fg: string; label: string; mark: string }
> = {
  draft: { bg: "#fdf6e6", fg: "#8a5a10", label: "Draft", mark: "◐" },
  ready: { bg: "#eaf2fd", fg: "#045e8f", label: "Ready to apply", mark: "●" },
  applied: { bg: "#e4ecf7", fg: "#314155", label: "Applied", mark: "✓" },
  cancelled: { bg: "#dce7f4", fg: "#556275", label: "Cancelled", mark: "○" },
};

/**
 * Coarse enumerated reasons, rendered as sentences a reviewer can act on. The
 * API never sends prose here -- it sends a code -- so the mapping lives in the
 * UI where it can be worded for a human.
 */
const BLOCK_REASONS: Record<string, string> = {
  has_active_children: "This section still has child sections.",
  has_open_blockers: "This section has an open blocker.",
  has_resource_links: "This section has linked documents, workflows or checklists.",
  has_recorded_progress: "Someone has recorded work on this section.",
  ambiguous_section_code: "A section with this code was added by hand — which one is meant?",
  target_parent_unavailable: "The parent it would move under is not in this dossier.",
  duplicate_section_code: "That section code already exists in this dossier.",
};

const pill: React.CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  gap: 5,
  border: "1px solid rgba(0, 31, 69, 0.12)",
  borderRadius: 999,
  padding: "0.12rem 0.55rem",
  fontSize: "0.8rem",
  fontWeight: 600,
  whiteSpace: "nowrap",
};

export function ChangeTypeBadge({ changeType }: { changeType: UpgradeChangeType }) {
  const s = CHANGE_STYLES[changeType] ?? CHANGE_STYLES.no_change;
  return (
    <span
      data-testid="change-type-badge"
      data-change-type={changeType}
      style={{ ...pill, background: s.bg, color: s.fg }}
    >
      {/* Decorative: the label beside it carries the meaning. */}
      <span aria-hidden="true">{s.mark}</span>
      {s.label}
    </span>
  );
}

export function ItemStatusBadge({ status }: { status: UpgradeItemStatus }) {
  const s = ITEM_STYLES[status] ?? ITEM_STYLES.proposed;
  return (
    <span
      data-testid="item-status-badge"
      data-status={status}
      style={{ ...pill, background: s.bg, color: s.fg }}
    >
      <span aria-hidden="true">{s.mark}</span>
      {s.label}
    </span>
  );
}

export function PlanStatusBadge({ status }: { status: UpgradePlanStatus }) {
  const s = PLAN_STYLES[status] ?? PLAN_STYLES.draft;
  return (
    <span
      data-testid="plan-status-badge"
      data-status={status}
      style={{ ...pill, background: s.bg, color: s.fg }}
    >
      <span aria-hidden="true">{s.mark}</span>
      {s.label}
    </span>
  );
}

export function BlockingReason({ reason }: { reason: string }) {
  if (!reason) return null;
  return (
    <span data-testid="blocking-reason" style={{ fontSize: "0.8rem", color: "#8f2c20" }}>
      {BLOCK_REASONS[reason] ?? "This change needs manual review."}
    </span>
  );
}

/**
 * The one place the vocabulary is spelled out, shown wherever a plan status is.
 * Cheap to render, and the only thing standing between "Ready to apply" and
 * someone reading it as an approval.
 */
export function ReadyMeaningNote() {
  return (
    <p
      data-testid="ready-meaning-note"
      style={{ margin: 0, fontSize: "0.82rem", color: "#66768b", lineHeight: 1.6 }}
    >
      <strong>Ready to apply</strong> means this plan has been reviewed inside RegX. It is not a
      regulatory, QA or agency approval, and applying it changes only the sections you accepted.
    </p>
  );
}
