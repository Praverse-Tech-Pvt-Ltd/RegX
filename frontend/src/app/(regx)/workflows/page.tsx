"use client";

import { Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import { workflows, type WorkflowItem, type WorkflowState, ApiError } from "@/lib/api";
import { StateBadge } from "./state-badge";

const STATE_FILTERS: Array<{ value: "" | WorkflowState; label: string }> = [
  { value: "", label: "All" },
  { value: "draft", label: "Draft" },
  { value: "submitted", label: "Submitted" },
  { value: "in_review", label: "In Review" },
  { value: "approved", label: "Approved" },
  { value: "rejected", label: "Rejected" },
  { value: "cancelled", label: "Cancelled" },
];

function WorkflowsPageInner() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const tenantSlug = searchParams.get("tenant") ?? "";

  const [items, setItems] = useState<WorkflowItem[]>([]);
  const [stateFilter, setStateFilter] = useState<"" | WorkflowState>("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  function load(filter: "" | WorkflowState) {
    if (!tenantSlug) return;
    setLoading(true);
    workflows
      .list(tenantSlug, filter ? { state: filter } : undefined)
      .then((resp) => setItems(resp.results))
      .catch((err: unknown) => {
        if (err instanceof ApiError && (err.status === 403 || err.status === 401)) {
          router.push(
            `/signin?next=${encodeURIComponent(window.location.pathname + window.location.search)}`
          );
        } else {
          setError("Failed to load workflow items.");
        }
      })
      .finally(() => setLoading(false));
  }

  useEffect(() => {
    if (!tenantSlug) {
      router.push("/tenants");
      return;
    }
    load(stateFilter);
  }, [tenantSlug, stateFilter]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!tenantSlug) return null;

  return (
    <main style={{ maxWidth: 1000, margin: "2rem auto", padding: "0 1rem" }}>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          marginBottom: "1.5rem",
        }}
      >
        <h1 style={{ margin: 0 }}>Workflows</h1>
        <Link
          href={`/workflows/new?tenant=${tenantSlug}`}
          style={{
            background: "#1d4ed8",
            color: "#fff",
            borderRadius: 6,
            padding: "0.5rem 1rem",
            textDecoration: "none",
          }}
        >
          New workflow
        </Link>
      </div>

      <div style={{ marginBottom: "1rem" }}>
        <label htmlFor="state-filter" style={{ marginRight: "0.5rem" }}>
          State
        </label>
        <select
          id="state-filter"
          value={stateFilter}
          onChange={(e) => setStateFilter(e.target.value as "" | WorkflowState)}
          style={{ padding: "0.35rem 0.5rem", borderRadius: 6 }}
        >
          {STATE_FILTERS.map((opt) => (
            <option key={opt.value || "all"} value={opt.value}>
              {opt.label}
            </option>
          ))}
        </select>
      </div>

      {error && <p role="alert">{error}</p>}
      {loading && <p>Loading…</p>}

      {!loading && items.length === 0 && <p>No workflow items.</p>}

      {!loading && items.length > 0 && (
        <table style={{ width: "100%", borderCollapse: "collapse" }}>
          <thead>
            <tr style={{ textAlign: "left", borderBottom: "2px solid #e5e7eb" }}>
              <th style={{ padding: "0.5rem" }}>Title</th>
              <th style={{ padding: "0.5rem" }}>State</th>
              <th style={{ padding: "0.5rem" }}>Assigned to</th>
              <th style={{ padding: "0.5rem" }}>Due</th>
            </tr>
          </thead>
          <tbody>
            {items.map((item) => (
              <tr key={item.public_id} style={{ borderBottom: "1px solid #f1f5f9" }}>
                <td style={{ padding: "0.5rem" }}>
                  <Link href={`/workflows/${item.public_id}?tenant=${tenantSlug}`}>
                    {item.title}
                  </Link>
                </td>
                <td style={{ padding: "0.5rem" }}>
                  <StateBadge state={item.state} />
                </td>
                <td style={{ padding: "0.5rem" }}>
                  {item.assigned_to ? item.assigned_to.email : "—"}
                </td>
                <td style={{ padding: "0.5rem" }}>
                  {item.due_at ? new Date(item.due_at).toLocaleDateString() : "—"}
                  {item.is_overdue && (
                    <span style={{ color: "#b91c1c", marginLeft: "0.5rem" }}>Overdue</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </main>
  );
}

export default function WorkflowsPage() {
  return (
    <Suspense fallback={<p>Loading…</p>}>
      <WorkflowsPageInner />
    </Suspense>
  );
}
