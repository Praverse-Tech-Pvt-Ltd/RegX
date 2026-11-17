"use client";

import { Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { iigChecklists, ApiError } from "@/lib/api";

function NewExecutionPageInner() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const tenantSlug = searchParams.get("tenant") ?? "";

  const [checklistVersionPublicId, setChecklistVersionPublicId] = useState("");
  const [formulationVersionPublicId, setFormulationVersionPublicId] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  useEffect(() => {
    if (!tenantSlug) router.push("/tenants");
  }, [tenantSlug, router]);

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!checklistVersionPublicId.trim() || !formulationVersionPublicId.trim()) return;
    setSubmitting(true);
    setActionError(null);
    iigChecklists.executions
      .create(tenantSlug, {
        checklist_version_public_id: checklistVersionPublicId.trim(),
        formulation_version_public_id: formulationVersionPublicId.trim(),
      })
      .then((execution) => {
        router.push(`/iig-checklists/executions/${execution.publicId}?tenant=${tenantSlug}`);
      })
      .catch((err: unknown) => {
        if (err instanceof ApiError && err.status === 401) {
          router.push(`/signin?next=${encodeURIComponent(window.location.pathname + window.location.search)}`);
        } else if (err instanceof ApiError && err.status === 403) {
          setActionError("You do not have permission to create executions.");
        } else if (err instanceof ApiError && err.status === 409) {
          setActionError("An active execution already exists for this combination.");
        } else if (err instanceof ApiError) {
          setActionError(err.message || "Failed to create execution.");
        } else {
          setActionError("Failed to create execution.");
        }
      })
      .finally(() => setSubmitting(false));
  }

  return (
    <div>
      <h1>New Checklist Execution</h1>
      {actionError && <p style={{ color: "red" }}>{actionError}</p>}
      <form onSubmit={handleSubmit}>
        <div>
          <label>
            Checklist Version Public ID
            <br />
            <input
              type="text"
              value={checklistVersionPublicId}
              onChange={(e) => setChecklistVersionPublicId(e.target.value)}
              required
              style={{ width: "36ch" }}
            />
          </label>
        </div>
        <div>
          <label>
            Formulation Version Public ID
            <br />
            <input
              type="text"
              value={formulationVersionPublicId}
              onChange={(e) => setFormulationVersionPublicId(e.target.value)}
              required
              style={{ width: "36ch" }}
            />
          </label>
        </div>
        <button type="submit" disabled={submitting}>
          {submitting ? "Creating…" : "Create execution"}
        </button>
      </form>
    </div>
  );
}

export default function NewExecutionPage() {
  return (
    <main style={{ maxWidth: 1100, margin: "2rem auto", padding: "0 1rem" }}>
      <Suspense fallback={<p>Loading…</p>}>
        <NewExecutionPageInner />
      </Suspense>
    </main>
  );
}
