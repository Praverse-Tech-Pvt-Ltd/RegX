"use client";

import { Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import {
  migrationBatches,
  templateSources,
  type MigrationBatch,
  type MigrationBatchStatus,
  type TemplateSourcePackage,
  ApiError,
} from "@/lib/api";

const STATUS_COLOURS: Record<MigrationBatchStatus, string> = {
  registered: "#314155",
  extracting: "#045e8f",
  validating: "#045e8f",
  classifying: "#045e8f",
  normalizing: "#045e8f",
  duplicate_detection: "#045e8f",
  importing: "#045e8f",
  completed: "#1a6b46",
  failed: "#8f2c20",
};

function StatusBadge({ status }: { status: MigrationBatchStatus }) {
  return (
    <span
      style={{
        fontSize: 11,
        fontWeight: 600,
        padding: "2px 7px",
        borderRadius: 4,
        background: STATUS_COLOURS[status] ?? "#314155",
        color: "#fff",
        textTransform: "uppercase",
      }}
    >
      {status.replace(/_/g, " ")}
    </span>
  );
}

function MigrationBatchesPageInner() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const tenantSlug = searchParams.get("tenant") ?? "";

  const [items, setItems] = useState<MigrationBatch[]>([]);
  const [sources, setSources] = useState<TemplateSourcePackage[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [showForm, setShowForm] = useState(false);
  const [selectedSource, setSelectedSource] = useState("");
  const [recordsJson, setRecordsJson] = useState("[]");
  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  function load() {
    if (!tenantSlug) return;
    setLoading(true);
    Promise.all([migrationBatches.list(tenantSlug), templateSources.list(tenantSlug)])
      .then(([batchResp, sourceResp]) => {
        setItems(batchResp.results);
        setSources(sourceResp.results);
      })
      .catch((err: unknown) => {
        if (err instanceof ApiError && err.status === 403) {
          router.push(`/signin?next=${encodeURIComponent(window.location.pathname + window.location.search)}`);
        } else {
          setError("Failed to load migration batches.");
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

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    setFormError(null);
    let records: Record<string, unknown>[];
    try {
      records = JSON.parse(recordsJson);
      if (!Array.isArray(records)) throw new Error("not an array");
    } catch {
      setFormError("Records must be a JSON array of neutral record objects.");
      setSubmitting(false);
      return;
    }
    try {
      await migrationBatches.create(tenantSlug, selectedSource, records);
      setShowForm(false);
      setRecordsJson("[]");
      load();
    } catch (err) {
      setFormError(err instanceof ApiError ? err.message : "Batch failed.");
    } finally {
      setSubmitting(false);
    }
  }

  if (!tenantSlug) return null;

  return (
    <main style={{ maxWidth: 900, margin: "2rem auto", padding: "0 1rem" }}>
      <div style={{ marginBottom: "0.5rem" }}>
        <Link href={`/templates?tenant=${tenantSlug}`} style={{ color: "#045e8f", fontSize: 13, textDecoration: "none" }}>
          ← Templates
        </Link>
      </div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "1.5rem" }}>
        <h1 style={{ margin: 0 }}>Migration Batches</h1>
        <button
          onClick={() => setShowForm((s) => !s)}
          disabled={sources.length === 0}
          style={{ background: sources.length === 0 ? "#35b1f6" : "#045e8f", color: "#fff", border: "none", borderRadius: 6, padding: "8px 18px", cursor: sources.length === 0 ? "not-allowed" : "pointer", fontWeight: 600 }}
        >
          {showForm ? "Cancel" : "Start migration batch"}
        </button>
      </div>

      {sources.length === 0 && !loading && (
        <p style={{ color: "#66768b", fontSize: 13 }}>
          Register a{" "}
          <Link href={`/template-sources?tenant=${tenantSlug}`} style={{ color: "#045e8f" }}>
            source package
          </Link>{" "}
          before starting a migration batch.
        </p>
      )}

      {showForm && (
        <form onSubmit={handleCreate} style={{ border: "1px solid #dce7f4", borderRadius: 8, padding: "1rem", marginBottom: "1.5rem" }}>
          <label style={{ display: "block", marginBottom: "0.5rem", fontWeight: 500, fontSize: 13 }}>
            Source package
            <select
              value={selectedSource}
              onChange={(e) => setSelectedSource(e.target.value)}
              required
              style={{ display: "block", width: "100%", marginTop: 4, padding: "6px 8px", border: "1px solid #dce7f4", borderRadius: 4 }}
            >
              <option value="">Select…</option>
              {sources.map((s) => (
                <option key={s.public_id} value={s.public_id}>
                  {s.source_name}
                </option>
              ))}
            </select>
          </label>
          <label style={{ display: "block", marginBottom: "1rem", fontWeight: 500, fontSize: 13 }}>
            Neutral records (JSON array)
            <textarea
              value={recordsJson}
              onChange={(e) => setRecordsJson(e.target.value)}
              rows={6}
              style={{ display: "block", width: "100%", marginTop: 4, padding: "6px 8px", border: "1px solid #dce7f4", borderRadius: 4, boxSizing: "border-box", fontFamily: "monospace", fontSize: 12 }}
            />
          </label>
          {formError && <p role="alert" style={{ color: "#c0392b", fontSize: 13, marginBottom: 8 }}>{formError}</p>}
          <button
            type="submit"
            disabled={submitting}
            style={{ padding: "8px 18px", borderRadius: 6, border: "none", background: submitting ? "#35b1f6" : "#045e8f", color: "#fff", fontWeight: 600, cursor: submitting ? "not-allowed" : "pointer" }}
          >
            {submitting ? "Running…" : "Run batch"}
          </button>
        </form>
      )}

      {loading && <p>Loading…</p>}
      {error && <p role="alert" style={{ color: "#c0392b" }}>{error}</p>}
      {!loading && items.length === 0 && <p style={{ color: "#66768b" }}>No migration batches yet.</p>}

      {items.length > 0 && (
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 14 }}>
          <thead>
            <tr style={{ borderBottom: "2px solid #dce7f4", textAlign: "left" }}>
              <th style={{ padding: "8px 12px" }}>Correlation ID</th>
              <th style={{ padding: "8px 12px" }}>Status</th>
              <th style={{ padding: "8px 12px" }}>Started</th>
              <th style={{ padding: "8px 12px" }}>Imported</th>
              <th style={{ padding: "8px 12px" }}>Excluded</th>
              <th style={{ padding: "8px 12px" }}>Requires review</th>
            </tr>
          </thead>
          <tbody>
            {items.map((batch) => (
              <tr key={batch.public_id} style={{ borderBottom: "1px solid #f4f8fe" }}>
                <td style={{ padding: "10px 12px", fontFamily: "monospace", fontSize: 12 }}>
                  <Link href={`/migration-batches/${batch.public_id}?tenant=${tenantSlug}`} style={{ color: "#045e8f", textDecoration: "none" }}>
                    {batch.correlation_id.slice(0, 8)}…
                  </Link>
                </td>
                <td style={{ padding: "10px 12px" }}>
                  <StatusBadge status={batch.status} />
                </td>
                <td style={{ padding: "10px 12px", color: "#66768b", fontSize: 12 }}>
                  {new Date(batch.started_at).toLocaleString()}
                </td>
                <td style={{ padding: "10px 12px" }}>{batch.counts.imported ?? 0}</td>
                <td style={{ padding: "10px 12px" }}>{batch.counts.excluded ?? 0}</td>
                <td style={{ padding: "10px 12px" }}>{batch.counts.requires_review ?? 0}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </main>
  );
}

export default function MigrationBatchesPage() {
  return (
    <Suspense>
      <MigrationBatchesPageInner />
    </Suspense>
  );
}
