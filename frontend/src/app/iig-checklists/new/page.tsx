"use client";

import { Suspense, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import { iigChecklists, ApiError } from "@/lib/api";

function NewDefinitionPageInner() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const tenantSlug = searchParams.get("tenant") ?? "";

  const [code, setCode] = useState("");
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [scopeType, setScopeType] = useState("tenant");
  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    setFormError(null);
    try {
      const definition = await iigChecklists.definitions.create(tenantSlug, {
        code,
        title,
        description,
        scope_type: scopeType,
      });
      router.push(`/iig-checklists/${definition.public_id}?tenant=${tenantSlug}`);
    } catch (err) {
      if (err instanceof ApiError && (err.status === 403 || err.status === 401)) {
        router.push("/signin");
        return;
      }
      setFormError(err instanceof ApiError ? err.message : "Creation failed.");
    } finally {
      setSubmitting(false);
    }
  }

  if (!tenantSlug) {
    return (
      <main style={{ maxWidth: 700, margin: "2rem auto", padding: "0 1rem" }}>
        <p role="alert" style={{ color: "#b91c1c" }}>
          Select a tenant first.
        </p>
      </main>
    );
  }

  return (
    <main style={{ maxWidth: 700, margin: "2rem auto", padding: "0 1rem" }}>
      <div style={{ marginBottom: "0.5rem" }}>
        <Link href={`/iig-checklists?tenant=${tenantSlug}`} style={{ color: "#1d4ed8", fontSize: 13, textDecoration: "none" }}>
          ← Checklist definitions
        </Link>
      </div>
      <h1 style={{ margin: "0 0 0.5rem" }}>New Checklist Definition</h1>
      <p style={{ fontSize: 13, color: "#6b7280", marginTop: 0, marginBottom: "1rem" }}>
        A new definition starts with no versions. Create version 1 (draft) from the
        definition detail page once it exists.
      </p>

      <form onSubmit={handleCreate}>
        <label style={{ display: "block", marginBottom: "0.5rem", fontWeight: 500, fontSize: 13 }}>
          Code
          <input
            value={code}
            onChange={(e) => setCode(e.target.value)}
            required
            placeholder="e.g. IIG-ORAL-SOLID"
            style={{ display: "block", width: "100%", marginTop: 4, padding: "6px 8px", border: "1px solid #d1d5db", borderRadius: 4, boxSizing: "border-box" }}
          />
        </label>
        <label style={{ display: "block", marginBottom: "0.5rem", fontWeight: 500, fontSize: 13 }}>
          Title
          <input
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            required
            style={{ display: "block", width: "100%", marginTop: 4, padding: "6px 8px", border: "1px solid #d1d5db", borderRadius: 4, boxSizing: "border-box" }}
          />
        </label>
        <label style={{ display: "block", marginBottom: "0.5rem", fontWeight: 500, fontSize: 13 }}>
          Description (optional)
          <textarea
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            rows={3}
            style={{ display: "block", width: "100%", marginTop: 4, padding: "6px 8px", border: "1px solid #d1d5db", borderRadius: 4, boxSizing: "border-box" }}
          />
        </label>
        <label style={{ display: "block", marginBottom: "1rem", fontWeight: 500, fontSize: 13 }}>
          Scope
          <select
            value={scopeType}
            onChange={(e) => setScopeType(e.target.value)}
            style={{ display: "block", width: "100%", marginTop: 4, padding: "6px 8px", border: "1px solid #d1d5db", borderRadius: 4 }}
          >
            <option value="tenant">Tenant</option>
            <option value="platform_master">Platform master</option>
          </select>
        </label>
        {formError && (
          <p role="alert" style={{ color: "#b91c1c", fontSize: 13, marginBottom: 8 }}>
            {formError}
          </p>
        )}
        <button
          type="submit"
          disabled={submitting}
          style={{ padding: "8px 18px", borderRadius: 6, border: "none", background: submitting ? "#93c5fd" : "#1d4ed8", color: "#fff", fontWeight: 600, cursor: submitting ? "not-allowed" : "pointer" }}
        >
          {submitting ? "Creating…" : "Create"}
        </button>
      </form>
    </main>
  );
}

export default function NewDefinitionPage() {
  return (
    <Suspense>
      <NewDefinitionPageInner />
    </Suspense>
  );
}
