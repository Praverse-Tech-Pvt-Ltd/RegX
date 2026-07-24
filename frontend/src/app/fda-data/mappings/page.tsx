"use client";

import { Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import { fdaData, type TerminologyMapping, type MappingType, ApiError } from "@/lib/api";
import { ProvenanceLabel } from "@/components/ProvenanceLabel";

const STATUS_COLOURS: Record<string, string> = {
  proposed: "#374151",
  reviewed: "#1d4ed8",
  approved: "#166534",
  rejected: "#991b1b",
};

function StatusBadge({ status }: { status: string }) {
  return (
    <span
      style={{
        fontSize: 11,
        fontWeight: 600,
        padding: "2px 7px",
        borderRadius: 4,
        background: STATUS_COLOURS[status] ?? "#374151",
        color: "#fff",
        textTransform: "uppercase",
      }}
    >
      {status}
    </span>
  );
}

function MappingsPageInner() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const tenantSlug = searchParams.get("tenant") ?? "";

  const [items, setItems] = useState<TerminologyMapping[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [typeFilter, setTypeFilter] = useState<MappingType | "">("");
  const [statusFilter, setStatusFilter] = useState("");

  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [confirmAction, setConfirmAction] = useState<{
    action: "approve" | "reject";
    mapping: TerminologyMapping;
  } | null>(null);
  const [reason, setReason] = useState("");
  const [actionError, setActionError] = useState<string | null>(null);
  const [actionBusy, setActionBusy] = useState(false);

  function load() {
    if (!tenantSlug) return;
    setLoading(true);
    fdaData.mappings
      .list(tenantSlug, {
        type: typeFilter || undefined,
        status: statusFilter || undefined,
      })
      .then((resp) => setItems(resp.results))
      .catch((err: unknown) => {
        if (err instanceof ApiError && (err.status === 403 || err.status === 401)) {
          router.push("/signin");
        } else {
          setError("Failed to load terminology mappings.");
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
  }, [tenantSlug, typeFilter, statusFilter]); // eslint-disable-line react-hooks/exhaustive-deps

  async function confirmAndRun() {
    if (!confirmAction) return;
    setActionBusy(true);
    setActionError(null);
    try {
      const { action, mapping } = confirmAction;
      if (action === "approve") {
        await fdaData.mappings.approve(tenantSlug, mapping.mapping_type, mapping.public_id, reason);
      } else {
        await fdaData.mappings.reject(tenantSlug, mapping.mapping_type, mapping.public_id, reason);
      }
      setConfirmAction(null);
      setReason("");
      load();
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : "Action failed.");
    } finally {
      setActionBusy(false);
    }
  }

  function toggleSelect(publicId: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(publicId)) next.delete(publicId);
      else next.add(publicId);
      return next;
    });
  }

  async function bulkApproveSelected() {
    setActionBusy(true);
    setActionError(null);
    try {
      // Each selected mapping is approved individually against its own
      // scoped endpoint -- there is no unscoped "approve everything"
      // backend action, so a partial failure never silently approves
      // mappings beyond the ones this reviewer explicitly selected.
      const targets = items.filter((m) => selected.has(m.public_id) && m.status === "proposed");
      for (const mapping of targets) {
        await fdaData.mappings.approve(tenantSlug, mapping.mapping_type, mapping.public_id);
      }
      setSelected(new Set());
      load();
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : "Bulk approval failed partway through.");
    } finally {
      setActionBusy(false);
    }
  }

  if (!tenantSlug) return null;

  return (
    <main style={{ maxWidth: 1000, margin: "2rem auto", padding: "0 1rem" }}>
      <div style={{ marginBottom: "0.5rem" }}>
        <Link href={`/fda-data/releases?tenant=${tenantSlug}`} style={{ color: "#1d4ed8", fontSize: 13, textDecoration: "none" }}>
          ← FDA releases
        </Link>
      </div>
      <h1 style={{ margin: "0 0 0.5rem" }}>Terminology Mapping Review</h1>
      <p style={{ fontSize: 13, color: "#6b7280", marginTop: 0, marginBottom: "1rem" }}>
        No mapping is ever auto-approved. Every approval or rejection here requires an
        explicit reviewer action and is fully auditable.
      </p>

      <div style={{ display: "flex", gap: 12, marginBottom: "1rem" }}>
        <label style={{ fontSize: 13, color: "#374151" }}>
          Type:{" "}
          <select
            value={typeFilter}
            onChange={(e) => setTypeFilter(e.target.value as MappingType | "")}
            style={{ padding: "4px 8px", borderRadius: 4, border: "1px solid #d1d5db", fontSize: 13 }}
          >
            <option value="">All</option>
            <option value="route">Route</option>
            <option value="dosage_form">Dosage form</option>
            <option value="unit">Unit</option>
          </select>
        </label>
        <label style={{ fontSize: 13, color: "#374151" }}>
          Status:{" "}
          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
            style={{ padding: "4px 8px", borderRadius: 4, border: "1px solid #d1d5db", fontSize: 13 }}
          >
            <option value="">All</option>
            <option value="proposed">Proposed</option>
            <option value="approved">Approved</option>
            <option value="rejected">Rejected</option>
          </select>
        </label>
      </div>

      {selected.size > 0 && (
        <div style={{ marginBottom: 12 }}>
          <button onClick={bulkApproveSelected} disabled={actionBusy} style={{ ...actionButtonStyle, background: "#166534" }}>
            Approve {selected.size} selected
          </button>
        </div>
      )}

      {loading && <p>Loading…</p>}
      {error && (
        <p role="alert" style={{ color: "#b91c1c" }}>
          {error}
        </p>
      )}
      {!loading && items.length === 0 && !error && (
        <p style={{ color: "#6b7280" }}>No terminology mappings match this filter.</p>
      )}

      {items.length > 0 && (
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
          <thead>
            <tr style={{ borderBottom: "2px solid #e5e7eb", textAlign: "left" }}>
              <th style={{ padding: "8px 10px" }} scope="col">
                Select
              </th>
              <th style={{ padding: "8px 10px" }} scope="col">
                Source value <ProvenanceLabel kind="FDA_SOURCE" />
              </th>
              <th style={{ padding: "8px 10px" }} scope="col">
                Type
              </th>
              <th style={{ padding: "8px 10px" }} scope="col">
                Proposed controlled value
              </th>
              <th style={{ padding: "8px 10px" }} scope="col">
                Status
              </th>
              <th style={{ padding: "8px 10px" }} scope="col">
                Reviewer
              </th>
              <th style={{ padding: "8px 10px" }} scope="col">
                Affected records
              </th>
              <th style={{ padding: "8px 10px" }} scope="col">
                Actions
              </th>
            </tr>
          </thead>
          <tbody>
            {items.map((m) => (
              <tr key={m.public_id} style={{ borderBottom: "1px solid #f3f4f6" }}>
                <td style={{ padding: "8px 10px" }}>
                  <input
                    type="checkbox"
                    aria-label={`Select mapping ${m.source_raw_value}`}
                    checked={selected.has(m.public_id)}
                    onChange={() => toggleSelect(m.public_id)}
                  />
                </td>
                <td style={{ padding: "8px 10px", fontFamily: "monospace" }}>{m.source_raw_value}</td>
                <td style={{ padding: "8px 10px", color: "#6b7280" }}>{m.mapping_type.replace("_", " ")}</td>
                <td style={{ padding: "8px 10px" }}>{m.proposed_controlled_value ?? "—"}</td>
                <td style={{ padding: "8px 10px" }}>
                  <StatusBadge status={m.status} />
                </td>
                <td style={{ padding: "8px 10px", color: "#6b7280" }}>
                  {m.reviewer_email ?? "—"}
                  {m.reviewer_email && <ProvenanceLabel kind="REVIEWER_CONFIRMED" />}
                </td>
                <td style={{ padding: "8px 10px", color: "#6b7280" }}>{m.affected_record_count}</td>
                <td style={{ padding: "8px 10px" }}>
                  {m.status === "proposed" && (
                    <div style={{ display: "flex", gap: 6 }}>
                      <button
                        onClick={() => setConfirmAction({ action: "approve", mapping: m })}
                        style={{ ...actionButtonStyle, background: "#166534" }}
                      >
                        Approve
                      </button>
                      <button
                        onClick={() => setConfirmAction({ action: "reject", mapping: m })}
                        style={{ ...actionButtonStyle, background: "#991b1b" }}
                      >
                        Reject
                      </button>
                    </div>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {confirmAction && (
        <div
          role="dialog"
          aria-modal="true"
          aria-labelledby="mapping-confirm-title"
          style={{
            position: "fixed",
            inset: 0,
            background: "rgba(0,0,0,0.4)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
          }}
        >
          <div style={{ background: "#fff", borderRadius: 8, padding: "1.5rem", maxWidth: 420, width: "90%" }}>
            <h2 id="mapping-confirm-title" style={{ fontSize: 16, marginTop: 0 }}>
              {confirmAction.action === "approve" ? "Approve" : "Reject"} mapping
            </h2>
            <p style={{ fontSize: 13, color: "#6b7280" }}>
              {confirmAction.mapping.source_raw_value} →{" "}
              {confirmAction.mapping.proposed_controlled_value ?? "(no controlled value)"}. This
              affects {confirmAction.mapping.affected_record_count} record(s).
            </p>
            <label style={{ display: "block", fontSize: 13, marginBottom: 8 }}>
              Reason
              <textarea
                value={reason}
                onChange={(e) => setReason(e.target.value)}
                rows={2}
                style={{ display: "block", width: "100%", marginTop: 4, padding: "6px 8px", border: "1px solid #d1d5db", borderRadius: 4, boxSizing: "border-box" }}
              />
            </label>
            {actionError && (
              <p role="alert" style={{ color: "#b91c1c", fontSize: 13, marginBottom: 8 }}>
                {actionError}
              </p>
            )}
            <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
              <button
                onClick={() => {
                  setConfirmAction(null);
                  setActionError(null);
                  setReason("");
                }}
                style={{ ...actionButtonStyle, background: "#6b7280" }}
              >
                Cancel
              </button>
              <button onClick={confirmAndRun} disabled={actionBusy} style={{ ...actionButtonStyle, background: "#1d4ed8" }}>
                {actionBusy ? "Working…" : "Confirm"}
              </button>
            </div>
          </div>
        </div>
      )}
    </main>
  );
}

const actionButtonStyle: React.CSSProperties = {
  color: "#fff",
  border: "none",
  borderRadius: 6,
  padding: "6px 12px",
  cursor: "pointer",
  fontWeight: 600,
  fontSize: 12,
};

export default function MappingsPage() {
  return (
    <Suspense>
      <MappingsPageInner />
    </Suspense>
  );
}
