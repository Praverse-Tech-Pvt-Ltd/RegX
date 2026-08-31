"use client";

/**
 * "Transfer internal package" on a frozen package.
 *
 * The verb is **Transfer**, never "Submit", and the destination is named as the
 * connector the tenant configured. Nothing on this panel says or implies agency
 * submission, filing, or acceptance -- a transfer is a technical act against an
 * endpoint somebody in this tenant set up.
 *
 * The panel appears only when the caller can both export the package and run a
 * connector. Both are re-checked server-side; this only decides whether to
 * offer the control.
 */

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import {
  ApiError,
  externalIntegrations,
  type Connector,
  type ConnectorExecution,
} from "@/lib/api";
import {
  ExecutionStatusBadge,
  TRANSFER_CONFIRM_NOTE,
  errorLabel,
} from "../../external-integrations/integration-primitives";
import { T } from "../package-primitives";

const button: React.CSSProperties = {
  padding: "0.35rem 0.8rem",
  borderRadius: "0.3rem",
  border: `1px solid ${T.line}`,
  backgroundColor: "#ffffff",
  color: T.navy,
  fontSize: "0.82rem",
  cursor: "pointer",
};

const primary: React.CSSProperties = {
  ...button,
  backgroundColor: T.navy,
  borderColor: T.navy,
  color: "#fff",
  fontWeight: 600,
};

export function TransferPanel({
  tenantSlug,
  packagePublicId,
}: {
  tenantSlug: string;
  packagePublicId: string;
}) {
  const [connectors, setConnectors] = useState<Connector[] | null>(null);
  const [selected, setSelected] = useState("");
  const [execution, setExecution] = useState<ConnectorExecution | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    if (!tenantSlug) return;
    try {
      const page = await externalIntegrations.list(tenantSlug);
      // Only enabled connectors can run anything, so only they are offered.
      const usable = page.results.filter((connector) => connector.status === "active");
      setConnectors(usable);
      setSelected(usable[0]?.public_id ?? "");
    } catch {
      // Not an error on this page: a caller without connector permission simply
      // has no transfer option, and saying "failed" would be wrong.
      setConnectors([]);
    }
  }, [tenantSlug]);

  useEffect(() => {
    void load();
  }, [load]);

  async function transfer() {
    if (!selected) return;
    setBusy(true);
    setError("");
    try {
      const result = await externalIntegrations.execute(tenantSlug, selected, {
        operation: "push_frozen_package",
        payload: { package_public_id: packagePublicId },
      });
      setExecution(result);
    } catch (exc) {
      if (exc instanceof ApiError && exc.status === 403) {
        setError(
          "Transferring a package needs permission to export packages and to view their documents.",
        );
      } else if (exc instanceof ApiError && exc.status === 409) {
        setError("Only a frozen package can be transferred.");
      } else {
        setError("The transfer could not be started.");
      }
    } finally {
      setBusy(false);
    }
  }

  if (connectors === null) return null;

  return (
    <section
      aria-labelledby="transfer-heading"
      data-testid="transfer-panel"
      style={{ marginTop: "1.5rem" }}
    >
      <h2 id="transfer-heading" style={{ fontSize: "1.05rem", color: T.ink }}>
        Transfer internal package
      </h2>
      <p style={{ margin: "0.2rem 0 0.6rem", fontSize: "0.8rem", color: T.muted, maxWidth: "42rem" }}>
        {TRANSFER_CONFIRM_NOTE}
      </p>

      {connectors.length === 0 ? (
        <p data-testid="no-connectors" style={{ fontSize: "0.85rem", color: T.muted }}>
          No enabled connector is available.{" "}
          <Link href={`/external-integrations?tenant=${tenantSlug}`} style={{ color: T.blue }}>
            Manage connectors
          </Link>
          .
        </p>
      ) : (
        <div style={{ display: "flex", gap: "0.5rem", alignItems: "flex-end", flexWrap: "wrap" }}>
          <div>
            <label
              htmlFor="transfer-connector"
              style={{ display: "block", fontSize: "0.8rem", color: T.ink, fontWeight: 600 }}
            >
              Destination connector
            </label>
            <select
              id="transfer-connector"
              data-testid="transfer-connector"
              value={selected}
              onChange={(event) => setSelected(event.target.value)}
              style={{
                padding: "0.35rem 0.5rem",
                border: `1px solid ${T.line}`,
                borderRadius: "0.3rem",
                fontSize: "0.85rem",
                color: T.text,
                minWidth: "16rem",
              }}
            >
              {connectors.map((connector) => (
                <option key={connector.public_id} value={connector.public_id}>
                  {connector.name}
                </option>
              ))}
            </select>
          </div>
          <button
            type="button"
            data-testid="start-transfer"
            onClick={transfer}
            disabled={busy || !selected}
            style={primary}
          >
            {busy ? "Starting…" : "Transfer via connector"}
          </button>
        </div>
      )}

      {error && (
        <p
          data-testid="transfer-error"
          role="alert"
          style={{
            marginTop: "0.7rem",
            padding: "0.5rem 0.7rem",
            borderRadius: "0.3rem",
            backgroundColor: "#fdecec",
            color: "#8c1d1d",
            fontSize: "0.85rem",
          }}
        >
          {error}
        </p>
      )}

      {execution && (
        <div
          data-testid="transfer-result"
          role="status"
          style={{
            marginTop: "0.7rem",
            padding: "0.6rem 0.8rem",
            borderRadius: "0.3rem",
            border: `1px solid ${T.line}`,
            backgroundColor: T.panel,
            fontSize: "0.85rem",
          }}
        >
          <ExecutionStatusBadge status={execution.status} />{" "}
          {execution.error_code ? (
            <span data-testid="transfer-execution-error">{errorLabel(execution.error_code)}</span>
          ) : (
            <span>
              Transfer recorded against configuration version{" "}
              {execution.connector_configuration_version}.
            </span>
          )}{" "}
          <Link
            href={`/external-integrations/${execution.connector_public_id}?tenant=${tenantSlug}`}
            style={{ color: T.blue }}
          >
            View history
          </Link>
        </div>
      )}
    </section>
  );
}
