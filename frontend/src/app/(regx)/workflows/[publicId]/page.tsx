"use client";

import { Suspense, useEffect, useState } from "react";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import {
  workflows,
  WORKFLOW_REASON_REQUIRED,
  type WorkflowAction,
  type WorkflowItem,
  type WorkflowTransitionRecord,
  ApiError,
} from "@/lib/api";
import { StateBadge } from "../state-badge";
import { EvidenceSection } from "./evidence-section";

const ACTION_LABELS: Record<WorkflowAction, string> = {
  submit: "Submit for review",
  begin_review: "Begin review",
  approve: "Approve",
  reject: "Reject",
  cancel: "Cancel",
  return_to_draft: "Return to draft",
};

function WorkflowDetailInner() {
  const router = useRouter();
  const params = useParams<{ publicId: string }>();
  const searchParams = useSearchParams();
  const tenantSlug = searchParams.get("tenant") ?? "";
  const publicId = params.publicId;

  const [item, setItem] = useState<WorkflowItem | null>(null);
  const [history, setHistory] = useState<WorkflowTransitionRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [pendingAction, setPendingAction] = useState<WorkflowAction | null>(null);
  const [reason, setReason] = useState("");
  const [submitting, setSubmitting] = useState(false);

  function load(): Promise<void> {
    if (!tenantSlug) return Promise.resolve();
    setLoading(true);
    return Promise.all([
      workflows.get(tenantSlug, publicId),
      workflows.history(tenantSlug, publicId),
    ])
      .then(([detail, rows]) => {
        setItem(detail);
        setHistory(rows);
        setError(null);
      })
      .catch((err: unknown) => {
        if (err instanceof ApiError && (err.status === 403 || err.status === 401)) {
          router.push(
            `/signin?next=${encodeURIComponent(window.location.pathname + window.location.search)}`
          );
        } else if (err instanceof ApiError && err.status === 404) {
          setError("Workflow item not found.");
        } else {
          setError("Failed to load workflow item.");
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

  function startAction(action: WorkflowAction) {
    setReason("");
    setError(null);
    if (WORKFLOW_REASON_REQUIRED.includes(action)) {
      setPendingAction(action);
    } else {
      void runAction(action, "");
    }
  }

  async function runAction(action: WorkflowAction, actionReason: string) {
    setSubmitting(true);
    try {
      await workflows.transition(tenantSlug, publicId, action, actionReason);
      setPendingAction(null);
      setReason("");
      load();
    } catch (err: unknown) {
      if (err instanceof ApiError && err.status === 409) {
        // Someone else moved it first. Reload rather than guess -- and set the
        // notice AFTER the reload, because load() clears the error on success.
        setPendingAction(null);
        void load().then(() =>
          setError("This item changed while you were viewing it. Reloading its current state.")
        );
      } else if (err instanceof ApiError && err.status === 403) {
        setError("You do not have permission to perform that action.");
      } else if (err instanceof ApiError && err.status === 400) {
        setError("That action was rejected. A reason may be required.");
      } else {
        setError("Action failed.");
      }
    } finally {
      setSubmitting(false);
    }
  }

  if (!tenantSlug) return null;
  if (loading) return <main style={{ padding: "2rem" }}>Loading…</main>;
  if (!item)
    return (
      <main style={{ padding: "2rem" }}>
        <p role="alert">{error ?? "Workflow item not found."}</p>
      </main>
    );

  return (
    <main style={{ maxWidth: 900, margin: "2rem auto", padding: "0 1rem" }}>
      <Link href={`/workflows?tenant=${tenantSlug}`}>&larr; All workflows</Link>

      <div style={{ display: "flex", alignItems: "center", gap: "0.75rem", marginTop: "1rem" }}>
        <h1 style={{ margin: 0 }}>{item.title}</h1>
        <StateBadge state={item.state} />
      </div>

      {error && (
        <p role="alert" data-testid="workflow-error" style={{ color: "#b91c1c" }}>
          {error}
        </p>
      )}

      {item.description && <p style={{ whiteSpace: "pre-wrap" }}>{item.description}</p>}

      <dl style={{ display: "grid", gridTemplateColumns: "auto 1fr", gap: "0.35rem 1rem" }}>
        <dt>Created by</dt>
        <dd>{item.created_by?.email ?? "—"}</dd>
        <dt>Assigned to</dt>
        <dd data-testid="workflow-assignee">{item.assigned_to?.email ?? "Unassigned"}</dd>
        <dt>Due</dt>
        <dd>
          {item.due_at ? new Date(item.due_at).toLocaleString() : "—"}
          {item.is_overdue && <strong style={{ color: "#b91c1c" }}> Overdue</strong>}
        </dd>
      </dl>

      {/* Rendered from `available_actions`, which the backend computes as
          structurally-legal AND permitted. Hiding a control is presentation,
          not security: every endpoint re-checks server-side. */}
      <section style={{ margin: "1.5rem 0" }}>
        <h2 style={{ fontSize: "1.1rem" }}>Actions</h2>
        {item.available_actions.length === 0 ? (
          <p data-testid="no-actions">No actions available in this state.</p>
        ) : (
          <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
            {item.available_actions.map((action) => (
              <button
                key={action}
                type="button"
                data-testid={`action-${action}`}
                disabled={submitting}
                onClick={() => startAction(action)}
                style={{
                  padding: "0.45rem 0.9rem",
                  borderRadius: 6,
                  border: "1px solid #cbd5e1",
                  background: "#fff",
                  cursor: submitting ? "default" : "pointer",
                }}
              >
                {ACTION_LABELS[action]}
              </button>
            ))}
          </div>
        )}
      </section>

      {pendingAction && (
        <section
          data-testid="reason-form"
          style={{ border: "1px solid #cbd5e1", borderRadius: 8, padding: "1rem" }}
        >
          <h3 style={{ marginTop: 0 }}>{ACTION_LABELS[pendingAction]} — reason required</h3>
          <p style={{ fontSize: "0.9rem", color: "#475569" }}>
            A reason is recorded in the workflow history. It is not an electronic signature.
          </p>
          <textarea
            aria-label="Reason"
            data-testid="reason-input"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            rows={3}
            style={{ width: "100%", padding: "0.5rem" }}
          />
          <div style={{ display: "flex", gap: "0.5rem", marginTop: "0.5rem" }}>
            <button
              type="button"
              data-testid="reason-confirm"
              disabled={submitting || reason.trim() === ""}
              onClick={() => void runAction(pendingAction, reason)}
              style={{ padding: "0.45rem 0.9rem", borderRadius: 6 }}
            >
              Confirm
            </button>
            <button
              type="button"
              onClick={() => setPendingAction(null)}
              style={{ padding: "0.45rem 0.9rem", borderRadius: 6 }}
            >
              Cancel
            </button>
          </div>
        </section>
      )}

      {/* Evidence. `canManage` is advisory for rendering only -- the API
          re-checks workflows.manage_evidence AND documents.view on every call. */}
      <EvidenceSection
        tenantSlug={tenantSlug}
        workflowPublicId={publicId}
        state={item.state}
        canManage={item.available_actions.length > 0 || item.state === "draft"}
      />

      <section style={{ marginTop: "2rem" }}>
        <h2 style={{ fontSize: "1.1rem" }}>History</h2>
        {history.length === 0 ? (
          <p>No transitions yet.</p>
        ) : (
          <table style={{ width: "100%", borderCollapse: "collapse" }} data-testid="history-table">
            <thead>
              <tr style={{ textAlign: "left", borderBottom: "2px solid #e5e7eb" }}>
                <th style={{ padding: "0.4rem" }}>When</th>
                <th style={{ padding: "0.4rem" }}>Change</th>
                <th style={{ padding: "0.4rem" }}>Actor</th>
                <th style={{ padding: "0.4rem" }}>Reason</th>
              </tr>
            </thead>
            <tbody>
              {history.map((row) => (
                <tr key={row.public_id} style={{ borderBottom: "1px solid #f1f5f9" }}>
                  <td style={{ padding: "0.4rem" }}>
                    {new Date(row.created_at).toLocaleString()}
                  </td>
                  <td style={{ padding: "0.4rem" }}>
                    {row.from_state} &rarr; {row.to_state}
                  </td>
                  <td style={{ padding: "0.4rem" }}>{row.actor?.email ?? "—"}</td>
                  <td style={{ padding: "0.4rem" }}>{row.reason || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </main>
  );
}

export default function WorkflowDetailPage() {
  return (
    <Suspense fallback={<p>Loading…</p>}>
      <WorkflowDetailInner />
    </Suspense>
  );
}
