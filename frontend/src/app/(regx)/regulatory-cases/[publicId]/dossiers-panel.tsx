"use client";

import { useEffect, useState, type FormEvent } from "react";
import Link from "next/link";
import {
  submissionDossiers,
  ApiError,
  type DossierPermissions,
  type SubmissionDossier,
} from "@/lib/api";
import { DossierStatusBadge } from "../../submission-dossiers/readiness-badge";

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

/** The dossier list for one case, rendered inside the case workspace. */
export function CaseDossiersPanel({
  tenantSlug,
  casePublicId,
  caseTerminal,
}: {
  tenantSlug: string;
  casePublicId: string;
  caseTerminal: boolean;
}) {
  const [dossiers, setDossiers] = useState<SubmissionDossier[]>([]);
  const [permissions, setPermissions] = useState<DossierPermissions | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [title, setTitle] = useState("");
  const [busy, setBusy] = useState(false);

  function load(): Promise<void> {
    setLoading(true);
    return submissionDossiers
      .listForCase(tenantSlug, casePublicId)
      .then((r) => {
        setDossiers(r.results);
        setPermissions(r.permissions);
        setError(null);
      })
      .catch(() => setError("Failed to load dossiers."))
      .finally(() => setLoading(false));
  }

  useEffect(() => {
    void load();
  }, [tenantSlug, casePublicId]); // eslint-disable-line react-hooks/exhaustive-deps

  async function create(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      await submissionDossiers.create(tenantSlug, casePublicId, { title: title.trim() });
      setTitle("");
      setShowCreate(false);
      await load();
    } catch (err: unknown) {
      // Reload first, then set the message: load() clears errors on success.
      await load();
      if (err instanceof ApiError && err.status === 403)
        setError("You do not have permission to create dossiers in this tenant.");
      else if (err instanceof ApiError && err.status === 400)
        setError("Check the title and try again.");
      else setError("Could not create the dossier.");
    } finally {
      setBusy(false);
    }
  }

  // Advisory only -- the API re-checks. A terminal case should not invite work
  // that the backend would refuse.
  const canCreate = (permissions?.can_create ?? false) && !caseTerminal;

  return (
    <section data-testid="tab-panel-dossiers">
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          gap: "1rem",
          flexWrap: "wrap",
          marginBottom: "0.9rem",
        }}
      >
        <p style={{ margin: 0, fontSize: "0.9rem", color: T.muted, lineHeight: 1.6 }}>
          A dossier is the submission outline for this case: ordered sections with owners, due
          dates, blockers and internal readiness. Build one by hand, or start from a blueprint.
        </p>
        {/* Manual creation stays. Blueprints are a convenience and a control,
            never a requirement, so removing the manual path would be a
            regression dressed up as a feature. */}
        <Link
          href={`/dossier-blueprints?tenant=${tenantSlug}`}
          data-testid="create-from-blueprint"
          style={{
            padding: "0.45rem 0.9rem",
            border: `1px solid ${T.line}`,
            borderRadius: 8,
            background: "#fff",
            color: T.blue,
            fontWeight: 600,
            whiteSpace: "nowrap",
            textDecoration: "none",
          }}
        >
          Create from blueprint
        </Link>
        {canCreate && (
          <button
            type="button"
            data-testid="new-dossier"
            onClick={() => setShowCreate((v) => !v)}
            style={{
              padding: "0.45rem 0.9rem",
              border: `1px solid ${T.navy}`,
              borderRadius: 8,
              background: T.blue,
              color: "#fff",
              fontWeight: 600,
              cursor: "pointer",
              whiteSpace: "nowrap",
            }}
          >
            {showCreate ? "Close" : "New dossier"}
          </button>
        )}
      </div>

      {error && (
        <p
          role="alert"
          data-testid="dossiers-error"
          style={{
            margin: "0 0 0.9rem",
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

      {showCreate && canCreate && (
        <form
          onSubmit={create}
          data-testid="create-dossier-form"
          aria-label="Create dossier form"
          style={{
            display: "flex",
            gap: "0.5rem",
            flexWrap: "wrap",
            marginBottom: "1rem",
            padding: "0.9rem",
            border: `1px solid ${T.line}`,
            borderRadius: 8,
            background: T.panel,
          }}
        >
          <label htmlFor="dossier-title" style={{ position: "absolute", left: -9999 }}>
            Dossier title
          </label>
          <input
            id="dossier-title"
            data-testid="dossier-title-input"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="Dossier title"
            style={{ ...field, flex: 1, minWidth: 240 }}
          />
          <button
            type="submit"
            data-testid="create-dossier-submit"
            disabled={busy || !title.trim()}
            style={{
              padding: "0.45rem 1rem",
              border: `1px solid ${busy || !title.trim() ? T.line : T.navy}`,
              borderRadius: 6,
              background: busy || !title.trim() ? T.soft : T.blue,
              color: busy || !title.trim() ? T.muted : "#fff",
              fontWeight: 600,
              cursor: busy || !title.trim() ? "not-allowed" : "pointer",
            }}
          >
            Create
          </button>
        </form>
      )}

      {loading && <p style={{ color: T.muted, fontSize: "0.9rem" }}>Loading dossiers…</p>}

      {!loading && dossiers.length === 0 && (
        <p
          data-testid="dossiers-empty"
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
          No dossiers yet for this case.
        </p>
      )}

      {!loading && dossiers.length > 0 && (
        <div style={{ overflowX: "auto" }}>
          <table
            data-testid="dossiers-table"
            style={{ width: "100%", borderCollapse: "separate", borderSpacing: 0 }}
          >
            <thead>
              <tr style={{ textAlign: "left", borderBottom: `1px solid ${T.line}` }}>
                <th style={head}>Dossier</th>
                <th style={head}>Owner</th>
                <th style={head}>Target date</th>
                <th style={head}>Status</th>
              </tr>
            </thead>
            <tbody>
              {dossiers.map((d) => (
                <tr key={d.public_id} style={{ borderBottom: `1px solid ${T.line}` }}>
                  <td style={{ ...cell, fontWeight: 600 }}>
                    <Link
                      href={`/submission-dossiers/${d.public_id}?tenant=${tenantSlug}`}
                      data-testid="dossier-link"
                    >
                      {d.title}
                    </Link>
                  </td>
                  <td style={{ ...cell, color: d.owner ? T.text : T.muted }}>
                    {d.owner ? d.owner.full_name : "—"}
                  </td>
                  <td style={{ ...cell, color: d.target_date ? T.text : T.muted }}>
                    {d.target_date ? new Date(d.target_date).toLocaleDateString() : "—"}
                  </td>
                  <td style={cell}>
                    <DossierStatusBadge status={d.status} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
