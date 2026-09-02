"use client";

import { Suspense, useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useParams, useSearchParams } from "next/navigation";
import { ApiError, dossierBlueprints, type BlueprintDetail } from "@/lib/api";
import { ActiveMeaningNote, ArchivedBadge, VersionStatusBadge } from "../status-badge";

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

function BlueprintDetailInner() {
  const params = useParams<{ publicId: string }>();
  const search = useSearchParams();
  const tenantSlug = search.get("tenant") ?? "";
  const publicId = params.publicId;

  const [detail, setDetail] = useState<BlueprintDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback((): Promise<void> => {
    setLoading(true);
    return dossierBlueprints
      .get(tenantSlug, publicId)
      .then((d) => {
        setDetail(d);
        setError(null);
      })
      .catch((err: unknown) => {
        if (err instanceof ApiError && err.status === 404) setError("Blueprint not found.");
        else setError("Failed to load this blueprint.");
      })
      .finally(() => setLoading(false));
  }, [tenantSlug, publicId]);

  useEffect(() => {
    void load();
  }, [load]);

  async function act(fn: () => Promise<unknown>, conflictMessage: string) {
    setBusy(true);
    try {
      await fn();
      await load();
    } catch (err: unknown) {
      // Reload first, then set the message: load() clears errors on success.
      await load();
      if (err instanceof ApiError && err.status === 409) setError(conflictMessage);
      else if (err instanceof ApiError && err.status === 403)
        setError("You do not have permission to do that in this tenant.");
      else setError("The action could not be completed.");
    } finally {
      setBusy(false);
    }
  }

  if (loading && !detail) return <main style={page}>Loading blueprint…</main>;
  if (!detail)
    return (
      <main style={page}>
        <p role="alert" data-testid="blueprint-detail-error" style={alertStyle}>
          {error ?? "Blueprint not found."}
        </p>
      </main>
    );

  const p = detail.permissions;
  const latest = detail.versions[0] ?? null;
  const canStartNewVersion = p.can_create_version && !detail.is_archived;

  return (
    <main style={page}>
      <nav style={{ marginBottom: "0.75rem", fontSize: "0.85rem" }}>
        <Link href={`/dossier-blueprints?tenant=${tenantSlug}`} data-testid="back-to-library">
          ← Blueprint library
        </Link>
      </nav>

      <header style={{ marginBottom: "1.25rem" }}>
        <div style={{ display: "flex", alignItems: "center", gap: "0.6rem", flexWrap: "wrap" }}>
          <h1 style={{ margin: 0, color: T.ink, fontSize: "1.4rem" }} data-testid="blueprint-name">
            {detail.name}
          </h1>
          {detail.is_archived && <ArchivedBadge />}
        </div>
        {detail.description && (
          <p style={{ margin: "0.4rem 0 0", color: T.text, fontSize: "0.92rem", lineHeight: 1.6 }}>
            {detail.description}
          </p>
        )}
        <p style={{ margin: "0.4rem 0 0.6rem", color: T.muted, fontSize: "0.85rem" }}>
          Owner: {detail.owner ? detail.owner.full_name : "—"} · Used by{" "}
          <span data-testid="instantiation-count">{detail.instantiation_count ?? 0}</span> dossier
          {(detail.instantiation_count ?? 0) === 1 ? "" : "s"}
        </p>
        <ActiveMeaningNote />
      </header>

      {error && (
        <p role="alert" data-testid="blueprint-detail-error" style={alertStyle}>
          {error}
        </p>
      )}

      <section>
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            gap: "1rem",
            flexWrap: "wrap",
            marginBottom: "0.75rem",
          }}
        >
          <h2 style={{ margin: 0, color: T.ink, fontSize: "1.05rem" }}>Versions</h2>
          {canStartNewVersion && (
            <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
              {latest && (
                <button
                  type="button"
                  data-testid="new-version-from-latest"
                  disabled={busy}
                  onClick={() =>
                    void act(
                      () =>
                        dossierBlueprints.createVersion(tenantSlug, publicId, {
                          source_version_public_id: latest.public_id,
                        }),
                      "That version could not be copied."
                    )
                  }
                  style={busy ? disabledPrimary : primary}
                >
                  New version from v{latest.version_number}
                </button>
              )}
              <button
                type="button"
                data-testid="new-empty-version"
                disabled={busy}
                onClick={() =>
                  void act(
                    () => dossierBlueprints.createVersion(tenantSlug, publicId, {}),
                    "A new version could not be started."
                  )
                }
                style={secondary}
              >
                New empty version
              </button>
            </div>
          )}
        </div>

        <p style={{ margin: "0 0 0.75rem", color: T.muted, fontSize: "0.85rem", lineHeight: 1.6 }}>
          An active version is frozen. Corrections are made by starting a new version, which
          leaves every dossier already built from the old one untouched.
        </p>

        {detail.versions.length === 0 && (
          <p data-testid="versions-empty" style={emptyStyle}>
            No versions yet. Start one to begin adding sections.
          </p>
        )}

        {detail.versions.length > 0 && (
          <div style={{ overflowX: "auto" }}>
            <table
              data-testid="versions-table"
              style={{ width: "100%", borderCollapse: "separate", borderSpacing: 0 }}
            >
              <thead>
                <tr style={{ textAlign: "left", borderBottom: `1px solid ${T.line}` }}>
                  <th style={head}>Version</th>
                  <th style={head}>Status</th>
                  <th style={head}>Supersedes</th>
                  <th style={head}>Created</th>
                  <th style={head}>Activated</th>
                </tr>
              </thead>
              <tbody>
                {detail.versions.map((v) => (
                  <tr key={v.public_id} style={{ borderBottom: `1px solid ${T.line}` }}>
                    <td style={{ ...cell, fontWeight: 600 }}>
                      <Link
                        href={`/dossier-blueprints/${publicId}/versions/${v.public_id}?tenant=${tenantSlug}`}
                        data-testid="version-link"
                      >
                        v{v.version_number}
                      </Link>
                    </td>
                    <td style={cell}>
                      <VersionStatusBadge status={v.status} />
                    </td>
                    <td style={{ ...cell, color: T.muted }}>
                      {v.supersedes_public_id
                        ? `v${
                            detail.versions.find((x) => x.public_id === v.supersedes_public_id)
                              ?.version_number ?? "?"
                          }`
                        : "—"}
                    </td>
                    <td style={{ ...cell, color: T.muted }}>
                      {new Date(v.created_at).toLocaleDateString()}
                    </td>
                    <td style={{ ...cell, color: T.muted }}>
                      {v.activated_at ? new Date(v.activated_at).toLocaleDateString() : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {p.can_archive && !detail.is_archived && (
        <section style={{ marginTop: "1.5rem" }}>
          <button
            type="button"
            data-testid="archive-blueprint"
            disabled={busy}
            onClick={() =>
              void act(
                () => dossierBlueprints.archive(tenantSlug, publicId),
                "This blueprint is already archived."
              )
            }
            style={secondary}
          >
            Archive blueprint
          </button>
          <p style={{ margin: "0.4rem 0 0", color: T.muted, fontSize: "0.82rem" }}>
            Archiving hides the blueprint and frees its name. Existing versions and the dossiers
            built from them are unaffected.
          </p>
        </section>
      )}
    </main>
  );
}

const page: React.CSSProperties = { padding: "1.5rem", maxWidth: 1000, margin: "0 auto" };

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
  whiteSpace: "nowrap",
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

export default function BlueprintDetailPage() {
  return (
    <Suspense fallback={null}>
      <BlueprintDetailInner />
    </Suspense>
  );
}
