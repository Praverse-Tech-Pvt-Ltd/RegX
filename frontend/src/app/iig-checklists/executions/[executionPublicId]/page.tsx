"use client";

import { Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams, useParams } from "next/navigation";
import { iigChecklists, type ChecklistExecution, ApiError } from "@/lib/api";

const TERMINAL_STATUSES = new Set(["rejected", "cancelled", "superseded"]);

function ExecutionDetailPageInner() {
  const router = useRouter();
  const params = useParams();
  const searchParams = useSearchParams();
  const tenantSlug = searchParams.get("tenant") ?? "";
  const executionPublicId = params.executionPublicId as string;

  const [execution, setExecution] = useState<ChecklistExecution | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [acting, setActing] = useState(false);

  // Inputs for actions that require text.
  const [returnReason, setReturnReason] = useState("");
  const [reviewerConclusionNote, setReviewerConclusionNote] = useState("");

  function load() {
    if (!tenantSlug || !executionPublicId) return;
    setLoading(true);
    iigChecklists.executions
      .get(tenantSlug, executionPublicId)
      .then(setExecution)
      .catch((err: unknown) => {
        if (err instanceof ApiError && err.status === 401) {
          router.push("/signin");
        } else {
          setError("Failed to load execution.");
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
  }, [tenantSlug, executionPublicId]); // eslint-disable-line react-hooks/exhaustive-deps

  async function doAction(action: () => Promise<ChecklistExecution>) {
    setActing(true);
    setActionError(null);
    try {
      const updated = await action();
      setExecution(updated);
    } catch (err: unknown) {
      if (err instanceof ApiError && err.status === 401) {
        router.push("/signin");
      } else if (err instanceof ApiError && err.status === 403) {
        setActionError("You do not have permission to perform this action.");
      } else if (err instanceof ApiError) {
        setActionError(err.message || "Action failed.");
      } else {
        setActionError("Action failed.");
      }
    } finally {
      setActing(false);
    }
  }

  if (loading) return <p>Loading execution…</p>;
  if (error) return <p style={{ color: "red" }}>{error}</p>;
  if (!execution) return <p>Not found.</p>;

  const isTerminal = TERMINAL_STATUSES.has(execution.status);

  return (
    <div>
      <h1>Checklist Execution</h1>

      {actionError && <p style={{ color: "red" }}>{actionError}</p>}

      <table>
        <tbody>
          <tr><th>Status</th><td>{execution.status}</td></tr>
          <tr><th>Checklist version</th><td>v{execution.checklistVersion.versionNumber} ({execution.checklistVersion.status})</td></tr>
          <tr><th>Formulation version</th><td>{execution.formulationVersionPublicId}</td></tr>
          <tr><th>Created by</th><td>{execution.createdByEmail ?? "—"}</td></tr>
          {execution.submittedAt && (
            <>
              <tr><th>Submitted by</th><td>{execution.submittedByEmail ?? "—"}</td></tr>
              <tr><th>Submitted at</th><td>{execution.submittedAt}</td></tr>
            </>
          )}
          {execution.returnedAt && (
            <>
              <tr><th>Returned by</th><td>{execution.returnedByEmail ?? "—"}</td></tr>
              <tr><th>Returned at</th><td>{execution.returnedAt}</td></tr>
              <tr><th>Return reason</th><td>{execution.returnReason}</td></tr>
            </>
          )}
          {execution.approvedAt && (
            <>
              <tr><th>Approved by</th><td>{execution.approvedByEmail ?? "—"}</td></tr>
              <tr><th>Approved at</th><td>{execution.approvedAt}</td></tr>
              {execution.reviewerConclusionNote && (
                <tr><th>Reviewer conclusion</th><td>{execution.reviewerConclusionNote}</td></tr>
              )}
            </>
          )}
          {execution.rejectedAt && (
            <>
              <tr><th>Rejected by</th><td>{execution.rejectedByEmail ?? "—"}</td></tr>
              <tr><th>Rejected at</th><td>{execution.rejectedAt}</td></tr>
            </>
          )}
          {execution.cancelledAt && (
            <>
              <tr><th>Cancelled by</th><td>{execution.cancelledByEmail ?? "—"}</td></tr>
              <tr><th>Cancelled at</th><td>{execution.cancelledAt}</td></tr>
            </>
          )}
        </tbody>
      </table>

      {!isTerminal && (
        <div style={{ marginTop: "1rem" }}>
          <h2>Actions</h2>

          {(execution.status === "draft" || execution.status === "returned") && (
            <>
              <button
                disabled={acting}
                onClick={() =>
                  doAction(() => iigChecklists.executions.submitReview(tenantSlug, executionPublicId))
                }
              >
                Submit for review
              </button>
              {" "}
              <button
                disabled={acting}
                onClick={() =>
                  doAction(() => iigChecklists.executions.cancel(tenantSlug, executionPublicId))
                }
              >
                Cancel
              </button>
            </>
          )}

          {execution.status === "submitted_for_review" && (
            <>
              <div>
                <label>
                  Reviewer conclusion note (required to approve)
                  <br />
                  <textarea
                    value={reviewerConclusionNote}
                    onChange={(e) => setReviewerConclusionNote(e.target.value)}
                    rows={4}
                    maxLength={4000}
                    style={{ width: "60ch" }}
                  />
                </label>
                <br />
                <button
                  disabled={acting || !reviewerConclusionNote.trim()}
                  onClick={() =>
                    doAction(() =>
                      iigChecklists.executions.approve(tenantSlug, executionPublicId, reviewerConclusionNote)
                    )
                  }
                >
                  Approve
                </button>
              </div>
              <div style={{ marginTop: "0.5rem" }}>
                <label>
                  Return reason
                  <br />
                  <input
                    type="text"
                    value={returnReason}
                    onChange={(e) => setReturnReason(e.target.value)}
                    style={{ width: "60ch" }}
                  />
                </label>
                {" "}
                <button
                  disabled={acting || !returnReason.trim()}
                  onClick={() =>
                    doAction(() =>
                      iigChecklists.executions.return(tenantSlug, executionPublicId, returnReason)
                    )
                  }
                >
                  Return
                </button>
                {" "}
                <button
                  disabled={acting}
                  onClick={() =>
                    doAction(() => iigChecklists.executions.reject(tenantSlug, executionPublicId))
                  }
                >
                  Reject
                </button>
              </div>
            </>
          )}

          {execution.status === "approved" && (
            <button
              disabled={acting}
              onClick={() =>
                doAction(() => iigChecklists.executions.supersede(tenantSlug, executionPublicId))
              }
            >
              Supersede
            </button>
          )}
        </div>
      )}
    </div>
  );
}

export default function ExecutionDetailPage() {
  return (
    <Suspense fallback={<p>Loading…</p>}>
      <ExecutionDetailPageInner />
    </Suspense>
  );
}
