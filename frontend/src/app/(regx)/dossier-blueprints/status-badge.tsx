"use client";

import type { BlueprintVersionStatus } from "@/lib/api";

/*
 * Status is never communicated by colour alone: every badge carries a text
 * label and a distinct glyph, so a reviewer with a colour-vision deficiency can
 * still tell an editable draft from a published version at a glance.
 *
 * Nothing here is green. ACTIVE means "available for internal RegX dossier
 * instantiation" -- an approval-coloured badge would imply a regulatory, QA or
 * agency decision the platform never makes. There is deliberately no APPROVED
 * state to render.
 *
 * Contrast is measured, not assumed: Milestone 9 shipped two badges at 3.70:1
 * and 4.35:1 because axe cannot resolve a pill that paints its own background
 * inline. Every pair below is >= 4.5:1 and pinned by a computed test.
 */
const VERSION_STYLES: Record<
  BlueprintVersionStatus,
  { bg: string; fg: string; label: string; mark: string }
> = {
  draft: { bg: "#fdf6e6", fg: "#8a5a10", label: "Draft", mark: "◐" },
  active: { bg: "#eaf2fd", fg: "#045e8f", label: "Active", mark: "●" },
  retired: { bg: "#dce7f4", fg: "#556275", label: "Retired", mark: "○" },
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

export function VersionStatusBadge({ status }: { status: BlueprintVersionStatus }) {
  const s = VERSION_STYLES[status] ?? VERSION_STYLES.draft;
  return (
    <span
      data-testid="version-status-badge"
      data-status={status}
      style={{ ...pill, background: s.bg, color: s.fg }}
    >
      {/* Decorative: the label beside it carries the meaning. */}
      <span aria-hidden="true">{s.mark}</span>
      {s.label}
    </span>
  );
}

export function RequiredBadge({ required }: { required: boolean }) {
  return (
    <span
      data-testid="required-badge"
      data-required={required ? "true" : "false"}
      style={{
        ...pill,
        background: required ? "#eaf2fd" : "#f4f8fe",
        color: required ? "#045e8f" : "#556275",
        borderColor: "#dce7f4",
      }}
    >
      {required ? "Required" : "Optional"}
    </span>
  );
}

export function ArchivedBadge() {
  return (
    <span
      data-testid="archived-badge"
      style={{ ...pill, background: "#dce7f4", color: "#556275" }}
    >
      Archived
    </span>
  );
}

/**
 * The one place the vocabulary is spelled out for a reader, shown beside any
 * active version. Cheap to render and the only thing standing between "Active"
 * and someone reading it as an approval.
 */
export function ActiveMeaningNote() {
  return (
    <p
      data-testid="active-meaning-note"
      style={{
        margin: 0,
        fontSize: "0.82rem",
        color: "#66768b",
        lineHeight: 1.6,
      }}
    >
      <strong>Active</strong> means this version is available for creating dossiers inside RegX.
      It is not a regulatory, QA or agency approval, and not a validated status.
    </p>
  );
}
