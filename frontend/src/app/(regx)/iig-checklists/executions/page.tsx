"use client";

import { Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import { iigChecklists, type ChecklistExecution, ApiError } from "@/lib/api";

function ExecutionListPageInner() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const tenantSlug = searchParams.get("tenant") ?? "";

  const [items, setItems] = useState<ChecklistExecution[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  function load() {
    if (!tenantSlug) return;
    setLoading(true);
    iigChecklists.executions
      .list(tenantSlug)
      .then((resp) => setItems(resp.results))
      .catch((err: unknown) => {
        if (err instanceof ApiError && err.status === 401) {
          router.push("/signin");
        } else if (err instanceof ApiError && err.status === 403) {
          setError("You do not have permission to view executions.");
        } else {
          setError("Failed to load executions.");
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
  }, [tenantSlug]); // eslint-disable-line react-hooks/exhaustive-deps

  if (loading) return <p>Loading executions…</p>;
  if (error) return <p style={{ color: "red" }}>{error}</p>;

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <h1>Checklist Executions</h1>
        <Link href={`/iig-checklists/executions/new?tenant=${tenantSlug}`}>
          New execution
        </Link>
      </div>
      {items.length === 0 ? (
        <p>No executions found.</p>
      ) : (
        <table>
          <thead>
            <tr>
              <th>Status</th>
              <th>Checklist version</th>
              <th>Formulation version</th>
              <th>Created</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {items.map((ex) => (
              <tr key={ex.publicId}>
                <td>{ex.status}</td>
                <td>v{ex.checklistVersion.versionNumber} ({ex.checklistVersion.status})</td>
                <td>{ex.formulationVersionPublicId}</td>
                <td>{new Date(ex.createdAt).toLocaleDateString()}</td>
                <td>
                  <Link href={`/iig-checklists/executions/${ex.publicId}?tenant=${tenantSlug}`}>
                    View
                  </Link>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

export default function ExecutionListPage() {
  return (
    <Suspense fallback={<p>Loading…</p>}>
      <ExecutionListPageInner />
    </Suspense>
  );
}
