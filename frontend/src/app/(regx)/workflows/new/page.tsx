"use client";

import { Suspense, useState, type FormEvent } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import { workflows, ApiError } from "@/lib/api";

function NewWorkflowInner() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const tenantSlug = searchParams.get("tenant") ?? "";

  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [dueAt, setDueAt] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleCreate(e: FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      const created = await workflows.create(tenantSlug, {
        title,
        description,
        due_at: dueAt ? new Date(dueAt).toISOString() : null,
      });
      router.push(`/workflows/${created.public_id}?tenant=${tenantSlug}`);
    } catch (err: unknown) {
      if (err instanceof ApiError && err.status === 403) {
        setError("You do not have permission to create workflow items.");
      } else if (err instanceof ApiError && err.status === 401) {
        router.push(
          `/signin?next=${encodeURIComponent(window.location.pathname + window.location.search)}`
        );
      } else {
        setError("Could not create the workflow item.");
      }
    } finally {
      setSubmitting(false);
    }
  }

  if (!tenantSlug) return null;

  return (
    <main style={{ maxWidth: 700, margin: "2rem auto", padding: "0 1rem" }}>
      <Link href={`/workflows?tenant=${tenantSlug}`}>&larr; All workflows</Link>
      <h1>New workflow</h1>

      {error && (
        <p role="alert" style={{ color: "#c0392b" }}>
          {error}
        </p>
      )}

      <form onSubmit={handleCreate}>
        <div style={{ marginBottom: "1rem" }}>
          <label htmlFor="wf-title" style={{ display: "block", marginBottom: "0.25rem" }}>
            Title
          </label>
          <input
            id="wf-title"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            required
            maxLength={255}
            style={{ width: "100%", padding: "0.5rem" }}
          />
        </div>

        <div style={{ marginBottom: "1rem" }}>
          <label htmlFor="wf-description" style={{ display: "block", marginBottom: "0.25rem" }}>
            Description
          </label>
          <textarea
            id="wf-description"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            rows={4}
            style={{ width: "100%", padding: "0.5rem" }}
          />
        </div>

        <div style={{ marginBottom: "1rem" }}>
          <label htmlFor="wf-due" style={{ display: "block", marginBottom: "0.25rem" }}>
            Due date (optional)
          </label>
          <input
            id="wf-due"
            type="datetime-local"
            value={dueAt}
            onChange={(e) => setDueAt(e.target.value)}
            style={{ padding: "0.5rem" }}
          />
        </div>

        <button
          type="submit"
          disabled={submitting || title.trim() === ""}
          style={{
            background: "#045e8f",
            color: "#fff",
            border: "none",
            borderRadius: 6,
            padding: "0.5rem 1.1rem",
          }}
        >
          Create
        </button>
      </form>
    </main>
  );
}

export default function NewWorkflowPage() {
  return (
    <Suspense fallback={<p>Loading…</p>}>
      <NewWorkflowInner />
    </Suspense>
  );
}
