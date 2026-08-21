"use client";

import type { DossierStatus, Readiness, SectionStatus } from "@/lib/api";

/*
 * Readiness is never communicated by colour alone: every badge carries a text
 * label, and the icon glyph differs per state. A reviewer scanning a 500-row
 * outline with a colour-vision deficiency must still be able to tell READY from
 * NOT READY.
 *
 * Nothing here is green. READY means *internally* ready against configured RegX
 * criteria -- an approval-coloured badge would imply an agency decision the
 * platform never makes.
 */
const READINESS_STYLES: Record<Readiness, { bg: string; fg: string; label: string; mark: string }> =
  {
    ready: { bg: "#eaf2fd", fg: "#045e8f", label: "Ready", mark: "●" },
    partially_ready: { bg: "#fdf6e6", fg: "#8a5a10", label: "Partially ready", mark: "◐" },
    not_ready: { bg: "#e4ecf7", fg: "#314155", label: "Not ready", mark: "○" },
    // Not `--muted #66768b`: on `--line #dce7f4` that measures 3.70:1, which
    // fails WCAG AA for this pill's 0.8rem text. `#556275` is the nearest tone
    // on the same muted->text axis that clears 4.5:1 (4.95:1), so the badge
    // still reads as de-emphasised without being unreadable.
    not_applicable: { bg: "#dce7f4", fg: "#556275", label: "N/A", mark: "–" },
  };

const SECTION_STATUS_LABELS: Record<SectionStatus, string> = {
  not_started: "Not started",
  in_progress: "In progress",
  blocked: "Blocked",
  complete: "Complete",
  not_applicable: "Not applicable",
};

const DOSSIER_STATUS_STYLES: Record<DossierStatus, { bg: string; fg: string; label: string }> = {
  open: { bg: "#e4ecf7", fg: "#314155", label: "Open" },
  on_hold: { bg: "#fdf6e6", fg: "#8a5a10", label: "On hold" },
  completed: { bg: "#eaf2fd", fg: "#045e8f", label: "Completed" },
  cancelled: { bg: "#dce7f4", fg: "#556275", label: "Cancelled" },
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

export function ReadinessBadge({ readiness }: { readiness: Readiness }) {
  const s = READINESS_STYLES[readiness] ?? READINESS_STYLES.not_ready;
  return (
    <span
      data-testid="readiness-badge"
      data-readiness={readiness}
      style={{ ...pill, background: s.bg, color: s.fg }}
    >
      {/* Decorative: the label beside it carries the meaning. */}
      <span aria-hidden="true">{s.mark}</span>
      {s.label}
    </span>
  );
}

export function SectionStatusBadge({ status }: { status: SectionStatus }) {
  return (
    <span
      data-testid="section-status-badge"
      data-status={status}
      // `--muted #66768b` on `--panel #f4f8fe` is 4.35:1 -- just under AA for
      // this size. Same substitution as the N/A pill above.
      style={{ ...pill, background: "#f4f8fe", color: "#556275", borderColor: "#dce7f4" }}
    >
      {SECTION_STATUS_LABELS[status] ?? status}
    </span>
  );
}

export function DossierStatusBadge({ status }: { status: DossierStatus }) {
  const s = DOSSIER_STATUS_STYLES[status] ?? DOSSIER_STATUS_STYLES.open;
  return (
    <span
      data-testid="dossier-status-badge"
      data-status={status}
      style={{ ...pill, background: s.bg, color: s.fg }}
    >
      {s.label}
    </span>
  );
}

export function BlockerIndicator({ count }: { count: number }) {
  if (count === 0) return null;
  return (
    <span
      data-testid="blocker-indicator"
      title={`${count} open blocker${count === 1 ? "" : "s"}`}
      style={{
        ...pill,
        background: "#fdf3f2",
        color: "#8f2c20",
        borderColor: "#f3c9c4",
      }}
    >
      <span aria-hidden="true">!</span>
      {count} blocker{count === 1 ? "" : "s"}
    </span>
  );
}
