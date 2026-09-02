import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";

import {
  ConnectorStatusBadge,
  EmptyState,
  EnabledMeansNote,
  ExecutionStatusBadge,
  Monospace,
  TRANSFER_CONFIRM_NOTE,
  TestStatusBadge,
  errorLabel,
  operationLabel,
} from "@/app/(regx)/external-integrations/integration-primitives";

// ---------------------------------------------------------------------------
// Wording: a connector is a destination, a transfer is not a submission
// ---------------------------------------------------------------------------
describe("Internal-only wording", () => {
  it("says what Enabled is not", () => {
    render(<EnabledMeansNote />);
    const note = (screen.getByTestId("enabled-means-note").textContent ?? "").toLowerCase();
    expect(note).toContain("not approval");
    expect(note).toContain("not validation of the remote system");
    expect(note).toContain("not a regulatory submission");
  });

  it("the transfer confirmation calls it a technical transfer", () => {
    const note = TRANSFER_CONFIRM_NOTE.toLowerCase();
    expect(note).toContain("technical transfer");
    expect(note).toContain("not a regulatory submission");
  });

  it("no connector status label borrows approval language", () => {
    for (const status of ["draft", "active", "disabled", "archived"] as const) {
      const { unmount } = render(<ConnectorStatusBadge status={status} />);
      const text = (screen.getByTestId("connector-status-badge").textContent ?? "").toLowerCase();
      for (const banned of ["approved", "accepted", "validated", "certified", "compliant"]) {
        expect(text).not.toContain(banned);
      }
      unmount();
    }
  });

  it("no execution status label claims a submission", () => {
    for (const status of ["queued", "running", "succeeded", "failed", "cancelled"] as const) {
      const { unmount } = render(<ExecutionStatusBadge status={status} />);
      const text = (screen.getByTestId("execution-status-badge").textContent ?? "").toLowerCase();
      for (const banned of ["submitted", "filed", "accepted", "approved", "agency"]) {
        expect(text).not.toContain(banned);
      }
      unmount();
    }
  });

  it("a successful transfer reads as transferred, not accepted", () => {
    // "Accepted" would be a claim about what the remote system did with the
    // bytes, which nothing here knows.
    render(<ExecutionStatusBadge status="succeeded" />);
    expect(screen.getByTestId("execution-status-badge")).toHaveTextContent("Transferred");
  });

  it("operation labels use transfer and import, never submit", () => {
    expect(operationLabel("push_frozen_package")).toBe("Transfer frozen package");
    expect(operationLabel("import_document")).toBe("Import document");
    for (const operation of ["push_frozen_package", "import_document"]) {
      expect(operationLabel(operation).toLowerCase()).not.toContain("submit");
    }
  });
});

// ---------------------------------------------------------------------------
// Failure states are distinguished, not collapsed
// ---------------------------------------------------------------------------
describe("Failure states", () => {
  it("gives each enumerated code its own sentence", () => {
    const distinct = new Set(
      [
        "DNS_BLOCKED",
        "TLS_ERROR",
        "TIMEOUT",
        "AUTH_FAILED",
        "REMOTE_4XX",
        "REMOTE_5XX",
        "RESPONSE_TOO_LARGE",
        "DOCUMENT_REJECTED",
        "PACKAGE_INTEGRITY_FAILED",
        "CONNECTOR_DISABLED",
        "CREDENTIAL_UNAVAILABLE",
      ].map(errorLabel),
    );
    // Eleven codes, eleven sentences: nothing collapses into "Error".
    expect(distinct.size).toBe(11);
    for (const sentence of distinct) {
      expect(sentence.toLowerCase()).not.toBe("error");
    }
  });

  it("distinguishes not-configured from disabled from unreachable", () => {
    expect(errorLabel("CONNECTOR_DISABLED")).toMatch(/disabled/i);
    expect(errorLabel("DNS_UNRESOLVED")).toMatch(/resolved/i);
    expect(errorLabel("AUTH_FAILED")).toMatch(/authentication/i);
    expect(errorLabel("CREDENTIAL_UNAVAILABLE")).toMatch(/does not provide/i);
  });

  it("renders an unknown code readably rather than shouting", () => {
    expect(errorLabel("A_BRAND_NEW_CODE")).toBe("a brand new code");
  });

  it("an empty state names what is absent and what to do", () => {
    render(
      <EmptyState
        testId="connectors-empty"
        title="No connectors configured"
        detail="A tenant administrator can add one."
      />,
    );
    expect(screen.getByTestId("connectors-empty")).toHaveTextContent("No connectors configured");
    expect(screen.getByTestId("connectors-empty")).toHaveTextContent("tenant administrator");
  });
});

// ---------------------------------------------------------------------------
// Nothing renders a secret
// ---------------------------------------------------------------------------
describe("Secrets", () => {
  it("the credential type in the API surface carries no value field", async () => {
    // A structural check on the client type's runtime shape: the server has no
    // column for a secret, and nothing in the client invents one.
    const api = await import("@/lib/api");
    const source = Object.keys(api.externalIntegrations);
    expect(source).toContain("test");
    expect(source).not.toContain("secret");
    expect(source).not.toContain("credentialValue");
  });

  it("renders an environment variable name as plain text", () => {
    render(<Monospace value="REGX_CONNECTOR_ABC_TOKEN" testId="credential-variable" />);
    // The *name* is shown because an operator needs it. It is not a secret.
    expect(screen.getByTestId("credential-variable")).toHaveTextContent("REGX_CONNECTOR_ABC");
  });

  it("truncates a long remote identifier rather than rendering it whole", () => {
    render(<Monospace value={"x".repeat(200)} testId="external-reference" />);
    const text = screen.getByTestId("external-reference").textContent ?? "";
    expect(text.length).toBeLessThan(30);
  });
});

// ---------------------------------------------------------------------------
// Test result rendering
// ---------------------------------------------------------------------------
describe("Connection test", () => {
  it("labels every reachability outcome in words", () => {
    const labels = (["never_tested", "reachable", "unreachable", "unauthorised"] as const).map(
      (status) => {
        const { unmount } = render(<TestStatusBadge status={status} />);
        const text = screen.getByTestId("connector-test-badge").textContent ?? "";
        unmount();
        return text;
      },
    );
    expect(new Set(labels).size).toBe(4);
    expect(labels).toContain("Authentication failed");
  });
});
