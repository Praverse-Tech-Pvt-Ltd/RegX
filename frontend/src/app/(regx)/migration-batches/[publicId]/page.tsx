"use client";

import { Suspense, useEffect, useState } from "react";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import {
  migrationBatches,
  type MigrationBatch,
  type MigrationRecordResult,
  type ReconciliationReport,
  ApiError,
} from "@/lib/api";

function resultColour(result: MigrationRecordResult["result"]) {
  const colours: Record<string, string> = {
    imported: "#166534",
    skipped: "#6b7280",
    excluded: "#92400e",
    duplicate: "#92400e",
    failed: "#991b1b",
    requires_review: "#1d4ed8",
  };
  return colours[result] ?? "#374151";
}

function MigrationBatchDetailPageInner() {
  const { publicId } = useParams<{ publicId: string }>();
  const searchParams = useSearchParams();
  const tenantSlug = searchParams.get("tenant") ?? "";
  const router = useRouter();

  const [batch, setBatch] = useState<MigrationBatch | null>(null);
  const [results, setResults] = useState<MigrationRecordResult[]>([]);
  const [report, setReport] = useState<ReconciliationReport | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [resolutions, setResolutions] = useState<Record<string, string>>({});
  const [reviewSubmitting, setReviewSubmitting] = useState(false);
  const [reviewError, setReviewError] = useState<string | null>(null);

  async function load() {
    if (!tenantSlug) return;
    try {
      const [batchData, resultsData] = await Promise.all([
        migrationBatches.get(tenantSlug, publicId),
        migrationBatches.results(tenantSlug, publicId),
      ]);
      setBatch(batchData);
      setResults(resultsData.results);
      // Reconciliation reports require the export-reconciliation permission
      // (VP/tenant admin) -- fetched separately so a Doer without that
      // permission still sees their batch and per-record results instead
      // of a blanket page failure.
      try {
        setReport(await migrationBatches.reconciliation(tenantSlug, publicId));
      } catch (reportErr) {
        if (reportErr instanceof ApiError && reportErr.status === 403) {
          setReport(null);
        } else {
          throw reportErr;
        }
      }
    } catch (err) {
      if (err instanceof ApiError && err.status === 403) {
        router.push(`/signin?next=${encodeURIComponent(window.location.pathname + window.location.search)}`);
      } else {
        setError("Failed to load migration batch.");
      }
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    if (!tenantSlug) {
      router.push("/tenants");
      return;
    }
    load();
  }, [tenantSlug, publicId]); // eslint-disable-line react-hooks/exhaustive-deps

  async function submitDuplicateReview() {
    const entries = Object.entries(resolutions).filter(([, v]) => v);
    if (entries.length === 0) return;
    setReviewSubmitting(true);
    setReviewError(null);
    try {
      await migrationBatches.review(
        tenantSlug,
        publicId,
        entries.map(([public_id, resolution]) => ({ public_id, resolution }))
      );
      setResolutions({});
      await load();
    } catch (err) {
      setReviewError(err instanceof ApiError ? err.message : "Review submission failed.");
    } finally {
      setReviewSubmitting(false);
    }
  }

  if (loading) return <main style={{ maxWidth: 900, margin: "2rem auto", padding: "0 1rem" }}><p>Loading…</p></main>;
  if (error) return <main style={{ maxWidth: 900, margin: "2rem auto", padding: "0 1rem" }}><p role="alert" style={{ color: "#b91c1c" }}>{error}</p></main>;
  if (!batch) return null;

  const csvUrl = `${process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000"}/api/regx/v1/migration-batches/${publicId}/reconciliation.csv`;

  return (
    <main style={{ maxWidth: 960, margin: "2rem auto", padding: "0 1rem" }}>
      <div style={{ marginBottom: "0.5rem" }}>
        <Link href={`/migration-batches?tenant=${tenantSlug}`} style={{ color: "#1d4ed8", fontSize: 13, textDecoration: "none" }}>
          ← All migration batches
        </Link>
      </div>

      <h1 style={{ margin: "0 0 4px" }}>Migration Batch</h1>
      <p style={{ color: "#6b7280", fontFamily: "monospace", fontSize: 13 }}>{batch.correlation_id}</p>

      <section style={{ marginBottom: "1.5rem" }}>
        <h2 style={{ fontSize: 16, marginBottom: "0.5rem" }}>Reconciliation summary</h2>
        {!report && (
          <p style={{ color: "#6b7280", fontSize: 13 }}>
            Reconciliation reports are restricted to reviewers with export permission.
          </p>
        )}
        {report && (
          <>
            <table style={{ borderCollapse: "collapse", fontSize: 13 }}>
              <tbody>
                {Object.entries(report.counts).map(([key, value]) => (
                  <tr key={key}>
                    <td style={{ padding: "2px 12px 2px 0", color: "#6b7280", textTransform: "capitalize" }}>
                      {key.replace(/_/g, " ")}
                    </td>
                    <td style={{ padding: "2px 0", fontWeight: 600 }}>{value}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div style={{ marginTop: 8 }}>
              <a href={csvUrl} style={{ fontSize: 13, color: "#1d4ed8" }}>
                Download reconciliation.csv
              </a>
            </div>
          </>
        )}
      </section>

      <section style={{ marginBottom: "1.5rem" }}>
        <h2 style={{ fontSize: 16, marginBottom: "0.5rem" }}>Record-level results ({results.length})</h2>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
          <thead>
            <tr style={{ borderBottom: "2px solid #e5e7eb", textAlign: "left" }}>
              <th style={{ padding: "6px 10px" }}>Source identifier</th>
              <th style={{ padding: "6px 10px" }}>Result</th>
              <th style={{ padding: "6px 10px" }}>Reason</th>
            </tr>
          </thead>
          <tbody>
            {results.map((r) => (
              <tr key={r.public_id} style={{ borderBottom: "1px solid #f3f4f6" }}>
                <td style={{ padding: "6px 10px", fontFamily: "monospace" }}>{r.source_record_identifier}</td>
                <td style={{ padding: "6px 10px" }}>
                  <span
                    style={{
                      fontSize: 11,
                      fontWeight: 600,
                      padding: "2px 6px",
                      borderRadius: 4,
                      background: resultColour(r.result),
                      color: "#fff",
                      textTransform: "uppercase",
                    }}
                  >
                    {r.result.replace(/_/g, " ")}
                  </span>
                </td>
                <td style={{ padding: "6px 10px", color: "#6b7280" }}>{r.reason_code || "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      {report && report.normalization_mappings.length > 0 && (
        <section style={{ marginBottom: "1.5rem" }}>
          <h2 style={{ fontSize: 16, marginBottom: "0.5rem" }}>
            Normalization mappings ({report.normalization_mappings.length})
          </h2>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
            <thead>
              <tr style={{ borderBottom: "2px solid #e5e7eb", textAlign: "left" }}>
                <th style={{ padding: "6px 10px" }}>Record</th>
                <th style={{ padding: "6px 10px" }}>Rule</th>
                <th style={{ padding: "6px 10px" }}>Raw value</th>
                <th style={{ padding: "6px 10px" }}>Normalized value</th>
              </tr>
            </thead>
            <tbody>
              {report.normalization_mappings.map((m) => (
                <tr key={m.public_id} style={{ borderBottom: "1px solid #f3f4f6" }}>
                  <td style={{ padding: "6px 10px", fontFamily: "monospace" }}>{m.source_record_identifier}</td>
                  <td style={{ padding: "6px 10px", color: "#6b7280" }}>{m.normalization_rule}</td>
                  <td style={{ padding: "6px 10px", maxWidth: 260, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }} title={m.raw_value}>
                    {m.raw_value}
                  </td>
                  <td style={{ padding: "6px 10px", maxWidth: 260, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }} title={m.normalized_value}>
                    {m.normalized_value}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}

      {report && (
      <section>
        <h2 style={{ fontSize: 16, marginBottom: "0.5rem" }}>
          Duplicate candidates ({report.duplicate_candidates.length})
        </h2>
        {report.duplicate_candidates.length === 0 && (
          <p style={{ color: "#6b7280", fontSize: 13 }}>No duplicate candidates for this batch.</p>
        )}
        {report.duplicate_candidates.length > 0 && (
          <>
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
              <thead>
                <tr style={{ borderBottom: "2px solid #e5e7eb", textAlign: "left" }}>
                  <th style={{ padding: "6px 10px" }}>Match type</th>
                  <th style={{ padding: "6px 10px" }}>Current resolution</th>
                  <th style={{ padding: "6px 10px" }}>Set resolution</th>
                </tr>
              </thead>
              <tbody>
                {report.duplicate_candidates.map((candidate) => (
                  <tr key={candidate.public_id} style={{ borderBottom: "1px solid #f3f4f6" }}>
                    <td style={{ padding: "6px 10px", color: "#6b7280" }}>{candidate.match_type.replace(/_/g, " ")}</td>
                    <td style={{ padding: "6px 10px", textTransform: "capitalize" }}>{candidate.resolution}</td>
                    <td style={{ padding: "6px 10px" }}>
                      <select
                        value={resolutions[candidate.public_id] ?? ""}
                        onChange={(e) =>
                          setResolutions((prev) => ({ ...prev, [candidate.public_id]: e.target.value }))
                        }
                        style={{ fontSize: 12, padding: "3px 6px", borderRadius: 4, border: "1px solid #d1d5db" }}
                      >
                        <option value="">— no change —</option>
                        <option value="same">Same</option>
                        <option value="distinct">Distinct</option>
                        <option value="superseded">Superseded</option>
                        <option value="merge_approved">Merge approved</option>
                      </select>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {reviewError && <p role="alert" style={{ color: "#b91c1c", fontSize: 13, marginTop: 8 }}>{reviewError}</p>}
            <button
              onClick={submitDuplicateReview}
              disabled={reviewSubmitting}
              style={{
                marginTop: 10,
                padding: "7px 16px",
                borderRadius: 6,
                border: "none",
                background: reviewSubmitting ? "#93c5fd" : "#1d4ed8",
                color: "#fff",
                fontWeight: 600,
                cursor: reviewSubmitting ? "not-allowed" : "pointer",
                fontSize: 13,
              }}
            >
              {reviewSubmitting ? "Submitting…" : "Submit duplicate resolutions"}
            </button>
          </>
        )}
      </section>
      )}
    </main>
  );
}

export default function MigrationBatchDetailPage() {
  return (
    <Suspense>
      <MigrationBatchDetailPageInner />
    </Suspense>
  );
}
