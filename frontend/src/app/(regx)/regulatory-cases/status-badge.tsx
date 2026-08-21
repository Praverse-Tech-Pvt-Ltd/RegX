"use client";

import type { CaseStatus } from "@/lib/api";

/*
 * Case status is operational, not an approval outcome, and the palette says so:
 * nothing here is green. An approved-looking badge on a COMPLETED case would
 * imply an agency decision the platform never makes.
 *
 * `open` carries a deeper fill than the page surface (--panel #f4f8fe) on
 * purpose -- filled with the surface colour it disappears, which is exactly the
 * defect the workflow Draft badge had.
 */
const STATUS_STYLES: Record<CaseStatus, { bg: string; fg: string; label: string }> = {
  open: { bg: "#e4ecf7", fg: "#314155", label: "Open" },
  on_hold: { bg: "#fdf6e6", fg: "#8a5a10", label: "On hold" },
  completed: { bg: "#eaf2fd", fg: "#045e8f", label: "Completed" },
  cancelled: { bg: "#dce7f4", fg: "#66768b", label: "Cancelled" },
};

export function CaseStatusBadge({ status }: { status: CaseStatus }) {
  const style = STATUS_STYLES[status] ?? STATUS_STYLES.open;
  return (
    <span
      data-testid="case-status-badge"
      data-status={status}
      style={{
        background: style.bg,
        color: style.fg,
        // Outlined, so no state depends on its fill contrasting with whatever
        // surface it sits on.
        border: "1px solid rgba(0, 31, 69, 0.12)",
        borderRadius: 999,
        padding: "0.15rem 0.6rem",
        fontSize: "0.85rem",
        fontWeight: 600,
        whiteSpace: "nowrap",
      }}
    >
      {style.label}
    </span>
  );
}
