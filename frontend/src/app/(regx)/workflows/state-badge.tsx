"use client";

import type { WorkflowState } from "@/lib/api";

const STATE_STYLES: Record<WorkflowState, { bg: string; fg: string; label: string }> = {
  draft: { bg: "#f4f8fe", fg: "#314155", label: "Draft" },
  submitted: { bg: "#eaf2fd", fg: "#045e8f", label: "Submitted" },
  in_review: { bg: "#fdf6e6", fg: "#8a5a10", label: "In Review" },
  approved: { bg: "#eaf7f0", fg: "#1a6b46", label: "Approved" },
  rejected: { bg: "#fdf3f2", fg: "#8f2c20", label: "Rejected" },
  cancelled: { bg: "#dce7f4", fg: "#66768b", label: "Cancelled" },
};

export function StateBadge({ state }: { state: WorkflowState }) {
  const style = STATE_STYLES[state] ?? STATE_STYLES.draft;
  return (
    <span
      data-testid="workflow-state-badge"
      data-state={state}
      style={{
        background: style.bg,
        color: style.fg,
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
