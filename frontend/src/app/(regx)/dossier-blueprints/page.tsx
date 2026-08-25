"use client";

import { Suspense, useEffect, useState, type FormEvent } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import {
  ApiError,
  dossierBlueprints,
  type BlueprintPermissions,
  type DossierBlueprint,
} from "@/lib/api";
import { ActiveMeaningNote, ArchivedBadge, VersionStatusBadge } from "./status-badge";

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

const head: React.CSSProperties = {
  padding: "0.5rem",
  fontSize: "0.72rem",
  fontWeight: 700,
  letterSpacing: "0.05em",
  textTransform: "uppercase",
  color: T.muted,
};

const cell: React.CSSProperties = {
  padding: "0.6rem 0.5rem",
  fontSize: "0.9rem",
  color: T.text,
  verticalAlign: "middle",
};

function BlueprintLibraryInner() {
  const params = useSearchParams();
  const tenantSlug = params.get("tenant") ?? "";

  const [rows, setRows] = useState<DossierBlueprint[]>([]);
  const [permissions, setPermissions] = useState<BlueprintPermissions | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [includeArchived, setIncludeArchived] = useState(false);
  const [showCreate, setShowCreate] = useState(false);
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);

  function load(): Promise<void> {
    setLoading(true);
    return dossierBlueprints
      .list(tenantSlug, { search: search.trim() || undefined, includeArchived })
      .then((r) => {
        setRows(r.results);
        setPermissions(r.permissions);
        setError(null);
      })
      .catch(() => setError("Failed to load the blueprint library."))
      .finally(() => setLoading(false));
  }

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tenantSlug, includeArchived]);

  async function create(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      await dossierBlueprints.create(tenantSlug, { name: name.trim() });
      setName("");
      setShowCreate(false);
      await load();
    } catch (err: unknown) {
      // Reload first, then set the message: load() clears errors on success.
      await load();
      if (err instanceof ApiError && err.status === 403)
        setError("You do not have permission to create blueprints in this tenant.");
      else if (err instanceof ApiError && err.status === 409)
        setError("A blueprint with that name already exists.");
      else setError("Could not create the blueprint.");
    } finally {
      setBusy(false);
    }
  }

  const canCreate = permissions?.can_create ?? false;

  return (
    <main style={{ padding: "1.5rem", maxWidth: 1100, margin: "0 auto" }}>
      <header style={{ marginBottom: "1.25rem" }}>
        <h1 style={{ margin: 0, color: T.ink, fontSize: "1.5rem" }}>Blueprint library</h1>
        <p
          style={{
            margin: "0.4rem 0 0.6rem",
            color: T.muted,
            fontSize: "0.92rem",
            lineHeight: 1.6,
            maxWidth: 760,
          }}
        >
          A blueprint is a reusable dossier outline: ordered sections you can version and stamp
          into a case. Once a dossier is created from a version it is independent — publishing a
          later version never changes it.
        </p>
        <ActiveMeaningNote />
      </header>

      <div
        style={{
          display: "flex",
          gap: "0.6rem",
          alignItems: "center",
          flexWrap: "wrap",
          marginBottom: "1rem",
        }}
      >
        <label htmlFor="blueprint-search" style={{ position: "absolute", left: -9999 }}>
          Search blueprints
        </label>
        <input
          id="blueprint-search"
          data-testid="blueprint-search"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") void load();
          }}
          placeholder="Search by name"
          style={{ ...field, minWidth: 240 }}
        />
        <button type="button" data-testid="blueprint-search-go" onClick={() => void load()} style={secondary}>
          Search
        </button>
        <label
          style={{ display: "flex", alignItems: "center", gap: "0.35rem", fontSize: "0.88rem", color: T.text }}
        >
          <input
            type="checkbox"
            data-testid="include-archived"
            checked={includeArchived}
            onChange={(e) => setIncludeArchived(e.target.checked)}
          />
          Show archived
        </label>
        <span style={{ flex: 1 }} />
        {canCreate && (
          <button
            type="button"
            data-testid="new-blueprint"
            onClick={() => setShowCreate((v) => !v)}
            style={primary}
          >
            {showCreate ? "Close" : "New blueprint"}
          </button>
        )}
      </div>

      {error && (
        <p role="alert" data-testid="blueprint-error" style={alertStyle}>
          {error}
        </p>
      )}

      {showCreate && canCreate && (
        <form
          onSubmit={create}
          data-testid="create-blueprint-form"
          aria-label="Create blueprint form"
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
          <label htmlFor="blueprint-name" style={{ position: "absolute", left: -9999 }}>
            Blueprint name
          </label>
          <input
            id="blueprint-name"
            data-testid="blueprint-name-input"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Blueprint name"
            style={{ ...field, flex: 1, minWidth: 240 }}
          />
          <button
            type="submit"
            data-testid="create-blueprint-submit"
            disabled={busy || !name.trim()}
            style={busy || !name.trim() ? disabledPrimary : primary}
          >
            Create
          </button>
        </form>
      )}

      {loading && <p style={{ color: T.muted, fontSize: "0.9rem" }}>Loading blueprints…</p>}

      {!loading && rows.length === 0 && (
        <p data-testid="blueprints-empty" style={emptyStyle}>
          No blueprints yet.
        </p>
      )}

      {!loading && rows.length > 0 && (
        <div style={{ overflowX: "auto" }}>
          <table
            data-testid="blueprints-table"
            style={{ width: "100%", borderCollapse: "separate", borderSpacing: 0 }}
          >
            <thead>
              <tr style={{ textAlign: "left", borderBottom: `1px solid ${T.line}` }}>
                <th style={head}>Name</th>
                <th style={head}>Current version</th>
                <th style={head}>Status</th>
                <th style={head}>Owner</th>
                <th style={head}>In use</th>
                <th style={head}>Updated</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((b) => (
                <tr key={b.public_id} style={{ borderBottom: `1px solid ${T.line}` }}>
                  <td style={{ ...cell, fontWeight: 600 }}>
                    <Link
                      href={`/dossier-blueprints/${b.public_id}?tenant=${tenantSlug}`}
                      data-testid="blueprint-link"
                    >
                      {b.name}
                    </Link>
                    {b.is_archived && (
                      <span style={{ marginLeft: "0.5rem" }}>
                        <ArchivedBadge />
                      </span>
                    )}
                  </td>
                  <td style={cell}>
                    {b.current_version_number ? `v${b.current_version_number}` : "—"}
                    <span style={{ color: T.muted, fontSize: "0.8rem", marginLeft: "0.4rem" }}>
                      ({b.version_count ?? 0} total)
                    </span>
                  </td>
                  <td style={cell}>
                    {b.current_version_status ? (
                      <VersionStatusBadge status={b.current_version_status} />
                    ) : (
                      <span style={{ color: T.muted }}>No published version</span>
                    )}
                  </td>
                  <td style={{ ...cell, color: b.owner ? T.text : T.muted }}>
                    {b.owner ? b.owner.full_name : "—"}
                  </td>
                  <td style={cell} data-testid="usage-count">
                    {b.instantiation_count ?? 0}
                  </td>
                  <td style={{ ...cell, color: T.muted }}>
                    {new Date(b.updated_at).toLocaleDateString()}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </main>
  );
}

const primary: React.CSSProperties = {
  padding: "0.45rem 0.9rem",
  border: `1px solid ${T.navy}`,
  borderRadius: 8,
  background: T.blue,
  color: "#fff",
  fontWeight: 600,
  cursor: "pointer",
  whiteSpace: "nowrap",
};

const disabledPrimary: React.CSSProperties = {
  ...primary,
  border: `1px solid ${T.line}`,
  background: T.soft,
  color: T.muted,
  cursor: "not-allowed",
};

const secondary: React.CSSProperties = {
  padding: "0.45rem 0.9rem",
  border: `1px solid ${T.line}`,
  borderRadius: 8,
  background: "#fff",
  color: T.blue,
  fontWeight: 600,
  cursor: "pointer",
};

const alertStyle: React.CSSProperties = {
  margin: "0 0 0.9rem",
  padding: "0.6rem 0.8rem",
  border: "1px solid #f3c9c4",
  borderRadius: 6,
  background: "#fdf3f2",
  color: "#8f2c20",
  fontSize: "0.88rem",
};

const emptyStyle: React.CSSProperties = {
  margin: 0,
  padding: "1.25rem 1rem",
  border: `1px solid ${T.line}`,
  borderRadius: 8,
  background: T.panel,
  color: T.muted,
  fontSize: "0.9rem",
};

export default function BlueprintLibraryPage() {
  return (
    <Suspense fallback={null}>
      <BlueprintLibraryInner />
    </Suspense>
  );
}
