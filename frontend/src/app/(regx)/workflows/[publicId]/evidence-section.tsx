"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import {
  workflowEvidence,
  type WorkflowEvidenceLink,
  type WorkflowState,
  ApiError,
} from "@/lib/api";

/**
 * Evidence section of the workflow detail page.
 *
 * Deliberately has NO upload control. The document platform owns uploads; a
 * second implementation here would duplicate storage, checksum and scan
 * handling. Users needing a new document go to the Documents module and come
 * back with a version id.
 *
 * Backend is authoritative for everything: it decides whether evidence may
 * change, and whether document detail is visible at all.
 */

/** Mirrors the backend rule. Advisory only -- the API returns 409 regardless. */
const EVIDENCE_MUTABLE_STATES: WorkflowState[] = ["draft"];

const LOCK_EXPLANATION: Record<WorkflowState, string> = {
  draft: "",
  submitted: "Evidence is locked while this item is awaiting review.",
  in_review: "Evidence is locked while this item is under review.",
  approved: "This item is approved. Its evidence set is now permanent.",
  rejected: "Evidence is locked. Return the item to draft to change it.",
  cancelled: "This item is cancelled. Its evidence set is now permanent.",
};

export function EvidenceSection({
  tenantSlug,
  workflowPublicId,
  state,
  canManage,
}: {
  tenantSlug: string;
  workflowPublicId: string;
  state: WorkflowState;
  canManage: boolean;
}) {
  const [links, setLinks] = useState<WorkflowEvidenceLink[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [versionId, setVersionId] = useState("");
  const [label, setLabel] = useState("");
  const [busy, setBusy] = useState(false);

  const mutable = EVIDENCE_MUTABLE_STATES.includes(state);

  function load(): Promise<void> {
    setLoading(true);
    return workflowEvidence
      .list(tenantSlug, workflowPublicId)
      .then((rows) => {
        setLinks(rows);
        setError(null);
      })
      .catch(() => setError("Failed to load evidence."))
      .finally(() => setLoading(false));
  }

  useEffect(() => {
    void load();
  }, [tenantSlug, workflowPublicId]); // eslint-disable-line react-hooks/exhaustive-deps

  async function handleLink(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await workflowEvidence.link(tenantSlug, workflowPublicId, {
        document_version_public_id: versionId.trim(),
        label: label.trim(),
      });
      setVersionId("");
      setLabel("");
      await load();
    } catch (err: unknown) {
      if (err instanceof ApiError && err.status === 409) {
        setError("Already linked, or this item no longer accepts evidence changes.");
        await load();
      } else if (err instanceof ApiError && err.status === 403) {
        setError("You do not have permission to link documents in this tenant.");
      } else if (err instanceof ApiError && err.status === 400) {
        setError("That document version is not available to link as evidence.");
      } else {
        setError("Could not link evidence.");
      }
    } finally {
      setBusy(false);
    }
  }

  async function handleUnlink(evidencePublicId: string) {
    setBusy(true);
    setError(null);
    try {
      await workflowEvidence.unlink(tenantSlug, workflowPublicId, evidencePublicId);
      await load();
    } catch (err: unknown) {
      if (err instanceof ApiError && err.status === 409) {
        setError("This item no longer accepts evidence changes.");
        await load();
      } else {
        setError("Could not unlink evidence.");
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <section style={{ marginTop: "2rem" }} data-testid="evidence-section">
      <h2 style={{ fontSize: "1.1rem" }}>Evidence</h2>

      {error && (
        <p role="alert" data-testid="evidence-error" style={{ color: "#b91c1c" }}>
          {error}
        </p>
      )}

      {!mutable && (
        <p data-testid="evidence-locked" style={{ color: "#475569", fontSize: "0.9rem" }}>
          {LOCK_EXPLANATION[state]}
        </p>
      )}

      {loading && <p>Loading evidence…</p>}

      {!loading && links.length === 0 && (
        <p data-testid="evidence-empty">No documents linked as evidence.</p>
      )}

      {!loading && links.length > 0 && (
        <table style={{ width: "100%", borderCollapse: "collapse" }} data-testid="evidence-table">
          <thead>
            <tr style={{ textAlign: "left", borderBottom: "2px solid #e5e7eb" }}>
              <th style={{ padding: "0.4rem" }}>Document</th>
              <th style={{ padding: "0.4rem" }}>Version</th>
              <th style={{ padding: "0.4rem" }}>Label</th>
              <th style={{ padding: "0.4rem" }}>Linked</th>
              {mutable && canManage && <th style={{ padding: "0.4rem" }} />}
            </tr>
          </thead>
          <tbody>
            {links.map((row) => (
              <tr key={row.public_id} style={{ borderBottom: "1px solid #f1f5f9" }}>
                <td style={{ padding: "0.4rem" }}>
                  {row.document ? (
                    // Only linked through when the caller can actually open it.
                    <Link
                      href={`/documents/${row.document_public_id}?tenant=${tenantSlug}`}
                      data-testid="evidence-document-link"
                    >
                      {row.document.title}
                    </Link>
                  ) : (
                    // No documents.view: identity only, and say why rather than
                    // showing a link that would 403.
                    <span data-testid="evidence-restricted" title="Requires document access">
                      <code style={{ fontSize: "0.8rem" }}>
                        {row.document_public_id.slice(0, 8)}…
                      </code>{" "}
                      <em style={{ color: "#64748b" }}>(no document access)</em>
                    </span>
                  )}
                </td>
                <td style={{ padding: "0.4rem" }}>
                  {row.document ? (
                    <span title={row.document.sha256_checksum}>
                      v{row.document.version_number}
                    </span>
                  ) : (
                    <code style={{ fontSize: "0.8rem" }}>
                      {row.document_version_public_id.slice(0, 8)}…
                    </code>
                  )}
                </td>
                <td style={{ padding: "0.4rem" }}>{row.label || "—"}</td>
                <td style={{ padding: "0.4rem" }}>
                  {new Date(row.linked_at).toLocaleDateString()}
                  {row.linked_by ? ` by ${row.linked_by.email}` : ""}
                </td>
                {mutable && canManage && (
                  <td style={{ padding: "0.4rem" }}>
                    <button
                      type="button"
                      data-testid={`unlink-${row.public_id}`}
                      disabled={busy}
                      onClick={() => void handleUnlink(row.public_id)}
                      style={{ padding: "0.25rem 0.6rem", borderRadius: 6 }}
                    >
                      Unlink
                    </button>
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {mutable && canManage && (
        <form onSubmit={handleLink} style={{ marginTop: "1rem" }} data-testid="evidence-form">
          <p style={{ fontSize: "0.9rem", color: "#475569" }}>
            Link an existing document version as evidence. To add a new document, upload it in{" "}
            <Link href={`/documents?tenant=${tenantSlug}`}>Documents</Link> first — this screen
            does not upload files.
          </p>
          <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
            <input
              aria-label="Document version ID"
              data-testid="evidence-version-input"
              value={versionId}
              onChange={(e) => setVersionId(e.target.value)}
              placeholder="Document version ID (UUID)"
              style={{ padding: "0.4rem", minWidth: 320 }}
            />
            <input
              aria-label="Label"
              data-testid="evidence-label-input"
              value={label}
              onChange={(e) => setLabel(e.target.value)}
              placeholder="Label (optional)"
              style={{ padding: "0.4rem" }}
            />
            <button
              type="submit"
              data-testid="evidence-link-submit"
              disabled={busy || versionId.trim() === ""}
              style={{ padding: "0.4rem 0.9rem", borderRadius: 6 }}
            >
              Link evidence
            </button>
          </div>
        </form>
      )}
    </section>
  );
}
