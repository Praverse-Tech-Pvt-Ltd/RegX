"use client";

/**
 * Shared pieces for the submission package screens.
 *
 * Two rules run through all of them:
 *   - **Frozen is an internal RegX state.** The copy says so wherever the word
 *     appears, because "frozen" next to a checksum reads like a certification
 *     to anyone who has not read the docs.
 *   - **A restricted document is `null`, and reads "Unavailable".** Never a
 *     blank cell and never a placeholder that looks like data.
 */

import type { PackageStatus } from "@/lib/api";

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

/** Every pairing is asserted at >= 4.5:1 by a computed contrast test, because
 *  axe cannot resolve an inline background against a parent's ground -- M9
 *  shipped two real AA failures behind exactly that silence. */
const STATUS_STYLE: Record<PackageStatus, { bg: string; fg: string; label: string }> = {
  draft: { bg: "#eef1f5", fg: "#495a6e", label: "Draft" },
  in_review: { bg: "#eaf2fd", fg: "#0b4a76", label: "In review" },
  frozen: { bg: "#e6f4ea", fg: "#1b5e34", label: "Frozen" },
  cancelled: { bg: "#fdecec", fg: "#8c1d1d", label: "Cancelled" },
};

export function PackageStatusBadge({ status }: { status: PackageStatus }) {
  const style = STATUS_STYLE[status] ?? STATUS_STYLE.draft;
  return (
    <span
      data-testid="package-status-badge"
      data-status={status}
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

const SCAN_STYLE: Record<string, { bg: string; fg: string; label: string }> = {
  clean: { bg: "#e6f4ea", fg: "#1b5e34", label: "Scan cleared" },
  pending: { bg: "#fdf0e3", fg: "#8a4b06", label: "Scan pending" },
  quarantined: { bg: "#fdecec", fg: "#8c1d1d", label: "Quarantined" },
  infected: { bg: "#fdecec", fg: "#8c1d1d", label: "Infected" },
  scan_failed: { bg: "#fdf0e3", fg: "#8a4b06", label: "Scan failed" },
  scanner_unavailable: { bg: "#fdf0e3", fg: "#8a4b06", label: "Scanner unavailable" },
};

export function ScanStatusBadge({ status }: { status: string }) {
  const style = SCAN_STYLE[status] ?? {
    bg: "#eef1f5",
    fg: "#495a6e",
    label: status.replace(/_/g, " "),
  };
  return (
    <span
      data-testid="scan-status-badge"
      data-status={status}
      style={{
        display: "inline-block",
        padding: "0.1rem 0.4rem",
        borderRadius: "0.25rem",
        fontSize: "0.72rem",
        fontWeight: 600,
        backgroundColor: style.bg,
        color: style.fg,
      }}
    >
      {style.label}
    </span>
  );
}

/** Integrity reason codes map to copy here, never on the server: a generated
 *  sentence would carry document detail the projection withholds. */
const ISSUE_COPY: Record<string, string> = {
  no_active_entries: "The package has no entries",
  document_version_unavailable: "A cited document version is not available",
  scan_not_cleared: "A cited document version is not scan-cleared",
  checksum_missing: "A cited document version has no checksum",
  duplicate_path: "Two entries would export to the same path",
  tenant_mismatch: "An entry does not belong to this tenant",
  case_mismatch: "A dossier section belongs to a different case",
  section_retired: "A linked dossier section has been retired",
  storage_unavailable: "A cited file is missing from storage",
  too_many_entries: "The package exceeds the export entry limit",
  too_large: "The package exceeds the export size limit",
};

export function issueLabel(code: string): string {
  return ISSUE_COPY[code] ?? code.replace(/_/g, " ");
}

/** The single rendering of "you may not know". Never blank, never a dash. */
export function Unavailable({ testId = "unavailable" }: { testId?: string }) {
  return (
    <span data-testid={testId} style={{ color: T.muted, fontSize: "0.8rem" }}>
      Unavailable
    </span>
  );
}

export function Checksum({ value, testId }: { value: string; testId?: string }) {
  if (!value) return <Unavailable testId={testId} />;
  return (
    <code
      data-testid={testId ?? "checksum"}
      title={value}
      style={{
        fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
        fontSize: "0.75rem",
        color: T.text,
        backgroundColor: T.panel,
        padding: "0.05rem 0.3rem",
        borderRadius: "0.2rem",
      }}
    >
      {value.slice(0, 12)}…
    </code>
  );
}

/** Pinned copy, asserted verbatim in the test suite. */
export const FROZEN_MEANS_NOTE =
  "Frozen is an internal RegX package state. It records that this manifest and " +
  "these exact document versions can no longer change. It is not regulatory " +
  "approval, QA approval or agency acceptance.";

export const FREEZE_CONFIRM_NOTE =
  "Freezing locks this internal package manifest and the exact document " +
  "versions it names. Future document uploads will not change it, and a frozen " +
  "package cannot be reopened — you would clone it into a new draft instead.";

export function FrozenMeansNote() {
  return (
    <p
      data-testid="frozen-means-note"
      style={{ fontSize: "0.78rem", color: T.muted, margin: "0.35rem 0 0", maxWidth: "62ch" }}
    >
      {FROZEN_MEANS_NOTE}
    </p>
  );
}
