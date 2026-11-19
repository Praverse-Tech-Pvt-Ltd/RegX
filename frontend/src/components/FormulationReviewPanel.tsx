"use client";

import { useState } from "react";
import { formulations, type FormulationVersion, ApiError } from "@/lib/api";

/**
 * Review and approval of a formulation version (Option A, owner decision
 * 2026-11-18). Shows the status and history, and only the actions the server
 * says this user may take now (`available_actions`). Every action asks for
 * confirmation first; return and reject need a reason, approve a note. The
 * server checks everything again (permissions, separation of duties, MFA).
 */

type Action = "submit" | "return" | "reject" | "approve";

const ACTION_TEXT: Record<Action, { button: string; title: string; body: string; field?: string; confirm: string }> = {
  submit: {
    button: "Submit for review",
    title: "Submit this version for review?",
    body: "Its components and dosing regimen are frozen while it is under review. A reviewer can return it to draft.",
    confirm: "Submit for review",
  },
  return: {
    button: "Return to draft",
    title: "Return this version to draft?",
    body: "The submitter can then change it and submit it again.",
    field: "Reason for returning (required)",
    confirm: "Return to draft",
  },
  reject: {
    button: "Reject",
    title: "Reject this version?",
    body: "A rejected version can never be submitted again. This cannot be undone.",
    field: "Reason for rejecting (required)",
    confirm: "Reject",
  },
  approve: {
    button: "Approve",
    title: "Approve this version (internal approval)?",
    body:
      "After approval the version can be used for the IIG checklist and can never be changed. " +
      "Any earlier approved version of this product is marked superseded. This is an internal " +
      "workflow step, not a regulatory approval. This cannot be undone.",
    field: "Approval note (required)",
    confirm: "Approve",
  },
};

const STATUS_TEXT: Record<string, string> = {
  draft: "Draft",
  under_review: "Under review",
  approved: "Approved (internal)",
  superseded: "Superseded",
  retired: "Rejected / retired",
};

export function FormulationReviewPanel({
  tenantSlug,
  version,
  onChanged,
}: {
  tenantSlug: string;
  version: FormulationVersion;
  onChanged: (v: FormulationVersion) => void;
}) {
  const [pending, setPending] = useState<Action | null>(null);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const actions = (version.available_actions ?? []) as Action[];

  async function confirm() {
    if (!pending) return;
    setBusy(true);
    setError(null);
    try {
      const id = version.public_id;
      const v =
        pending === "submit"
          ? await formulations.versions.submitReview(tenantSlug, id)
          : pending === "return"
            ? await formulations.versions.returnToDraft(tenantSlug, id, text)
            : pending === "reject"
              ? await formulations.versions.reject(tenantSlug, id, text)
              : await formulations.versions.approve(tenantSlug, id, text);
      setPending(null);
      setText("");
      onChanged(v);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "The action failed.");
    } finally {
      setBusy(false);
    }
  }

  const needsText = pending ? Boolean(ACTION_TEXT[pending].field) : false;

  return (
    <section
      aria-label="Review and approval"
      data-testid="formulation-review"
      style={{ marginTop: "1rem", border: "1px solid #dce7f4", borderRadius: 8, padding: "1rem" }}
    >
      <h2 style={{ fontSize: 16, margin: "0 0 0.5rem" }}>Review and approval</h2>
      <p style={{ margin: "0 0 0.5rem", fontSize: 13 }}>
        Status: <strong data-testid="version-status">{STATUS_TEXT[version.status] ?? version.status}</strong>
      </p>
      {version.return_reason && version.status === "draft" && (
        <p style={{ fontSize: 13, color: "#8a5a10", margin: "0 0 0.5rem" }}>
          Returned by {version.returned_by_email}: {version.return_reason}
        </p>
      )}

      {actions.length > 0 && (
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 8 }}>
          {actions.map((a) => (
            <button
              key={a}
              type="button"
              onClick={() => {
                setPending(a);
                setText("");
                setError(null);
              }}
              style={{ ...buttonStyle, ...(a === "reject" ? { background: "#8f2c20" } : {}) }}
            >
              {ACTION_TEXT[a].button}
            </button>
          ))}
        </div>
      )}

      {pending && (
        <div
          role="dialog"
          aria-modal="true"
          aria-labelledby="review-dialog-title"
          style={{ border: "1px solid #e8c77a", background: "#fff8e6", borderRadius: 8, padding: "0.75rem 1rem", marginBottom: 8 }}
        >
          <p id="review-dialog-title" style={{ fontWeight: 700, margin: "0 0 4px" }}>
            {ACTION_TEXT[pending].title}
          </p>
          <p style={{ fontSize: 13, margin: "0 0 8px" }}>{ACTION_TEXT[pending].body}</p>
          {needsText && (
            <label style={{ display: "block", fontSize: 13, marginBottom: 8 }}>
              {ACTION_TEXT[pending].field}
              <textarea
                value={text}
                onChange={(e) => setText(e.target.value)}
                rows={3}
                maxLength={4000}
                style={{ display: "block", width: "100%", marginTop: 4, boxSizing: "border-box" }}
              />
            </label>
          )}
          {error && (
            <p role="alert" style={{ color: "#c0392b", fontSize: 13, margin: "0 0 8px" }}>
              {error}
            </p>
          )}
          <button type="button" onClick={confirm} disabled={busy || (needsText && !text.trim())} style={buttonStyle}>
            {busy ? "Working…" : ACTION_TEXT[pending].confirm}
          </button>{" "}
          <button type="button" onClick={() => setPending(null)} disabled={busy} style={{ ...buttonStyle, background: "#66768b" }}>
            Cancel
          </button>
        </div>
      )}

      {(version.history ?? []).length > 0 && (
        <table aria-label="Version history" style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
          <thead>
            <tr style={{ textAlign: "left", borderBottom: "1px solid #dce7f4" }}>
              <th style={{ padding: "4px 8px" }}>When</th>
              <th style={{ padding: "4px 8px" }}>What</th>
              <th style={{ padding: "4px 8px" }}>Who</th>
              <th style={{ padding: "4px 8px" }}>Reason / note</th>
            </tr>
          </thead>
          <tbody>
            {(version.history ?? []).map((h, i) => (
              <tr key={i} style={{ borderBottom: "1px solid #f4f8fe" }}>
                <td style={{ padding: "4px 8px" }}>{new Date(h.at).toLocaleString()}</td>
                <td style={{ padding: "4px 8px" }}>{h.event}</td>
                <td style={{ padding: "4px 8px" }}>{h.by}</td>
                <td style={{ padding: "4px 8px" }}>{h.reason}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}

const buttonStyle: React.CSSProperties = {
  background: "#045e8f",
  color: "#fff",
  border: "none",
  borderRadius: 6,
  padding: "6px 14px",
  cursor: "pointer",
  fontWeight: 600,
  fontSize: 13,
};
