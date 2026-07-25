"use client";

import { Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import { fdaData, type TerminologyMapping, type MappingType, ApiError } from "@/lib/api";
import { ProvenanceLabel } from "@/components/ProvenanceLabel";

const STATUS_COLOURS: Record<string, string> = {
  proposed: "#374151",
  reviewed: "#1d4ed8",
  under_review: "#b45309",
  approved: "#166534",
  rejected: "#991b1b",
  returned: "#6d28d9",
};

type MappingAction = "submit_review" | "approve" | "reject" | "return";

const ACTION_LABELS: Record<MappingAction, string> = {
  submit_review: "Submit for review",
  approve: "Approve",
  reject: "Reject",
  return: "Return for correction",
};

const TERMINAL_STATUSES = new Set(["approved", "rejected"]);

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
      {/* Text label, never colour alone, communicates status. */}
      {status.replace("_", " ")}
    </span>
  );
}

const TYPE_TABS: { value: MappingType | ""; label: string }[] = [
  { value: "", label: "All" },
  { value: "route", label: "Routes" },
  { value: "dosage_form", label: "Dosage forms" },
  { value: "unit", label: "Units" },
  { value: "substance", label: "Substance / UNII" },
];

function MappingsPageInner() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const tenantSlug = searchParams.get("tenant") ?? "";

  const [items, setItems] = useState<TerminologyMapping[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [typeFilter, setTypeFilter] = useState<MappingType | "">("");
  const [statusFilter, setStatusFilter] = useState("");

  const [confirmAction, setConfirmAction] = useState<{
    action: MappingAction;
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
      const id = mapping.public_id;
      if (action === "approve") await fdaData.mappings.approve(tenantSlug, id, reason);
      else if (action === "reject") await fdaData.mappings.reject(tenantSlug, id, reason);
      else if (action === "return") await fdaData.mappings.return(tenantSlug, id, reason);
      else await fdaData.mappings.submitReview(tenantSlug, id, reason);
      setConfirmAction(null);
      setReason("");
      load();
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : "Action failed.");
    } finally {
      setActionBusy(false);
    }
  }

  function availableActions(m: TerminologyMapping): MappingAction[] {
    if (TERMINAL_STATUSES.has(m.status)) return [];
    const actions: MappingAction[] = [];
    if (m.status === "proposed" || m.status === "returned") actions.push("submit_review");
    actions.push("approve", "reject");
    if (m.status !== "returned") actions.push("return");
    return actions;
  }

  if (!tenantSlug) return null;

  const showSubstanceColumns = typeFilter === "substance";

  return (
    <main style={{ maxWidth: 1120, margin: "2rem auto", padding: "0 1rem" }}>
      <div style={{ marginBottom: "0.5rem" }}>
        <Link
          href={`/fda-data/releases?tenant=${tenantSlug}`}
          style={{ color: "#1d4ed8", fontSize: 13, textDecoration: "none" }}
        >
          ← FDA releases
        </Link>
      </div>
      <h1 style={{ margin: "0 0 0.5rem" }}>Terminology Mapping Review</h1>
      <p style={{ fontSize: 13, color: "#6b7280", marginTop: 0, marginBottom: "0.75rem" }}>
        No mapping is ever auto-approved. Every approval, rejection, or return here requires an
        explicit reviewer action and is fully auditable. Fuzzy matches only ever surface as
        proposals for a human to decide.
      </p>

      <div
        role="note"
        style={{
          fontSize: 12,
          color: "#78350f",
          background: "#fffbeb",
          border: "1px solid #fde68a",
          borderRadius: 6,
          padding: "8px 12px",
          marginBottom: "1rem",
        }}
      >
        <strong>Segregation of duties:</strong> a reviewer who has already reviewed a mapping
        cannot also approve it. Approval requires a separate VP-level approver.
      </div>

      {/* Type tabs */}
      <div
        role="tablist"
        aria-label="Mapping type"
        style={{ display: "flex", gap: 4, marginBottom: "0.75rem", flexWrap: "wrap" }}
      >
        {TYPE_TABS.map((tab) => {
          const active = typeFilter === tab.value;
          return (
            <button
              key={tab.value || "all"}
              role="tab"
              aria-selected={active}
              onClick={() => setTypeFilter(tab.value)}
              style={{
                fontSize: 13,
                padding: "6px 12px",
                borderRadius: 6,
                border: active ? "1px solid #1d4ed8" : "1px solid #d1d5db",
                background: active ? "#eff6ff" : "#fff",
                color: active ? "#1d4ed8" : "#374151",
                fontWeight: active ? 600 : 400,
                cursor: "pointer",
              }}
            >
              {tab.label}
            </button>
          );
        })}
      </div>

      <div style={{ display: "flex", gap: 12, marginBottom: "1rem" }}>
        <label style={{ fontSize: 13, color: "#374151" }}>
          Status:{" "}
          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
            style={{ padding: "4px 8px", borderRadius: 4, border: "1px solid #d1d5db", fontSize: 13 }}
          >
            <option value="">All</option>
            <option value="proposed">Proposed</option>
            <option value="under_review">Under review</option>
            <option value="approved">Approved</option>
            <option value="rejected">Rejected</option>
            <option value="returned">Returned</option>
          </select>
        </label>
      </div>

      {loading && <p>Loading…</p>}
      {error && (
        <div role="alert" style={{ color: "#b91c1c" }}>
          <p>{error}</p>
          <button onClick={load} style={{ ...actionButtonStyle, background: "#1d4ed8" }}>
            Retry
          </button>
        </div>
      )}
      {!loading && items.length === 0 && !error && (
        <p style={{ color: "#6b7280" }}>No terminology mappings match this filter.</p>
      )}

      {items.length > 0 && (
        <div style={{ overflowX: "auto" }}>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
            <thead>
              <tr style={{ borderBottom: "2px solid #e5e7eb", textAlign: "left" }}>
                <th style={{ padding: "8px 10px" }} scope="col">
                  Source value <ProvenanceLabel kind="FDA_SOURCE" />
                </th>
                <th style={{ padding: "8px 10px" }} scope="col">
                  Type
                </th>
                <th style={{ padding: "8px 10px" }} scope="col">
                  {showSubstanceColumns ? "Proposed ingredient" : "Proposed controlled value"}
                </th>
                {showSubstanceColumns && (
                  <>
                    <th style={{ padding: "8px 10px" }} scope="col">
                      UNII
                    </th>
                    <th style={{ padding: "8px 10px" }} scope="col">
                      CAS
                    </th>
                    <th style={{ padding: "8px 10px" }} scope="col">
                      Method
                    </th>
                  </>
                )}
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
                  <td style={{ padding: "8px 10px", fontFamily: "monospace" }}>
                    {m.source_raw_value}
                  </td>
                  <td style={{ padding: "8px 10px", color: "#6b7280" }}>
                    {m.mapping_type.replace("_", " ")}
                  </td>
                  <td style={{ padding: "8px 10px" }}>{m.proposed_controlled_value ?? "—"}</td>
                  {showSubstanceColumns && (
                    <>
                      <td style={{ padding: "8px 10px", fontFamily: "monospace" }}>
                        {m.proposed_unii ?? "—"}
                      </td>
                      <td style={{ padding: "8px 10px", fontFamily: "monospace" }}>
                        {m.proposed_cas_number ?? "—"}
                      </td>
                      <td style={{ padding: "8px 10px", color: "#6b7280" }}>
                        {m.mapping_method ?? "—"}
                      </td>
                    </>
                  )}
                  <td style={{ padding: "8px 10px" }}>
                    <StatusBadge status={m.status} />
                  </td>
                  <td style={{ padding: "8px 10px", color: "#6b7280" }}>
                    {m.reviewer_email ?? "—"}
                    {m.reviewer_email && <ProvenanceLabel kind="REVIEWER_CONFIRMED" />}
                  </td>
                  <td style={{ padding: "8px 10px", color: "#6b7280" }}>
                    <Link
                      href={`/fda-data/mappings/${m.public_id}?tenant=${tenantSlug}`}
                      style={{ color: "#1d4ed8", textDecoration: "none" }}
                    >
                      {m.affected_record_count} record(s) →
                    </Link>
                  </td>
                  <td style={{ padding: "8px 10px" }}>
                    <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                      {availableActions(m).map((action) => (
                        <button
                          key={action}
                          onClick={() => setConfirmAction({ action, mapping: m })}
                          style={{
                            ...actionButtonStyle,
                            background:
                              action === "approve"
                                ? "#166534"
                                : action === "reject"
                                  ? "#991b1b"
                                  : action === "return"
                                    ? "#6d28d9"
                                    : "#1d4ed8",
                          }}
                        >
                          {ACTION_LABELS[action]}
                        </button>
                      ))}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
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
          <div
            style={{ background: "#fff", borderRadius: 8, padding: "1.5rem", maxWidth: 440, width: "90%" }}
          >
            <h2 id="mapping-confirm-title" style={{ fontSize: 16, marginTop: 0 }}>
              {ACTION_LABELS[confirmAction.action]}
            </h2>
            <p style={{ fontSize: 13, color: "#6b7280" }}>
              {confirmAction.mapping.source_raw_value} →{" "}
              {confirmAction.mapping.proposed_controlled_value ?? "(no controlled value)"}. This
              affects {confirmAction.mapping.affected_record_count} record(s).
            </p>
            {confirmAction.action === "approve" && (
              <p style={{ fontSize: 12, color: "#78350f" }}>
                Approving records your identity as the approver. You cannot approve a mapping you
                have already reviewed.
              </p>
            )}
            <label style={{ display: "block", fontSize: 13, marginBottom: 8 }}>
              Reason
              <textarea
                value={reason}
                onChange={(e) => setReason(e.target.value)}
                rows={2}
                style={{
                  display: "block",
                  width: "100%",
                  marginTop: 4,
                  padding: "6px 8px",
                  border: "1px solid #d1d5db",
                  borderRadius: 4,
                  boxSizing: "border-box",
                }}
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
              <button
                onClick={confirmAndRun}
                disabled={actionBusy}
                style={{ ...actionButtonStyle, background: "#1d4ed8" }}
              >
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
