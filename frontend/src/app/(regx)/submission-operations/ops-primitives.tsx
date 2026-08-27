"use client";

/**
 * Shared pieces for the operations dashboard.
 *
 * The whole screen turns on one distinction: `null` means *you are not entitled
 * to know*, `0` means *there are none*. `SummaryCard` takes `number | null` and
 * renders "Unavailable" for null -- it is not possible to pass a restricted
 * dimension and get a zero, because the only path to a number is a number.
 *
 * Severity never travels as colour alone. Every badge carries a word, and the
 * words are operational -- Blocked, Overdue, Needs attention -- rather than
 * borrowed regulatory vocabulary that already means something specific to the
 * people reading this screen.
 */

import Link from "next/link";
import type { AttentionSeverity } from "@/lib/api";

export const T = {
  ink: "#001f45",
  text: "#314155",
  muted: "#66768b",
  line: "#dce7f4",
  soft: "#eaf2fd",
  panel: "#f4f8fe",
  blue: "#045e8f",
  navy: "#003865",
};

/** Every pairing below is computed against its own background and asserted at
 *  >= 4.5:1 in the accessibility suite. Milestone 9 shipped two AA failures
 *  that axe could not see, because an inline background has no pair to measure. */
const SEVERITY_STYLE: Record<AttentionSeverity, { bg: string; fg: string; label: string }> = {
  blocked: { bg: "#fdecec", fg: "#8c1d1d", label: "Blocked" },
  overdue: { bg: "#fdf0e3", fg: "#8a4b06", label: "Overdue" },
  attention: { bg: "#eaf2fd", fg: "#0b4a76", label: "Needs attention" },
  informational: { bg: "#eef1f5", fg: "#495a6e", label: "Informational" },
};

export function SeverityBadge({ severity }: { severity: AttentionSeverity }) {
  const style = SEVERITY_STYLE[severity] ?? SEVERITY_STYLE.informational;
  return (
    <span
      data-testid="severity-badge"
      data-severity={severity}
      style={{
        display: "inline-block",
        padding: "0.15rem 0.5rem",
        borderRadius: "999px",
        fontSize: "0.75rem",
        fontWeight: 600,
        backgroundColor: style.bg,
        color: style.fg,
      }}
    >
      {style.label}
    </span>
  );
}

/** Reason codes map to copy here, never on the server. The backend sends an
 *  enum precisely so no sentence about a resource is ever assembled from rows
 *  the caller may not be entitled to. */
const REASON_COPY: Record<string, string> = {
  open_blocker: "Open blocker",
  required_section_blocked: "Required section blocked",
  overdue_required_section: "Required section overdue",
  workflow_rejected: "Workflow rejected",
  due_soon_required_section: "Required section due soon",
  workflow_waiting_review: "Workflow waiting for review",
  required_section_not_started: "Required section not started",
  blocked_upgrade_plan: "Upgrade plan has blocked items",
  stale_upgrade_plan: "Upgrade plan is stale",
  dossier_on_hold: "Case on hold",
  case_with_no_dossier: "Case has no dossier",
};

export function reasonLabel(code: string): string {
  return REASON_COPY[code] ?? code.replace(/_/g, " ");
}

const READINESS_COPY: Record<string, string> = {
  internally_ready: "Internally ready",
  internally_partially_ready: "Internally partially ready",
  internally_not_ready: "Internally not ready",
  no_required_sections: "No required sections",
};

/**
 * Always says "Internally". A badge reading plain "Ready" on an operations
 * screen invites exactly the reading this product must never support, and the
 * word is the cheapest possible guard against it.
 */
export function InternalReadinessBadge({ value }: { value: string | null }) {
  if (value === null) return <Unavailable testId="readiness-unavailable" />;
  const label = READINESS_COPY[value] ?? value.replace(/_/g, " ");
  const ready = value === "internally_ready";
  return (
    <span
      data-testid="internal-readiness"
      data-value={value}
      style={{
        display: "inline-block",
        padding: "0.15rem 0.5rem",
        borderRadius: "999px",
        fontSize: "0.75rem",
        fontWeight: 600,
        backgroundColor: ready ? "#e6f4ea" : "#eef1f5",
        color: ready ? "#1b5e34" : "#495a6e",
      }}
    >
      {label}
    </span>
  );
}

/** The single rendering of "you may not know". Never a dash, never a zero. */
export function Unavailable({ testId = "unavailable" }: { testId?: string }) {
  return (
    <span data-testid={testId} style={{ color: T.muted, fontSize: "0.8rem" }}>
      Unavailable
    </span>
  );
}

export function SummaryCard({
  label,
  value,
  hint,
  testId,
}: {
  label: string;
  /** `null` is a permission answer, not a missing number. */
  value: number | null;
  hint?: string;
  testId: string;
}) {
  const restricted = value === null;
  return (
    <div
      data-testid={testId}
      data-restricted={restricted ? "true" : "false"}
      style={{
        border: `1px solid ${T.line}`,
        borderRadius: "0.5rem",
        padding: "0.85rem 1rem",
        backgroundColor: "#fff",
        minWidth: "10rem",
      }}
    >
      <div style={{ fontSize: "0.78rem", color: T.muted }}>{label}</div>
      <div style={{ fontSize: "1.6rem", fontWeight: 700, color: T.ink, lineHeight: 1.2 }}>
        {restricted ? (
          <span style={{ fontSize: "0.95rem", fontWeight: 600, color: T.muted }}>
            Unavailable
          </span>
        ) : (
          value
        )}
      </div>
      <div style={{ fontSize: "0.72rem", color: T.muted }}>
        {restricted ? "You do not have permission to view this" : (hint ?? " ")}
      </div>
    </div>
  );
}

/**
 * "Nothing here" and "you may not look here" are different states, and a screen
 * that renders them the same way teaches people the wrong thing about their own
 * data.
 */
export function EmptyState({
  restricted,
  emptyMessage,
  restrictedMessage,
  testId,
}: {
  restricted: boolean;
  emptyMessage: string;
  restrictedMessage: string;
  testId: string;
}) {
  return (
    <p
      data-testid={testId}
      data-restricted={restricted ? "true" : "false"}
      style={{ color: T.muted, fontSize: "0.85rem", padding: "0.75rem 0" }}
    >
      {restricted ? restrictedMessage : emptyMessage}
    </p>
  );
}

/**
 * A link only where the caller can actually follow it. Rendering a link into a
 * module they cannot open would both break and disclose that the target exists.
 */
export function MaybeLink({
  href,
  children,
  testId,
}: {
  href: string | null;
  children: React.ReactNode;
  testId?: string;
}) {
  if (href === null) {
    return <span data-testid={testId}>{children}</span>;
  }
  return (
    <Link href={href} data-testid={testId} style={{ color: T.blue }}>
      {children}
    </Link>
  );
}

/** Pinned copy. Asserted verbatim in the test suite. */
export const INTERNAL_ONLY_NOTE =
  "This dashboard reflects internal RegX operational status only. " +
  "It is not a statement of agency acceptance, regulatory approval, filing " +
  "completeness or submission validity.";

export function InternalOnlyNote() {
  return (
    <p
      data-testid="internal-only-note"
      style={{
        fontSize: "0.78rem",
        color: T.muted,
        margin: "0.35rem 0 0",
        maxWidth: "60ch",
      }}
    >
      {INTERNAL_ONLY_NOTE}
    </p>
  );
}
