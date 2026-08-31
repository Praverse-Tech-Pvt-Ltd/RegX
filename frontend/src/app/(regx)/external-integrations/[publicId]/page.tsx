"use client";

/**
 * Connector detail: configuration, connection test, and execution history.
 *
 * Every control is offered from the server-supplied `permissions` block --
 * advisory only, since each endpoint re-checks its own permission. What the
 * page never does is show a secret: the credential panel shows a type and the
 * *name* of an environment variable, and whether the deployment currently
 * provides it. There is no value to show.
 *
 * Failure states are distinguished rather than collapsed into "Error": not
 * configured, disabled, unreachable, authentication failed and transfer failed
 * are five different things a person would do five different things about.
 */

import { Suspense, useCallback, useEffect, useState } from "react";
import { useParams, useSearchParams } from "next/navigation";
import Link from "next/link";
import {
  ApiError,
  externalIntegrations,
  type Connector,
  type ConnectionTestResult,
  type ConnectorExecution,
} from "@/lib/api";
import {
  ConnectorStatusBadge,
  EmptyState,
  EnabledMeansNote,
  ExecutionStatusBadge,
  Monospace,
  T,
  TestStatusBadge,
  errorLabel,
  operationLabel,
} from "../integration-primitives";

const cell: React.CSSProperties = {
  padding: "0.5rem 0.65rem",
  borderBottom: `1px solid ${T.line}`,
  fontSize: "0.85rem",
  color: T.text,
  textAlign: "left",
  verticalAlign: "top",
};

const headCell: React.CSSProperties = {
  ...cell,
  fontWeight: 600,
  color: T.ink,
  backgroundColor: T.panel,
  whiteSpace: "nowrap",
};

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

function ConnectorPage() {
  const params = useParams<{ publicId: string }>();
  const searchParams = useSearchParams();
  const publicId = params.publicId;
  const tenantSlug = searchParams.get("tenant") ?? "";

  const [connector, setConnector] = useState<Connector | null>(null);
  const [executions, setExecutions] = useState<ConnectorExecution[] | null>(null);
  const [testResult, setTestResult] = useState<ConnectionTestResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notFound, setNotFound] = useState(false);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    if (!tenantSlug || !publicId) return;
    try {
      const [detail, history] = await Promise.all([
        externalIntegrations.get(tenantSlug, publicId),
        externalIntegrations.executions(tenantSlug, publicId).catch(() => null),
      ]);
      setConnector(detail);
      setExecutions(history ? history.results : null);
      setError(null);
      setNotFound(false);
    } catch (exc) {
      if (exc instanceof ApiError && exc.status === 404) {
        setNotFound(true);
        return;
      }
      setError("This connector could not be loaded.");
    }
  }, [tenantSlug, publicId]);

  useEffect(() => {
    void load();
  }, [load]);

  async function act(action: "enable" | "disable" | "archive" | "test") {
    if (!tenantSlug || !publicId) return;
    setBusy(true);
    setError(null);
    try {
      if (action === "test") {
        setTestResult(await externalIntegrations.test(tenantSlug, publicId));
      } else {
        await externalIntegrations[action](tenantSlug, publicId);
        setTestResult(null);
      }
      await load();
    } catch {
      setError("That action could not be completed.");
    } finally {
      setBusy(false);
    }
  }

  if (notFound) {
    return (
      <main style={{ padding: "1.5rem" }}>
        <EmptyState
          testId="connector-not-found"
          title="No such connector"
          detail="It may have been archived, or it belongs to another tenant."
        />
      </main>
    );
  }

  if (!connector) {
    return <p style={{ padding: "1.5rem" }}>Loading…</p>;
  }

  const permissions = connector.permissions ?? {};
  const configuration = connector.configuration as Record<string, unknown>;

  return (
    <main style={{ padding: "1.5rem", maxWidth: "72rem" }}>
      <p style={{ margin: 0, fontSize: "0.8rem" }}>
        <Link href={`/external-integrations?tenant=${tenantSlug}`} style={{ color: T.blue }}>
          ← All connectors
        </Link>
      </p>
      <h1 style={{ fontSize: "1.35rem", color: T.ink, margin: "0.4rem 0 0" }}>{connector.name}</h1>
      <p style={{ margin: "0.4rem 0 0", display: "flex", gap: "0.5rem", alignItems: "center" }}>
        <ConnectorStatusBadge status={connector.status} />
        <TestStatusBadge status={connector.last_test_status} />
      </p>
      <EnabledMeansNote />

      {error && (
        <p
          data-testid="connector-error"
          role="alert"
          style={{
            marginTop: "0.9rem",
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

      {/* ------------------------------------------------------------------ */}
      <section aria-labelledby="config-heading" style={{ marginTop: "1.4rem" }}>
        <h2 id="config-heading" style={{ fontSize: "1.05rem", color: T.ink }}>
          Configuration
        </h2>
        <dl
          data-testid="connector-configuration"
          style={{ display: "grid", gridTemplateColumns: "auto 1fr", gap: "0.3rem 1rem", margin: 0 }}
        >
          <dt style={{ color: T.muted, fontSize: "0.8rem" }}>Base URL</dt>
          <dd style={{ margin: 0, fontSize: "0.85rem" }} data-testid="config-base-url">
            {String(configuration.base_url ?? "")}
          </dd>
          <dt style={{ color: T.muted, fontSize: "0.8rem" }}>Allowed path prefix</dt>
          <dd style={{ margin: 0, fontSize: "0.85rem" }}>
            {String(configuration.allowed_path_prefix ?? "/")}
          </dd>
          <dt style={{ color: T.muted, fontSize: "0.8rem" }}>Timeouts</dt>
          <dd style={{ margin: 0, fontSize: "0.85rem" }}>
            {String(configuration.connect_timeout_seconds ?? "")}s connect,{" "}
            {String(configuration.read_timeout_seconds ?? "")}s read
          </dd>
          <dt style={{ color: T.muted, fontSize: "0.8rem" }}>TLS verification</dt>
          <dd style={{ margin: 0, fontSize: "0.85rem" }} data-testid="config-tls">
            Always on
          </dd>
          <dt style={{ color: T.muted, fontSize: "0.8rem" }}>Configuration version</dt>
          <dd style={{ margin: 0, fontSize: "0.85rem" }} data-testid="config-version">
            {connector.configuration_version}
          </dd>
        </dl>
      </section>

      {/* ------------------------------------------------------------------ */}
      <section aria-labelledby="credential-heading" style={{ marginTop: "1.4rem" }}>
        <h2 id="credential-heading" style={{ fontSize: "1.05rem", color: T.ink }}>
          Secret reference
        </h2>
        {connector.credential ? (
          <dl
            data-testid="connector-credential"
            style={{
              display: "grid",
              gridTemplateColumns: "auto 1fr",
              gap: "0.3rem 1rem",
              margin: 0,
            }}
          >
            <dt style={{ color: T.muted, fontSize: "0.8rem" }}>Type</dt>
            <dd style={{ margin: 0, fontSize: "0.85rem" }}>
              {connector.credential.credential_type.replace(/_/g, " ")}
            </dd>
            <dt style={{ color: T.muted, fontSize: "0.8rem" }}>Environment variable</dt>
            <dd style={{ margin: 0 }}>
              <Monospace
                value={connector.credential.environment_variable}
                testId="credential-variable"
              />
            </dd>
            <dt style={{ color: T.muted, fontSize: "0.8rem" }}>Provided by this deployment</dt>
            <dd style={{ margin: 0, fontSize: "0.85rem" }} data-testid="credential-resolvable">
              {connector.credential.is_resolvable ? "Yes" : "No — the variable is not set"}
            </dd>
          </dl>
        ) : (
          <EmptyState
            testId="credential-absent"
            title="No credential reference"
            detail="This connector authenticates with nothing. Requests will be sent unauthenticated."
          />
        )}
        <p style={{ margin: "0.5rem 0 0", fontSize: "0.78rem", color: T.muted }}>
          RegX stores the name of an environment variable, never a secret value.
          There is no field here that could hold one.
        </p>
      </section>

      {/* ------------------------------------------------------------------ */}
      <div style={{ display: "flex", gap: "0.4rem", marginTop: "1.4rem", flexWrap: "wrap" }}>
        {permissions.can_test && (
          <button
            type="button"
            data-testid="test-connection"
            onClick={() => act("test")}
            disabled={busy}
            style={button}
          >
            Test connection
          </button>
        )}
        {permissions.can_enable && connector.status !== "active" && (
          <button
            type="button"
            data-testid="enable-connector"
            onClick={() => act("enable")}
            disabled={busy}
            style={primary}
          >
            Enable
          </button>
        )}
        {permissions.can_enable && connector.status === "active" && (
          <button
            type="button"
            data-testid="disable-connector"
            onClick={() => act("disable")}
            disabled={busy}
            style={button}
          >
            Disable
          </button>
        )}
      </div>

      {testResult && (
        <div
          data-testid="test-result"
          role="status"
          style={{
            marginTop: "0.8rem",
            padding: "0.6rem 0.8rem",
            borderRadius: "0.3rem",
            border: `1px solid ${T.line}`,
            backgroundColor: T.panel,
            fontSize: "0.85rem",
          }}
        >
          <TestStatusBadge status={testResult.status} />{" "}
          {testResult.reachable ? (
            <span>
              Reachable
              {testResult.latency_ms !== null ? ` in ${testResult.latency_ms} ms` : ""}
              {testResult.authenticated ? ", authenticated" : ""}.
            </span>
          ) : (
            <span data-testid="test-error">{errorLabel(testResult.error_code)}</span>
          )}
        </div>
      )}

      {/* ------------------------------------------------------------------ */}
      <section aria-labelledby="history-heading" style={{ marginTop: "1.6rem" }}>
        <h2 id="history-heading" style={{ fontSize: "1.05rem", color: T.ink }}>
          Execution history
        </h2>
        {executions === null && (
          <EmptyState
            testId="history-forbidden"
            title="You do not have access to execution history"
            detail="Viewing what has been transferred needs the history permission."
          />
        )}
        {executions !== null && executions.length === 0 && (
          <EmptyState
            testId="history-empty"
            title="Nothing has been transferred yet"
            detail="Transfers started from a frozen package will appear here."
          />
        )}
        {executions !== null && executions.length > 0 && (
          <table
            data-testid="execution-table"
            style={{ width: "100%", borderCollapse: "collapse", marginTop: "0.6rem" }}
          >
            <caption style={{ captionSide: "top", textAlign: "left", padding: "0 0 0.4rem" }}>
              <span style={{ fontSize: "0.8rem", color: T.muted }}>
                Technical transfer attempts through this connector
              </span>
            </caption>
            <thead>
              <tr>
                <th scope="col" style={headCell}>
                  Operation
                </th>
                <th scope="col" style={headCell}>
                  Status
                </th>
                <th scope="col" style={headCell}>
                  Requested
                </th>
                <th scope="col" style={headCell}>
                  Attempts
                </th>
                <th scope="col" style={headCell}>
                  Config version
                </th>
                <th scope="col" style={headCell}>
                  Result
                </th>
                <th scope="col" style={headCell}>
                  Correlation ID
                </th>
              </tr>
            </thead>
            <tbody>
              {executions.map((execution) => (
                <tr key={execution.public_id} data-testid="execution-row">
                  <td style={cell}>{operationLabel(execution.operation)}</td>
                  <td style={cell}>
                    <ExecutionStatusBadge status={execution.status} />
                  </td>
                  <td style={cell}>{execution.requested_at}</td>
                  <td style={cell}>{execution.attempt_count}</td>
                  <td style={cell}>{execution.connector_configuration_version}</td>
                  <td style={cell} data-testid="execution-result">
                    {execution.error_code ? (
                      errorLabel(execution.error_code)
                    ) : execution.external_reference ? (
                      <Monospace value={execution.external_reference} testId="external-reference" />
                    ) : (
                      <span style={{ color: T.muted }}>—</span>
                    )}
                  </td>
                  <td style={cell}>
                    <Monospace value={execution.correlation_id} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </main>
  );
}

export default function Page() {
  return (
    <Suspense fallback={<p style={{ padding: "1.5rem" }}>Loading…</p>}>
      <ConnectorPage />
    </Suspense>
  );
}
