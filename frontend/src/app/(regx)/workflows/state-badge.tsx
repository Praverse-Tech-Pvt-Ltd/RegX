"use client";

import type { WorkflowState } from "@/lib/api";

const STATE_STYLES: Record<WorkflowState, { bg: string; fg: string; label: string }> = {
  draft: { bg: "#f1f5f9", fg: "#334155", label: "Draft" },
  submitted: { bg: "#e0f2fe", fg: "#075985", label: "Submitted" },
  in_review: { bg: "#fef3c7", fg: "#92400e", label: "In Review" },
  approved: { bg: "#dcfce7", fg: "#166534", label: "Approved" },
  rejected: { bg: "#fee2e2", fg: "#991b1b", label: "Rejected" },
  cancelled: { bg: "#e5e7eb", fg: "#4b5563", label: "Cancelled" },
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
