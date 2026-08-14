"use client";

import { Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import { templates, type RegulatoryTemplate, type TemplateLifecycleStatus, ApiError } from "@/lib/api";

const STATUS_COLOURS: Record<TemplateLifecycleStatus, string> = {
  draft: "#374151",
  imported: "#1d4ed8",
  under_review: "#92400e",
  returned: "#92400e",
  approved: "#0f766e",
  active: "#166534",
  superseded: "#6b7280",
  retired: "#6b7280",
  rejected: "#991b1b",
};

function StatusBadge({ status }: { status: TemplateLifecycleStatus }) {
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
        letterSpacing: "0.03em",
      }}
    >
      {status.replace(/_/g, " ")}
    </span>
  );
}

function TemplatesPageInner() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const tenantSlug = searchParams.get("tenant") ?? "";

  const [items, setItems] = useState<RegulatoryTemplate[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState("");

  useEffect(() => {
    if (!tenantSlug) {
      router.push("/tenants");
      return;
    }
    setLoading(true);
    templates
      .list(tenantSlug, statusFilter ? { status: statusFilter } : undefined)
      .then((resp) => setItems(resp.results))
      .catch((err: unknown) => {
        if (err instanceof ApiError && err.status === 403) {
          router.push(`/signin?next=${encodeURIComponent(window.location.pathname + window.location.search)}`);
        } else {
          setError("Failed to load templates.");
        }
      })
      .finally(() => setLoading(false));
  }, [tenantSlug, statusFilter]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!tenantSlug) return null;

  return (
    <main style={{ maxWidth: 960, margin: "2rem auto", padding: "0 1rem" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "1.5rem" }}>
        <h1 style={{ margin: 0 }}>Regulatory Templates</h1>
        <div style={{ display: "flex", gap: 8 }}>
          <Link
            href={`/template-sources?tenant=${tenantSlug}`}
            style={{ fontSize: 13, color: "#1d4ed8", textDecoration: "none", alignSelf: "center" }}
          >
            Source packages
          </Link>
          <Link
            href={`/migration-batches?tenant=${tenantSlug}`}
            style={{ fontSize: 13, color: "#1d4ed8", textDecoration: "none", alignSelf: "center" }}
          >
            Migration batches
          </Link>
        </div>
      </div>

      <div style={{ marginBottom: "1rem" }}>
        <label style={{ fontSize: 13, color: "#374151" }}>
          Filter by status:{" "}
          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
            style={{ padding: "4px 8px", borderRadius: 4, border: "1px solid #d1d5db", fontSize: 13 }}
          >
            <option value="">All</option>
            <option value="draft">Draft</option>
            <option value="imported">Imported</option>
            <option value="under_review">Under review</option>
            <option value="returned">Returned</option>
            <option value="approved">Approved</option>
            <option value="active">Active</option>
            <option value="superseded">Superseded</option>
            <option value="retired">Retired</option>
            <option value="rejected">Rejected</option>
          </select>
        </label>
      </div>

      {loading && <p>Loading…</p>}
      {error && <p role="alert" style={{ color: "#b91c1c" }}>{error}</p>}
      {!loading && items.length === 0 && (
        <p style={{ color: "#6b7280" }}>
          No templates yet. Register a source package and start a migration batch to import one.
        </p>
      )}

      {items.length > 0 && (
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 14 }}>
          <thead>
            <tr style={{ borderBottom: "2px solid #e5e7eb", textAlign: "left" }}>
              <th style={{ padding: "8px 12px" }}>Canonical code</th>
              <th style={{ padding: "8px 12px" }}>Title</th>
              <th style={{ padding: "8px 12px" }}>Category</th>
              <th style={{ padding: "8px 12px" }}>Status</th>
            </tr>
          </thead>
          <tbody>
            {items.map((t) => (
              <tr key={t.public_id} style={{ borderBottom: "1px solid #f3f4f6" }}>
                <td style={{ padding: "10px 12px", fontFamily: "monospace", fontSize: 13 }}>
                  <Link
                    href={`/templates/${t.public_id}?tenant=${tenantSlug}`}
                    style={{ color: "#1d4ed8", textDecoration: "none" }}
                  >
                    {t.canonical_code}
                  </Link>
                </td>
                <td style={{ padding: "10px 12px" }}>{t.title}</td>
                <td style={{ padding: "10px 12px", color: "#6b7280" }}>{t.category || "—"}</td>
                <td style={{ padding: "10px 12px" }}>
                  <StatusBadge status={t.lifecycle_status} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </main>
  );
}

export default function TemplatesPage() {
  return (
    <Suspense>
      <TemplatesPageInner />
    </Suspense>
  );
}
