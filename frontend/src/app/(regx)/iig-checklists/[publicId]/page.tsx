"use client";

import { Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams, useParams } from "next/navigation";
import Link from "next/link";
import {
  iigChecklists,
  type ChecklistDefinition,
  type ChecklistVersion,
  type ChecklistVersionStatus,
  ApiError,
} from "@/lib/api";

const STATUS_COLOURS: Record<ChecklistVersionStatus, string> = {
  draft: "#314155",
  under_review: "#8a5a10",
  returned: "#a8690f",
  approved: "#0e6b6b",
  active: "#1a6b46",
  superseded: "#66768b",
  rejected: "#8f2c20",
  retired: "#66768b",
};

function StatusBadge({ status }: { status: ChecklistVersionStatus }) {
  return (
    <span
      style={{
        fontSize: 11,
        fontWeight: 600,
        padding: "2px 7px",
        borderRadius: 4,
        background: STATUS_COLOURS[status] ?? "#314155",
        color: "#fff",
        textTransform: "uppercase",
      }}
    >
      {status.replace(/_/g, " ")}
    </span>
  );
}

function DefinitionDetailInner() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const params = useParams<{ publicId: string }>();
  const tenantSlug = searchParams.get("tenant") ?? "";
  const publicId = params.publicId;

  const [definition, setDefinition] = useState<ChecklistDefinition | null>(null);
  const [versions, setVersions] = useState<ChecklistVersion[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [actionBusy, setActionBusy] = useState(false);

  function load() {
    if (!tenantSlug) return;
    setLoading(true);
    Promise.all([
      iigChecklists.definitions.get(tenantSlug, publicId),
      iigChecklists.versions.listForDefinition(tenantSlug, publicId),
    ])
      .then(([def, versionsResp]) => {
        setDefinition(def);
        setVersions(versionsResp.results);
      })
      .catch((err: unknown) => {
        if (err instanceof ApiError && err.status === 404) {
          setError("Checklist definition not found.");
        } else if (err instanceof ApiError && (err.status === 403 || err.status === 401)) {
          router.push(`/signin?next=${encodeURIComponent(window.location.pathname + window.location.search)}`);
        } else {
          setError("Failed to load checklist definition.");
        }
      })
      .finally(() => setLoading(false));
  }

  useEffect(() => {
    if (!tenantSlug) {
      router.push("/tenants");
      return;
    }
    load();
  }, [tenantSlug, publicId]); // eslint-disable-line react-hooks/exhaustive-deps

  async function createVersion() {
    setActionBusy(true);
    setActionError(null);
    try {
      await iigChecklists.versions.create(tenantSlug, publicId);
      load();
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : "Could not create a new version.");
    } finally {
      setActionBusy(false);
    }
  }

  async function deleteDefinition() {
    setActionBusy(true);
    setActionError(null);
    try {
      await iigChecklists.definitions.remove(tenantSlug, publicId);
      router.push(`/iig-checklists?tenant=${tenantSlug}`);
    } catch (err) {
      setActionError(
        err instanceof ApiError ? err.message : "Only an empty, never-submitted draft may be deleted."
      );
      setActionBusy(false);
    }
  }

  async function cloneDefinition(sourceVersion: ChecklistVersion) {
    setActionBusy(true);
    setActionError(null);
    try {
      const result = await iigChecklists.definitions.clone(tenantSlug, publicId, {
        source_version_public_id: sourceVersion.public_id,
        target_scope_type: definition!.scope_type,
        target_tenant_public_id: definition!.tenant_public_id ?? undefined,
        new_code: `${definition!.code}-CLONE`,
        new_title: `${definition!.title} (clone)`,
      });
      router.push(`/iig-checklists/${result.public_id}?tenant=${tenantSlug}`);
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : "Clone failed.");
      setActionBusy(false);
    }
  }

  if (!tenantSlug) return null;
  if (loading) return <main style={{ maxWidth: 800, margin: "2rem auto" }}>Loading…</main>;
  if (error || !definition) {
    return (
      <main style={{ maxWidth: 800, margin: "2rem auto", padding: "0 1rem" }}>
        <p role="alert" style={{ color: "#c0392b" }}>
          {error ?? "Checklist definition not found."}
        </p>
      </main>
    );
  }

  const hasEditableVersion = versions.some(
    (v) => v.status === "draft" || v.status === "returned"
  );
  const canDeleteAsEmptyDraft =
    versions.length === 1 &&
    versions.every((v) => v.status === "draft" && !v.submitted_by_email);
  const clonableVersion = versions.find((v) =>
    ["approved", "active", "superseded"].includes(v.status)
  );

  return (
    <main style={{ maxWidth: 800, margin: "2rem auto", padding: "0 1rem" }}>
      <div style={{ marginBottom: "0.5rem" }}>
        <Link href={`/iig-checklists?tenant=${tenantSlug}`} style={{ color: "#045e8f", fontSize: 13, textDecoration: "none" }}>
          ← Checklist definitions
        </Link>
      </div>
      <h1 style={{ margin: "0 0 0.25rem" }}>{definition.title}</h1>
      <p style={{ color: "#66768b", fontSize: 13, marginTop: 0, fontFamily: "monospace" }}>
        {definition.code} · {definition.scope_type.replace(/_/g, " ")}
      </p>
      {definition.description && (
        <p style={{ fontSize: 14, color: "#314155" }}>{definition.description}</p>
      )}

      <div style={{ display: "flex", gap: 8, marginTop: "1rem", flexWrap: "wrap" }}>
        {canDeleteAsEmptyDraft && (
          <button onClick={deleteDefinition} disabled={actionBusy} style={{ ...buttonStyle, background: "#8f2c20" }}>
            Delete draft definition
          </button>
        )}
        {clonableVersion && (
          <button onClick={() => cloneDefinition(clonableVersion)} disabled={actionBusy} style={{ ...buttonStyle, background: "#314155" }}>
            Clone into new definition
          </button>
        )}
      </div>

      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginTop: "1.5rem", marginBottom: "0.75rem" }}>
        <h2 style={{ margin: 0, fontSize: 16 }}>Versions</h2>
        {!hasEditableVersion && (
          <button onClick={createVersion} disabled={actionBusy} style={buttonStyle}>
            Create new version
          </button>
        )}
      </div>

      {actionError && (
        <p role="alert" style={{ color: "#c0392b", fontSize: 13, marginBottom: 8 }}>
          {actionError}
        </p>
      )}

      {versions.length === 0 ? (
        <p style={{ color: "#66768b", fontSize: 14 }}>No versions yet.</p>
      ) : (
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 14 }}>
          <thead>
            <tr style={{ borderBottom: "2px solid #dce7f4", textAlign: "left" }}>
              <th style={{ padding: "8px 12px" }} scope="col">
                Version
              </th>
              <th style={{ padding: "8px 12px" }} scope="col">
                Status
              </th>
              <th style={{ padding: "8px 12px" }} scope="col">
                Effective date
              </th>
            </tr>
          </thead>
          <tbody>
            {versions.map((v) => (
              <tr key={v.public_id} style={{ borderBottom: "1px solid #f4f8fe" }}>
                <td style={{ padding: "10px 12px" }}>
                  <Link
                    href={`/iig-checklists/versions/${v.public_id}?tenant=${tenantSlug}`}
                    style={{ color: "#045e8f", textDecoration: "none" }}
                  >
                    v{v.version_number}
                  </Link>
                </td>
                <td style={{ padding: "10px 12px" }}>
                  <StatusBadge status={v.status} />
                </td>
                <td style={{ padding: "10px 12px", color: "#66768b", fontSize: 12 }}>
                  {v.effective_date ?? "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <p style={{ fontSize: 12, color: "#66768b", marginTop: 16 }}>
        This screen governs checklist structure and lifecycle only. It never displays
        or produces checklist execution responses or calculation outcomes.
      </p>
    </main>
  );
}

const buttonStyle: React.CSSProperties = {
  background: "#045e8f",
  color: "#fff",
  border: "none",
  borderRadius: 6,
  padding: "8px 18px",
  cursor: "pointer",
  fontWeight: 600,
  fontSize: 13,
};

export default function DefinitionDetailPage() {
  return (
    <Suspense>
      <DefinitionDetailInner />
    </Suspense>
  );
}
