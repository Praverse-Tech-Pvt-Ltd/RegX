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
      if (err instanceof ApiError && err.status === 401) {
        router.push(`/signin?next=${encodeURIComponent(window.location.pathname + window.location.search)}`);
        return;
      }
      if (err instanceof ApiError && err.status === 403) {
        setFormError(
          scopeType === "platform_master"
            ? "Creating platform-master content requires a separate, explicit platform-level authorization. Your ordinary create-definition permission does not grant it."
            : err.message || "You do not have permission to perform this action."
        );
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
        <p role="alert" style={{ color: "#c0392b" }}>
          Select a tenant first.
        </p>
      </main>
    );
  }

  return (
    <main style={{ maxWidth: 700, margin: "2rem auto", padding: "0 1rem" }}>
      <div style={{ marginBottom: "0.5rem" }}>
        <Link href={`/iig-checklists?tenant=${tenantSlug}`} style={{ color: "#045e8f", fontSize: 13, textDecoration: "none" }}>
          ← Checklist definitions
        </Link>
      </div>
      <h1 style={{ margin: "0 0 0.5rem" }}>New Checklist Definition</h1>
      <p style={{ fontSize: 13, color: "#66768b", marginTop: 0, marginBottom: "1rem" }}>
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
            style={{ display: "block", width: "100%", marginTop: 4, padding: "6px 8px", border: "1px solid #dce7f4", borderRadius: 4, boxSizing: "border-box" }}
          />
        </label>
        <label style={{ display: "block", marginBottom: "0.5rem", fontWeight: 500, fontSize: 13 }}>
          Title
          <input
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            required
            style={{ display: "block", width: "100%", marginTop: 4, padding: "6px 8px", border: "1px solid #dce7f4", borderRadius: 4, boxSizing: "border-box" }}
          />
        </label>
        <label style={{ display: "block", marginBottom: "0.5rem", fontWeight: 500, fontSize: 13 }}>
          Description (optional)
          <textarea
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            rows={3}
            style={{ display: "block", width: "100%", marginTop: 4, padding: "6px 8px", border: "1px solid #dce7f4", borderRadius: 4, boxSizing: "border-box" }}
          />
        </label>
        <label style={{ display: "block", marginBottom: "1rem", fontWeight: 500, fontSize: 13 }}>
          Scope
          <select
            value={scopeType}
            onChange={(e) => setScopeType(e.target.value)}
            style={{ display: "block", width: "100%", marginTop: 4, padding: "6px 8px", border: "1px solid #dce7f4", borderRadius: 4 }}
          >
            <option value="tenant">Tenant</option>
            <option value="platform_master">Platform master</option>
          </select>
        </label>
        {scopeType === "platform_master" && (
          <p style={{ fontSize: 12, color: "#8a5a10", marginTop: -4, marginBottom: "1rem" }}>
            Platform-master content is visible to every tenant and requires a separate,
            explicit platform-level authorization. An ordinary create-definition
            permission does not grant it — the server will reject this request unless
            you hold that authorization.
          </p>
        )}
        {formError && (
          <p role="alert" style={{ color: "#c0392b", fontSize: 13, marginBottom: 8 }}>
            {formError}
          </p>
        )}
        <button
          type="submit"
          disabled={submitting}
          style={{ padding: "8px 18px", borderRadius: 6, border: "none", background: submitting ? "#35b1f6" : "#045e8f", color: "#fff", fontWeight: 600, cursor: submitting ? "not-allowed" : "pointer" }}
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
