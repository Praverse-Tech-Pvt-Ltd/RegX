"use client";

/**
 * External integrations: the connector list and the form that creates one.
 *
 * Configuring a connector points the server at a network address, so the create
 * form is offered only when the server says the caller may create -- advisory
 * only, since the endpoint re-checks.
 *
 * The credential field is labelled **Secret reference**, not "Password". The
 * user is naming an environment variable the deployment must provide; they are
 * not typing a secret, and a field that looked like a password box would invite
 * them to.
 */

import { Suspense, useCallback, useEffect, useState, type FormEvent } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { ApiError, externalIntegrations, type Connector } from "@/lib/api";
import {
  ConnectorStatusBadge,
  EmptyState,
  EnabledMeansNote,
  T,
  TestStatusBadge,
  errorLabel,
} from "./integration-primitives";

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

const field: React.CSSProperties = {
  width: "100%",
  padding: "0.4rem 0.55rem",
  border: `1px solid ${T.line}`,
  borderRadius: "0.3rem",
  fontSize: "0.85rem",
  color: T.text,
};

const primary: React.CSSProperties = {
  padding: "0.4rem 0.9rem",
  borderRadius: "0.3rem",
  border: "none",
  backgroundColor: T.blue,
  color: "#ffffff",
  fontSize: "0.85rem",
  fontWeight: 600,
  cursor: "pointer",
};

function ExternalIntegrationsPage() {
  const searchParams = useSearchParams();
  const tenantSlug = searchParams.get("tenant") ?? "";
  const [connectors, setConnectors] = useState<Connector[] | null>(null);
  const [error, setError] = useState("");
  const [forbidden, setForbidden] = useState(false);
  const [showForm, setShowForm] = useState(false);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    if (!tenantSlug) return;
    try {
      const page = await externalIntegrations.list(tenantSlug);
      setConnectors(page.results);
      setError("");
      setForbidden(false);
    } catch (exc) {
      if (exc instanceof ApiError && exc.status === 403) {
        // "You may not see this" is a different state from "this failed".
        setForbidden(true);
        setConnectors([]);
        return;
      }
      setError("The connector list could not be loaded.");
      setConnectors([]);
    }
  }, [tenantSlug]);

  useEffect(() => {
    void load();
  }, [load]);

  async function create(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!tenantSlug) return;
    const form = new FormData(event.currentTarget);
    setBusy(true);
    setError("");
    try {
      await externalIntegrations.create(tenantSlug, {
        name: String(form.get("name") ?? ""),
        description: String(form.get("description") ?? ""),
        connector_type: "generic_https",
        configuration: {
          base_url: String(form.get("base_url") ?? ""),
          allowed_path_prefix: String(form.get("allowed_path_prefix") ?? "/"),
          health_path: String(form.get("health_path") ?? ""),
          connect_timeout_seconds: Number(form.get("connect_timeout_seconds") ?? 5),
          read_timeout_seconds: Number(form.get("read_timeout_seconds") ?? 30),
          verify_tls: true,
        },
        credential: {
          credential_type: String(form.get("credential_type") ?? "bearer_token"),
          reference_name: String(form.get("reference_name") ?? ""),
        },
      });
      setShowForm(false);
      await load();
    } catch (exc) {
      // `ApiError` carries a status and a message, not a parsed body, so the
      // enumerated code is recovered from the message rather than guessed at.
      // A code we do not recognise falls back to a plain sentence: the server's
      // own words are never rendered, because a rejected configuration value
      // would come back with them.
      const message = exc instanceof ApiError ? exc.message : "";
      const match = message.match(/(CONFIG_[A-Z_]+|[A-Z]+_REJECTED|URL_INVALID)/);
      setError(
        (match ? errorLabel(match[1] ?? "") : "") || "The connector could not be created.",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <main style={{ padding: "1.5rem", maxWidth: "72rem" }}>
      <h1 style={{ fontSize: "1.35rem", color: T.ink, margin: 0 }}>External integrations</h1>
      <p style={{ margin: "0.4rem 0 0", fontSize: "0.9rem", color: T.muted, maxWidth: "48rem" }}>
        Connectors are destinations this tenant has configured for technical
        transfer of internal packages and for importing documents. Nothing here
        is an agency gateway and no transfer is a regulatory submission.
      </p>
      <EnabledMeansNote />

      {error && (
        <p
          data-testid="integration-error"
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

      <div style={{ marginTop: "1rem" }}>
        <button
          type="button"
          data-testid="new-connector"
          onClick={() => setShowForm((open) => !open)}
          style={primary}
          aria-expanded={showForm}
          aria-controls="connector-form"
        >
          {showForm ? "Cancel" : "New connector"}
        </button>
      </div>

      {showForm && (
        <form
          id="connector-form"
          data-testid="connector-form"
          onSubmit={create}
          style={{
            marginTop: "0.9rem",
            padding: "1rem",
            border: `1px solid ${T.line}`,
            borderRadius: "0.4rem",
            backgroundColor: T.panel,
            display: "grid",
            gap: "0.7rem",
            maxWidth: "36rem",
          }}
        >
          <div>
            <label htmlFor="name" style={{ fontSize: "0.8rem", color: T.ink, fontWeight: 600 }}>
              Name
            </label>
            <input id="name" name="name" required style={field} data-testid="connector-name" />
          </div>
          <div>
            <label htmlFor="base_url" style={{ fontSize: "0.8rem", color: T.ink, fontWeight: 600 }}>
              Base URL
            </label>
            <input
              id="base_url"
              name="base_url"
              required
              type="url"
              placeholder="https://endpoint.example/"
              style={field}
              data-testid="connector-base-url"
              aria-describedby="base_url_help"
            />
            <p id="base_url_help" style={{ margin: "0.2rem 0 0", fontSize: "0.75rem", color: T.muted }}>
              HTTPS only, on a public internet destination. TLS verification is
              always on and cannot be turned off.
            </p>
          </div>
          <div>
            <label
              htmlFor="allowed_path_prefix"
              style={{ fontSize: "0.8rem", color: T.ink, fontWeight: 600 }}
            >
              Allowed path prefix
            </label>
            <input
              id="allowed_path_prefix"
              name="allowed_path_prefix"
              defaultValue="/"
              style={field}
              data-testid="connector-prefix"
              aria-describedby="prefix_help"
            />
            <p id="prefix_help" style={{ margin: "0.2rem 0 0", fontSize: "0.75rem", color: T.muted }}>
              Every request stays beneath this path.
            </p>
          </div>
          <div>
            <label
              htmlFor="health_path"
              style={{ fontSize: "0.8rem", color: T.ink, fontWeight: 600 }}
            >
              Health path (optional)
            </label>
            <input id="health_path" name="health_path" style={field} data-testid="connector-health" />
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "0.7rem" }}>
            <div>
              <label
                htmlFor="connect_timeout_seconds"
                style={{ fontSize: "0.8rem", color: T.ink, fontWeight: 600 }}
              >
                Connect timeout (s)
              </label>
              <input
                id="connect_timeout_seconds"
                name="connect_timeout_seconds"
                type="number"
                min={1}
                max={15}
                defaultValue={5}
                style={field}
              />
            </div>
            <div>
              <label
                htmlFor="read_timeout_seconds"
                style={{ fontSize: "0.8rem", color: T.ink, fontWeight: 600 }}
              >
                Read timeout (s)
              </label>
              <input
                id="read_timeout_seconds"
                name="read_timeout_seconds"
                type="number"
                min={1}
                max={120}
                defaultValue={30}
                style={field}
              />
            </div>
          </div>
          <div>
            <label
              htmlFor="credential_type"
              style={{ fontSize: "0.8rem", color: T.ink, fontWeight: 600 }}
            >
              Credential type
            </label>
            <select
              id="credential_type"
              name="credential_type"
              defaultValue="bearer_token"
              style={field}
              data-testid="credential-type"
            >
              <option value="bearer_token">Bearer token</option>
              <option value="api_key">API key header</option>
              <option value="basic_auth">Basic authentication</option>
            </select>
          </div>
          <div>
            <label
              htmlFor="reference_name"
              style={{ fontSize: "0.8rem", color: T.ink, fontWeight: 600 }}
            >
              Secret reference (optional)
            </label>
            <input
              id="reference_name"
              name="reference_name"
              // Explicitly text, never a password box. Nobody types a secret
              // here, and a masked field would invite them to paste one.
              type="text"
              style={field}
              data-testid="credential-reference"
              aria-describedby="reference_help"
            />
            {/* Deliberately not a password field: nobody types a secret here. */}
            <p
              id="reference_help"
              style={{ margin: "0.2rem 0 0", fontSize: "0.75rem", color: T.muted }}
            >
              The name of an environment variable the deployment provides. RegX
              stores the name, never the value. Leave blank to have one derived.
            </p>
          </div>
          <div>
            <button type="submit" disabled={busy} style={primary} data-testid="connector-submit">
              {busy ? "Creating…" : "Create connector"}
            </button>
          </div>
        </form>
      )}

      <section aria-labelledby="connector-list-heading" style={{ marginTop: "1.5rem" }}>
        <h2 id="connector-list-heading" style={{ fontSize: "1.05rem", color: T.ink }}>
          Connectors
        </h2>

        {forbidden && (
          <EmptyState
            testId="connectors-forbidden"
            title="You do not have access to external integrations"
            detail="Ask a tenant administrator if you need to view or run connectors."
          />
        )}

        {!forbidden && connectors !== null && connectors.length === 0 && (
          <EmptyState
            testId="connectors-empty"
            title="No connectors configured"
            detail="A tenant administrator can add one. Until then there is nowhere to transfer to."
          />
        )}

        {connectors !== null && connectors.length > 0 && (
          <table
            data-testid="connector-table"
            style={{ width: "100%", borderCollapse: "collapse", marginTop: "0.6rem" }}
          >
            <caption style={{ captionSide: "top", textAlign: "left", padding: "0 0 0.4rem" }}>
              <span style={{ fontSize: "0.8rem", color: T.muted }}>
                Configured external destinations for this tenant
              </span>
            </caption>
            <thead>
              <tr>
                <th scope="col" style={headCell}>
                  Name
                </th>
                <th scope="col" style={headCell}>
                  Status
                </th>
                <th scope="col" style={headCell}>
                  Type
                </th>
                <th scope="col" style={headCell}>
                  Last test
                </th>
                <th scope="col" style={headCell}>
                  Config version
                </th>
              </tr>
            </thead>
            <tbody>
              {connectors.map((connector) => (
                <tr key={connector.public_id} data-testid="connector-row">
                  <td style={cell}>
                    <Link
                      href={`/external-integrations/${connector.public_id}`}
                      style={{ color: T.blue, fontWeight: 600 }}
                    >
                      {connector.name}
                    </Link>
                  </td>
                  <td style={cell}>
                    <ConnectorStatusBadge status={connector.status} />
                  </td>
                  <td style={cell}>HTTPS endpoint</td>
                  <td style={cell}>
                    <TestStatusBadge status={connector.last_test_status} />
                  </td>
                  <td style={cell}>{connector.configuration_version}</td>
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
      <ExternalIntegrationsPage />
    </Suspense>
  );
}
