"use client";

/**
 * Shared pieces for the external integration screens.
 *
 * Three rules run through all of them:
 *   - **ACTIVE is not approval.** The copy says "Enabled", and the page says
 *     what that does and does not mean, because a green badge next to the word
 *     "active" reads like a certification to anyone who has not read the docs.
 *   - **A transfer is not a submission.** The verb is "Transfer", never
 *     "Submit", and never anything naming an agency.
 *   - **No secret is ever rendered.** A credential shows its type and the
 *     *name* of the environment variable an operator must set. There is no
 *     field carrying a value, on the server or here.
 */

import type { ConnectorStatus, ConnectorTestStatus, ExecutionStatus } from "@/lib/api";

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

type Badge = { bg: string; fg: string; label: string };

/** Every pairing is asserted at >= 4.5:1 by a computed contrast test, because
 *  axe cannot resolve an inline background against a parent's ground -- M9
 *  shipped two real AA failures behind exactly that silence. */
const CONNECTOR_STATUS: Record<ConnectorStatus, Badge> = {
  draft: { bg: "#eef1f5", fg: "#495a6e", label: "Draft" },
  active: { bg: "#e6f4ea", fg: "#1b5e34", label: "Enabled" },
  disabled: { bg: "#fdf0e3", fg: "#8a4b06", label: "Disabled" },
  archived: { bg: "#eef1f5", fg: "#495a6e", label: "Archived" },
};

export function ConnectorStatusBadge({ status }: { status: ConnectorStatus }) {
  const style = CONNECTOR_STATUS[status] ?? CONNECTOR_STATUS.draft;
  return (
    <span
      data-testid="connector-status-badge"
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

const TEST_STATUS: Record<ConnectorTestStatus, Badge> = {
  never_tested: { bg: "#eef1f5", fg: "#495a6e", label: "Never tested" },
  reachable: { bg: "#e6f4ea", fg: "#1b5e34", label: "Reachable" },
  unreachable: { bg: "#fdecec", fg: "#8c1d1d", label: "Unreachable" },
  unauthorised: { bg: "#fdf0e3", fg: "#8a4b06", label: "Authentication failed" },
};

export function TestStatusBadge({ status }: { status: ConnectorTestStatus }) {
  const style = TEST_STATUS[status] ?? TEST_STATUS.never_tested;
  return (
    <span
      data-testid="connector-test-badge"
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

const EXECUTION_STATUS: Record<ExecutionStatus, Badge> = {
  queued: { bg: "#eef1f5", fg: "#495a6e", label: "Queued" },
  running: { bg: "#eaf2fd", fg: "#0b4a76", label: "Running" },
  succeeded: { bg: "#e6f4ea", fg: "#1b5e34", label: "Transferred" },
  failed: { bg: "#fdecec", fg: "#8c1d1d", label: "Failed" },
  cancelled: { bg: "#eef1f5", fg: "#495a6e", label: "Cancelled" },
};

export function ExecutionStatusBadge({ status }: { status: ExecutionStatus }) {
  const style = EXECUTION_STATUS[status] ?? EXECUTION_STATUS.queued;
  return (
    <span
      data-testid="execution-status-badge"
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
      {/* Never rendered as colour alone: the label carries the meaning. */}
      {style.label}
    </span>
  );
}

/**
 * Enumerated failure codes mapped to copy here, never on the server.
 *
 * A generated sentence would carry the remote system's own words, which are
 * attacker-influenced text and can name internal hosts.
 */
const ERROR_COPY: Record<string, string> = {
  DNS_BLOCKED: "The destination is not permitted",
  DNS_UNRESOLVED: "The destination host could not be resolved",
  TLS_ERROR: "The TLS connection could not be established",
  CONNECTION_FAILED: "The connection could not be established",
  TIMEOUT: "The endpoint did not respond in time",
  REDIRECT_REFUSED: "The endpoint redirected elsewhere, which is not followed",
  AUTH_FAILED: "Authentication was rejected by the endpoint",
  REMOTE_4XX: "The endpoint rejected the request",
  REMOTE_5XX: "The endpoint reported an error",
  RESPONSE_TOO_LARGE: "The response exceeded the configured size limit",
  METHOD_REJECTED: "That request method is not permitted",
  CREDENTIAL_UNAVAILABLE: "The deployment does not provide this connector's secret",
  CONNECTOR_DISABLED: "The connector was disabled before this ran",
  CONFIGURATION_INVALID: "The stored configuration is no longer valid",
  ATTEMPTS_EXHAUSTED: "The transfer failed after the permitted attempts",
  PACKAGE_NOT_FROZEN: "Only a frozen package can be transferred",
  PACKAGE_INTEGRITY_FAILED: "The package could not be assembled as it was frozen",
  PACKAGE_MISSING: "The package is no longer available",
  DOCUMENT_REJECTED: "The fetched content was rejected by document validation",
  EMPTY_RESPONSE: "The endpoint returned no content",
  PATH_REJECTED: "The requested path is outside the connector's allowed prefix",
  PAYLOAD_INVALID: "The request was not valid for this operation",
  INTERNAL_ERROR: "The transfer failed for an internal reason",
  CANCELLED_BY_USER: "Cancelled before it ran",
  CONFIG_UNKNOWN_FIELD: "That configuration field is not supported",
  CONFIG_MISSING_FIELD: "A required configuration field is missing",
  CONFIG_INVALID_VALUE: "A configuration value is not valid",
  CONFIG_HEADER_REJECTED: "That header may not be configured",
  CONFIG_TLS_REQUIRED: "TLS verification cannot be disabled",
  CONFIG_UNSUPPORTED_TYPE: "That connector type is not supported",
  URL_INVALID: "The URL is not valid",
  SCHEME_REJECTED: "Only https:// destinations are supported",
  CREDENTIALS_IN_URL: "Credentials may not be embedded in a URL",
  PORT_REJECTED: "That port is not permitted",
  HOSTNAME_INVALID: "The URL has no usable host",
};

export function errorLabel(code: string): string {
  if (!code) return "";
  return ERROR_COPY[code] ?? code.replace(/_/g, " ").toLowerCase();
}

const OPERATION_COPY: Record<string, string> = {
  import_document: "Import document",
  push_frozen_package: "Transfer frozen package",
};

export function operationLabel(operation: string): string {
  return OPERATION_COPY[operation] ?? operation.replace(/_/g, " ");
}

/** The single rendering of "there is nothing here", distinct from a failure. */
export function EmptyState({
  title,
  detail,
  testId,
}: {
  title: string;
  detail: string;
  testId: string;
}) {
  return (
    <div
      data-testid={testId}
      style={{
        padding: "1.25rem",
        border: `1px dashed ${T.line}`,
        borderRadius: "0.4rem",
        backgroundColor: T.panel,
      }}
    >
      <p style={{ margin: 0, fontWeight: 600, color: T.ink }}>{title}</p>
      <p style={{ margin: "0.35rem 0 0", fontSize: "0.85rem", color: T.muted }}>{detail}</p>
    </div>
  );
}

/**
 * What "Enabled" does and does not mean.
 *
 * Shown wherever a connector's status is offered as a control, for the same
 * reason M13 shows a note beside "Frozen".
 */
export function EnabledMeansNote() {
  return (
    <p
      data-testid="enabled-means-note"
      style={{ margin: "0.4rem 0 0", fontSize: "0.78rem", color: T.muted }}
    >
      Enabled means this connector may be used to transfer content. It is not
      approval, not validation of the remote system, and not a regulatory
      submission of anything sent through it.
    </p>
  );
}

/** Shown before a transfer is started. */
export const TRANSFER_CONFIRM_NOTE =
  "This sends the frozen package to the destination this connector is configured " +
  "for. It is a technical transfer, not a regulatory submission.";

export function Monospace({ value, testId }: { value: string; testId?: string }) {
  if (!value) return <span style={{ color: T.muted }}>—</span>;
  return (
    <code
      data-testid={testId}
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
      {value.length > 20 ? `${value.slice(0, 20)}…` : value}
    </code>
  );
}
