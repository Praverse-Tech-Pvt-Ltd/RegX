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

  const [showProposeDialog, setShowProposeDialog] = useState(false);
  const [proposeForm, setProposeForm] = useState({
    release_public_id: "",
    raw_ingredient_name: "",
    normalized_ingredient_name: "",
    proposed_ingredient_public_id: "",
    proposed_unii: "",
    proposed_cas_number: "",
    raw_unii: "",
    raw_cas_number: "",
    source_row_locator: "",
    mapping_method: "manual",
    reason: "",
  });
  const [proposeError, setProposeError] = useState<string | null>(null);
  const [proposeBusy, setProposeBusy] = useState(false);
  const [proposeSuccess, setProposeSuccess] = useState<string | null>(null);

  function resetProposeForm() {
    setProposeForm({
      release_public_id: "",
      raw_ingredient_name: "",
      normalized_ingredient_name: "",
      proposed_ingredient_public_id: "",
      proposed_unii: "",
      proposed_cas_number: "",
      raw_unii: "",
      raw_cas_number: "",
      source_row_locator: "",
      mapping_method: "manual",
      reason: "",
    });
    setProposeError(null);
    setProposeSuccess(null);
  }

  async function submitProposal() {
    setProposeBusy(true);
    setProposeError(null);
    try {
      const created = await fdaData.mappings.proposeSubstance(tenantSlug, {
        release_public_id: proposeForm.release_public_id || undefined,
        raw_ingredient_name: proposeForm.raw_ingredient_name,
        normalized_ingredient_name: proposeForm.normalized_ingredient_name,
        proposed_ingredient_public_id: proposeForm.proposed_ingredient_public_id || undefined,
        proposed_unii: proposeForm.proposed_unii || undefined,
        proposed_cas_number: proposeForm.proposed_cas_number || undefined,
        raw_unii: proposeForm.raw_unii || undefined,
        raw_cas_number: proposeForm.raw_cas_number || undefined,
        source_row_locator: proposeForm.source_row_locator || undefined,
        mapping_method: proposeForm.mapping_method,
        reason: proposeForm.reason || undefined,
      });
      setProposeSuccess(created.public_id);
      load();
    } catch (err) {
      setProposeError(err instanceof ApiError ? err.message : "Failed to submit proposal.");
    } finally {
      setProposeBusy(false);
    }
  }

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
          router.push(`/signin?next=${encodeURIComponent(window.location.pathname + window.location.search)}`);
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

      <div style={{ display: "flex", gap: 12, marginBottom: "1rem", alignItems: "center" }}>
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
        {(typeFilter === "" || typeFilter === "substance") && (
          <button
            onClick={() => {
              resetProposeForm();
              setShowProposeDialog(true);
            }}
            style={{ ...actionButtonStyle, background: "#1d4ed8", marginLeft: "auto" }}
          >
            + Propose substance mapping
          </button>
        )}
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

      {showProposeDialog && (
        <div
          role="dialog"
          aria-modal="true"
          aria-labelledby="propose-mapping-title"
          style={{
            position: "fixed",
            inset: 0,
            background: "rgba(0,0,0,0.4)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            padding: "1rem",
          }}
        >
          <div
            style={{
              background: "#fff",
              borderRadius: 8,
              padding: "1.5rem",
              maxWidth: 560,
              width: "100%",
              maxHeight: "90vh",
              overflowY: "auto",
            }}
          >
            <h2 id="propose-mapping-title" style={{ fontSize: 16, marginTop: 0 }}>
              Propose substance mapping
            </h2>

            {proposeSuccess ? (
              <>
                <p style={{ fontSize: 13, color: "#166534" }}>
                  Proposal created. It is recorded as <strong>PROPOSED</strong> and has not been
                  auto-approved — it now requires submit-for-review and a separate VP approval
                  before it takes effect.
                </p>
                <p style={{ fontSize: 12, color: "#6b7280", fontFamily: "monospace" }}>
                  {proposeSuccess}
                </p>
                <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
                  <button
                    onClick={() => {
                      setShowProposeDialog(false);
                      resetProposeForm();
                    }}
                    style={{ ...actionButtonStyle, background: "#1d4ed8" }}
                  >
                    Done
                  </button>
                </div>
              </>
            ) : (
              <>
                <p style={{ fontSize: 13, color: "#6b7280" }}>
                  This only creates a <strong>PROPOSED</strong> candidate mapping. It is never
                  auto-approved: a reviewer must submit it for review, and a separate VP-level
                  approver must approve it before it affects any IID assessment.
                </p>

                <label style={{ display: "block", fontSize: 13, marginBottom: 8 }}>
                  Release public ID (optional)
                  <input
                    value={proposeForm.release_public_id}
                    onChange={(e) =>
                      setProposeForm({ ...proposeForm, release_public_id: e.target.value })
                    }
                    style={inputStyle}
                  />
                </label>
                <label style={{ display: "block", fontSize: 13, marginBottom: 8 }}>
                  Raw ingredient name (as seen in source)
                  <input
                    value={proposeForm.raw_ingredient_name}
                    onChange={(e) =>
                      setProposeForm({ ...proposeForm, raw_ingredient_name: e.target.value })
                    }
                    style={inputStyle}
                  />
                </label>
                <label style={{ display: "block", fontSize: 13, marginBottom: 8 }}>
                  Normalized ingredient name
                  <input
                    value={proposeForm.normalized_ingredient_name}
                    onChange={(e) =>
                      setProposeForm({
                        ...proposeForm,
                        normalized_ingredient_name: e.target.value,
                      })
                    }
                    style={inputStyle}
                  />
                </label>

                <div style={{ display: "flex", gap: 8 }}>
                  <label style={{ display: "block", fontSize: 13, marginBottom: 8, flex: 1 }}>
                    Proposed canonical ingredient (public ID)
                    <input
                      value={proposeForm.proposed_ingredient_public_id}
                      onChange={(e) =>
                        setProposeForm({
                          ...proposeForm,
                          proposed_ingredient_public_id: e.target.value,
                        })
                      }
                      style={inputStyle}
                    />
                  </label>
                </div>

                <div style={{ display: "flex", gap: 8 }}>
                  <label style={{ display: "block", fontSize: 13, marginBottom: 8, flex: 1 }}>
                    Proposed UNII
                    <input
                      value={proposeForm.proposed_unii}
                      onChange={(e) =>
                        setProposeForm({ ...proposeForm, proposed_unii: e.target.value })
                      }
                      style={inputStyle}
                    />
                  </label>
                  <label style={{ display: "block", fontSize: 13, marginBottom: 8, flex: 1 }}>
                    Proposed CAS
                    <input
                      value={proposeForm.proposed_cas_number}
                      onChange={(e) =>
                        setProposeForm({ ...proposeForm, proposed_cas_number: e.target.value })
                      }
                      style={inputStyle}
                    />
                  </label>
                </div>

                <label style={{ display: "block", fontSize: 13, marginBottom: 8 }}>
                  Mapping method
                  <select
                    value={proposeForm.mapping_method}
                    onChange={(e) =>
                      setProposeForm({ ...proposeForm, mapping_method: e.target.value })
                    }
                    style={inputStyle}
                  >
                    <option value="manual">Manual</option>
                    <option value="exact_unii">Exact UNII</option>
                    <option value="exact_cas">Exact CAS</option>
                    <option value="reviewed_synonym">Reviewed synonym</option>
                  </select>
                </label>

                <label style={{ display: "block", fontSize: 13, marginBottom: 8 }}>
                  Source row locator (optional)
                  <input
                    value={proposeForm.source_row_locator}
                    onChange={(e) =>
                      setProposeForm({ ...proposeForm, source_row_locator: e.target.value })
                    }
                    style={inputStyle}
                  />
                </label>

                <label style={{ display: "block", fontSize: 13, marginBottom: 8 }}>
                  Reason / evidence
                  <textarea
                    value={proposeForm.reason}
                    onChange={(e) => setProposeForm({ ...proposeForm, reason: e.target.value })}
                    rows={3}
                    style={{ ...inputStyle, resize: "vertical" }}
                  />
                </label>

                {proposeError && (
                  <p role="alert" style={{ color: "#b91c1c", fontSize: 13, marginBottom: 8 }}>
                    {proposeError}
                  </p>
                )}

                <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
                  <button
                    onClick={() => {
                      setShowProposeDialog(false);
                      resetProposeForm();
                    }}
                    style={{ ...actionButtonStyle, background: "#6b7280" }}
                  >
                    Cancel
                  </button>
                  <button
                    onClick={submitProposal}
                    disabled={
                      proposeBusy ||
                      !proposeForm.raw_ingredient_name ||
                      !proposeForm.normalized_ingredient_name
                    }
                    style={{ ...actionButtonStyle, background: "#1d4ed8" }}
                  >
                    {proposeBusy ? "Submitting…" : "Submit proposal"}
                  </button>
                </div>
              </>
            )}
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

const inputStyle: React.CSSProperties = {
  display: "block",
  width: "100%",
  marginTop: 4,
  padding: "6px 8px",
  border: "1px solid #d1d5db",
  borderRadius: 4,
  boxSizing: "border-box",
  fontSize: 13,
};

export default function MappingsPage() {
  return (
    <Suspense>
      <MappingsPageInner />
    </Suspense>
  );
}
