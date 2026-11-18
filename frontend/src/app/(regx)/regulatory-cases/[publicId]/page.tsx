"use client";

import { Suspense, useEffect, useState, type FormEvent } from "react";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import { regulatoryCases, ApiError, type CaseDetail, isSignedOut, loadError } from "@/lib/api";
import { CaseStatusBadge } from "../status-badge";
import { PackagePanel } from "./package-panel";
import { CaseDossiersPanel } from "./dossiers-panel";

const T = {
  ink: "#001f45",
  text: "#314155",
  muted: "#66768b",
  line: "#dce7f4",
  soft: "#eaf2fd",
  panel: "#f4f8fe",
  blue: "#045e8f",
  navy: "#003865",
} as const;

const TABS = [
  "overview",
  "documents",
  "workflows",
  "checklists",
  "dossiers",
  "packages",
  "evidence",
] as const;
type Tab = (typeof TABS)[number];

const TAB_LABELS: Record<Tab, string> = {
  overview: "Overview",
  documents: "Documents",
  workflows: "Workflow",
  checklists: "Checklists",
  dossiers: "Dossiers",
  packages: "Packages",
  evidence: "Evidence / Activity",
};

const field: React.CSSProperties = {
  padding: "0.45rem 0.6rem",
  border: `1px solid ${T.line}`,
  borderRadius: 6,
  background: "#fff",
  color: T.text,
  fontSize: "0.88rem",
};

const cell: React.CSSProperties = {
  padding: "0.6rem 0.5rem",
  fontSize: "0.9rem",
  color: T.text,
  verticalAlign: "middle",
};

const head: React.CSSProperties = {
  padding: "0.5rem",
  fontSize: "0.72rem",
  fontWeight: 700,
  letterSpacing: "0.05em",
  textTransform: "uppercase",
  color: T.muted,
};

function ghostButton(disabled: boolean): React.CSSProperties {
  return {
    padding: "0.3rem 0.7rem",
    border: `1px solid ${T.line}`,
    borderRadius: 6,
    background: "#fff",
    color: T.blue,
    fontSize: "0.82rem",
    fontWeight: 600,
    cursor: disabled ? "not-allowed" : "pointer",
    opacity: disabled ? 0.5 : 1,
  };
}

/** A link the caller may see but whose module permission they lack. */
function RestrictedCell() {
  return (
    <span data-testid="link-restricted" title="Requires permission for that module">
      <em style={{ color: T.muted }}>(no access)</em>
    </span>
  );
}

function Stat({
  label,
  value,
  testId,
}: {
  label: string;
  value: number | null;
  testId: string;
}) {
  // null means the server withheld it -- the caller lacks `workflows.view`.
  // Rendering 0 would be a lie, so it shows an em dash and says why on hover.
  const withheld = value === null;
  return (
    <div
      data-testid={testId}
      title={withheld ? "Requires permission to view workflows" : undefined}
      style={{
        padding: "0.75rem 0.9rem",
        border: `1px solid ${T.line}`,
        borderRadius: 8,
        background: "#fff",
        minWidth: 130,
      }}
    >
      <div style={{ fontSize: "1.3rem", fontWeight: 700, color: withheld ? T.muted : T.ink }}>
        {withheld ? "—" : value}
      </div>
      <div style={{ fontSize: "0.75rem", color: T.muted }}>{label}</div>
    </div>
  );
}

function CaseDetailInner() {
  const router = useRouter();
  const params = useParams<{ publicId: string }>();
  const searchParams = useSearchParams();
  const tenantSlug = searchParams.get("tenant") ?? "";
  const publicId = params.publicId;

  const [detail, setDetail] = useState<CaseDetail | null>(null);
  const [tab, setTab] = useState<Tab>("overview");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notFound, setNotFound] = useState(false);
  const [busy, setBusy] = useState(false);
  const [linkKind, setLinkKind] = useState<"workflows" | "documents" | "checklists">("documents");
  const [linkTargetId, setLinkTargetId] = useState("");

  function load(): Promise<void> {
    if (!tenantSlug) return Promise.resolve();
    setLoading(true);
    return regulatoryCases
      .get(tenantSlug, publicId)
      .then((d) => {
        setDetail(d);
        setError(null);
      })
      .catch((err: unknown) => {
        if (err instanceof ApiError && err.status === 404) {
          setNotFound(true);
        } else if (isSignedOut(err)) {
          router.push(
            `/signin?next=${encodeURIComponent(window.location.pathname + window.location.search)}`
          );
        } else {
          setError(loadError(err, "Failed to load this case."));
        }
      })
      .finally(() => setLoading(false));
  }

  useEffect(() => {
    if (!tenantSlug) {
      router.push("/tenants");
      return;
    }
    void load();
  }, [tenantSlug, publicId]); // eslint-disable-line react-hooks/exhaustive-deps

  async function runAction(fn: () => Promise<unknown>, conflictMessage: string) {
    setBusy(true);
    try {
      await fn();
      await load();
    } catch (err: unknown) {
      // Reload first, then set the message: load() clears errors on success.
      await load();
      if (err instanceof ApiError && err.status === 409) {
        setError(conflictMessage);
      } else if (err instanceof ApiError && err.status === 403) {
        setError("You do not have permission to do that in this tenant.");
      } else if (err instanceof ApiError && err.status === 400) {
        setError("That item is not available to link to this case.");
      } else if (err instanceof ApiError && err.status === 404) {
        setError("That link no longer exists.");
      } else {
        setError("The action could not be completed.");
      }
    } finally {
      setBusy(false);
    }
  }

  async function handleLink(e: FormEvent) {
    e.preventDefault();
    const id = linkTargetId.trim();
    if (!id) return;
    await runAction(
      () => regulatoryCases.linkTarget(tenantSlug, publicId, linkKind, id),
      "This case no longer accepts changes, or that item is already linked."
    );
    setLinkTargetId("");
  }

  if (!tenantSlug) return null;

  if (notFound) {
    return (
      <main style={{ maxWidth: 1000, margin: "2rem auto", padding: "0 1rem" }}>
        <p data-testid="case-not-found" style={{ color: T.muted }}>
          This case was not found.{" "}
          <Link href={`/regulatory-cases?tenant=${tenantSlug}`}>Back to cases</Link>
        </p>
      </main>
    );
  }

  if (loading && !detail) {
    return (
      <main style={{ maxWidth: 1000, margin: "2rem auto", padding: "0 1rem" }}>
        <p style={{ color: T.muted }}>Loading case…</p>
      </main>
    );
  }

  if (!detail) return null;

  const { case: c, permissions, summary } = detail;
  const canManage = permissions.can_manage_links && !c.is_terminal;

  return (
    <main style={{ maxWidth: 1100, margin: "2rem auto", padding: "0 1rem" }}>
      <Link
        href={`/regulatory-cases?tenant=${tenantSlug}`}
        data-testid="back-to-cases"
        style={{ fontSize: "0.85rem", color: T.muted, textDecoration: "none" }}
      >
        ← All cases
      </Link>

      <header style={{ marginTop: "0.5rem", marginBottom: "1.25rem" }}>
        <div style={{ display: "flex", gap: "0.75rem", alignItems: "center", flexWrap: "wrap" }}>
          <span style={{ fontSize: "0.9rem", fontWeight: 700, color: T.muted }}>
            {c.case_number}
          </span>
          <CaseStatusBadge status={c.status} />
        </div>
        <h1 style={{ margin: "0.25rem 0 0.75rem", fontSize: "1.6rem", fontWeight: 700, color: T.ink }}>
          {c.title}
        </h1>

        <dl
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))",
            gap: "0.6rem 1.25rem",
            margin: 0,
          }}
        >
          {(
            [
              ["Product / API", c.product_name],
              ["Product code", c.product_code],
              ["Market", c.market],
              ["Authority", c.authority],
              ["Submission type", c.submission_type],
              ["Owner", c.owner ? c.owner.full_name : ""],
              ["Target date", c.target_date ? new Date(c.target_date).toLocaleDateString() : ""],
            ] as const
          ).map(([label, value]) => (
            <div key={label}>
              <dt style={{ fontSize: "0.72rem", textTransform: "uppercase", letterSpacing: "0.05em", color: T.muted }}>
                {label}
              </dt>
              <dd style={{ margin: 0, fontSize: "0.9rem", color: value ? T.text : T.muted }}>
                {value || "—"}
              </dd>
            </div>
          ))}
        </dl>

        <div style={{ display: "flex", gap: "0.5rem", marginTop: "1rem", flexWrap: "wrap" }}>
          {/* Advisory only. The API re-checks, and refuses on a terminal case. */}
          {permissions.can_complete && !c.is_terminal && (
            <button
              type="button"
              data-testid="complete-case"
              disabled={busy}
              onClick={() =>
                void runAction(
                  () => regulatoryCases.complete(tenantSlug, publicId),
                  "This case has already been completed or cancelled."
                )
              }
              style={ghostButton(busy)}
            >
              Complete case
            </button>
          )}
          {permissions.can_cancel && !c.is_terminal && (
            <button
              type="button"
              data-testid="cancel-case"
              disabled={busy}
              onClick={() =>
                void runAction(
                  () => regulatoryCases.cancel(tenantSlug, publicId),
                  "This case has already been completed or cancelled."
                )
              }
              style={ghostButton(busy)}
            >
              Cancel case
            </button>
          )}
        </div>

        {c.is_terminal && (
          <p
            data-testid="case-terminal-note"
            style={{
              marginTop: "0.9rem",
              padding: "0.6rem 0.8rem",
              border: `1px solid ${T.line}`,
              borderRadius: 6,
              background: T.panel,
              color: T.muted,
              fontSize: "0.85rem",
            }}
          >
            This case is {c.status} and no longer accepts changes. Completing a case records that
            work stopped; it is not a regulatory approval.
          </p>
        )}
      </header>

      {error && (
        <p
          role="alert"
          data-testid="case-error"
          style={{
            margin: "0 0 1rem",
            padding: "0.6rem 0.8rem",
            border: "1px solid #f3c9c4",
            borderRadius: 6,
            background: "#fdf3f2",
            color: "#8f2c20",
            fontSize: "0.88rem",
          }}
        >
          {error}
        </p>
      )}

      <nav
        role="tablist"
        aria-label="Case sections"
        style={{ display: "flex", gap: "0.25rem", borderBottom: `1px solid ${T.line}`, marginBottom: "1rem", flexWrap: "wrap" }}
      >
        {TABS.map((t) => (
          <button
            key={t}
            role="tab"
            aria-selected={tab === t}
            data-testid={`tab-${t}`}
            onClick={() => setTab(t)}
            style={{
              padding: "0.5rem 0.9rem",
              border: "none",
              borderBottom: tab === t ? `2px solid ${T.blue}` : "2px solid transparent",
              background: "none",
              color: tab === t ? T.ink : T.muted,
              fontWeight: 600,
              fontSize: "0.88rem",
              cursor: "pointer",
            }}
          >
            {TAB_LABELS[t]}
          </button>
        ))}
      </nav>

      {tab === "overview" && (
        <section data-testid="tab-panel-overview">
          <div style={{ display: "flex", gap: "0.6rem", flexWrap: "wrap", marginBottom: "1rem" }}>
            <Stat label="Documents" value={summary.documents} testId="stat-documents" />
            <Stat label="Workflow items" value={summary.workflows} testId="stat-workflows" />
            <Stat label="Checklists" value={summary.checklists} testId="stat-checklists" />
            <Stat label="Open workflows" value={summary.workflows_open} testId="stat-open" />
            <Stat label="Completed workflows" value={summary.workflows_completed} testId="stat-completed" />
            <Stat label="Evidence links" value={summary.evidence_links} testId="stat-evidence" />
          </div>
          {c.description ? (
            <p style={{ fontSize: "0.9rem", color: T.text, lineHeight: 1.6 }}>{c.description}</p>
          ) : (
            <p style={{ fontSize: "0.9rem", color: T.muted }}>No description.</p>
          )}
        </section>
      )}

      {(tab === "documents" || tab === "workflows" || tab === "checklists") && (
        <section data-testid={`tab-panel-${tab}`}>
          {canManage && (
            <form
              onSubmit={handleLink}
              data-testid="link-form"
              aria-label="Link resource form"
              style={{ display: "flex", gap: "0.5rem", marginBottom: "1rem", flexWrap: "wrap" }}
            >
              <label htmlFor="link-target" style={{ position: "absolute", left: -9999 }}>
                Target public ID
              </label>
              <input
                id="link-target"
                data-testid="link-target-input"
                value={linkTargetId}
                onChange={(e) => {
                  setLinkTargetId(e.target.value);
                  setLinkKind(tab);
                }}
                onFocus={() => setLinkKind(tab)}
                placeholder={`${TAB_LABELS[tab]} public ID (UUID)`}
                style={{ ...field, minWidth: 320 }}
              />
              <button
                type="submit"
                data-testid="link-submit"
                disabled={busy || !linkTargetId.trim()}
                style={{
                  padding: "0.45rem 1rem",
                  border: `1px solid ${busy || !linkTargetId.trim() ? T.line : T.navy}`,
                  borderRadius: 6,
                  background: busy || !linkTargetId.trim() ? T.soft : T.blue,
                  color: busy || !linkTargetId.trim() ? T.muted : "#fff",
                  fontWeight: 600,
                  cursor: busy || !linkTargetId.trim() ? "not-allowed" : "pointer",
                }}
              >
                Link
              </button>
            </form>
          )}

          <LinkTable
            tab={tab}
            detail={detail}
            canManage={canManage}
            busy={busy}
            onUnlink={(linkId) =>
              void runAction(
                () => regulatoryCases.unlinkTarget(tenantSlug, publicId, tab, linkId),
                "This case no longer accepts changes."
              )
            }
            tenantSlug={tenantSlug}
          />
        </section>
      )}

      {tab === "dossiers" && (
        <CaseDossiersPanel
          tenantSlug={tenantSlug}
          casePublicId={publicId}
          caseTerminal={c.is_terminal}
        />
      )}

      {tab === "packages" && (
        <section data-testid="tab-panel-packages">
          {/* A package is a deliberate assembly of exact document versions.
              Nothing here creates one automatically and nothing syncs dossier
              contents into one -- that is what makes a frozen manifest mean
              something. */}
          <PackagePanel
            tenantSlug={tenantSlug}
            casePublicId={publicId}
            caseTerminal={c.is_terminal}
          />
        </section>
      )}

      {tab === "evidence" && (
        <section data-testid="tab-panel-evidence">
          <p style={{ fontSize: "0.9rem", color: T.muted, lineHeight: 1.6 }}>
            Evidence is recorded against workflow items, not against the case. This case has{" "}
            <strong data-testid="evidence-count">
              {summary.evidence_links === null ? "an unknown number of" : summary.evidence_links}
            </strong>{" "}
            evidence link{summary.evidence_links === 1 ? "" : "s"} across its workflow items that
            you are permitted to see. Open a workflow item to review or change its evidence.
          </p>
          {detail.workflows.length === 0 && (
            <p data-testid="evidence-empty" style={{ fontSize: "0.9rem", color: T.muted }}>
              No workflow items are linked to this case yet.
            </p>
          )}
        </section>
      )}
    </main>
  );
}

function LinkTable({
  tab,
  detail,
  canManage,
  busy,
  onUnlink,
  tenantSlug,
}: {
  tab: "documents" | "workflows" | "checklists";
  detail: CaseDetail;
  canManage: boolean;
  busy: boolean;
  onUnlink: (linkPublicId: string) => void;
  tenantSlug: string;
}) {
  const rows =
    tab === "documents" ? detail.documents : tab === "workflows" ? detail.workflows : detail.checklists;

  if (rows.length === 0) {
    return (
      <p
        data-testid={`${tab}-empty`}
        style={{
          margin: 0,
          padding: "1.25rem 1rem",
          border: `1px solid ${T.line}`,
          borderRadius: 8,
          background: T.panel,
          color: T.muted,
          fontSize: "0.9rem",
        }}
      >
        Nothing linked yet.
      </p>
    );
  }

  return (
    <div style={{ overflowX: "auto" }}>
      <table data-testid={`${tab}-table`} style={{ width: "100%", borderCollapse: "separate", borderSpacing: 0 }}>
        <thead>
          <tr style={{ textAlign: "left", borderBottom: `1px solid ${T.line}` }}>
            <th style={head}>{tab === "documents" ? "Document" : tab === "workflows" ? "Workflow item" : "Checklist"}</th>
            <th style={head}>Detail</th>
            <th style={head}>Linked</th>
            {canManage && <th style={head} />}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.public_id} style={{ borderBottom: `1px solid ${T.line}` }}>
              <td style={cell}>
                {tab === "documents" && "document" in row && row.document ? (
                  <Link href={`/documents/${row.document_public_id}?tenant=${tenantSlug}`}>
                    {row.document.title}
                  </Link>
                ) : tab === "workflows" && "workflow" in row && row.workflow ? (
                  <Link href={`/workflows/${row.workflow_public_id}?tenant=${tenantSlug}`}>
                    {row.workflow.title}
                  </Link>
                ) : tab === "checklists" && "checklist" in row && row.checklist ? (
                  <span>{row.execution_public_id.slice(0, 8)}…</span>
                ) : (
                  <RestrictedCell />
                )}
              </td>
              <td style={{ ...cell, color: T.muted }}>
                {"document" in row && row.document
                  ? `v${row.document.current_version_number ?? "—"} · ${row.document.status}`
                  : "workflow" in row && row.workflow
                    ? row.workflow.state
                    : "checklist" in row && row.checklist
                      ? row.checklist.status
                      : "—"}
              </td>
              <td style={{ ...cell, color: T.muted }}>
                {new Date(row.linked_at).toLocaleDateString()}
                {row.linked_by ? ` by ${row.linked_by.full_name}` : ""}
              </td>
              {canManage && (
                <td style={{ ...cell, textAlign: "right" }}>
                  <button
                    type="button"
                    data-testid={`unlink-${row.public_id}`}
                    disabled={busy}
                    onClick={() => onUnlink(row.public_id)}
                    style={ghostButton(busy)}
                  >
                    Unlink
                  </button>
                </td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function RegulatoryCaseDetailPage() {
  return (
    <Suspense fallback={<p>Loading…</p>}>
      <CaseDetailInner />
    </Suspense>
  );
}
