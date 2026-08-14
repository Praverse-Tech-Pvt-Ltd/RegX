"use client";

import { Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams, useParams } from "next/navigation";
import Link from "next/link";
import { fdaData, type FdaReconciliationReport, ApiError } from "@/lib/api";

const RESULT_COLOURS: Record<string, string> = {
  imported: "#166534",
  duplicate: "#374151",
  failed: "#991b1b",
  review_required: "#92400e",
};

function ReconciliationPageInner() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const params = useParams<{ publicId: string }>();
  const tenantSlug = searchParams.get("tenant") ?? "";
  const publicId = params.publicId;

  const [report, setReport] = useState<FdaReconciliationReport | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!tenantSlug) {
      router.push("/tenants");
      return;
    }
    setLoading(true);
    fdaData.releases
      .reconciliationJson(tenantSlug, publicId)
      .then(setReport)
      .catch((err: unknown) => {
        if (err instanceof ApiError && err.status === 403) {
          setError("You do not have permission to view this reconciliation report.");
        } else if (err instanceof ApiError && err.status === 401) {
          router.push("/signin");
        } else if (err instanceof ApiError && err.status === 404) {
          setError("Release not found.");
        } else {
          setError("Failed to load reconciliation report.");
        }
      })
      .finally(() => setLoading(false));
  }, [tenantSlug, publicId]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!tenantSlug) return null;

  return (
    <main style={{ maxWidth: 900, margin: "2rem auto", padding: "0 1rem" }}>
      <div style={{ marginBottom: "0.5rem" }}>
        <Link
          href={`/fda-data/releases/${publicId}?tenant=${tenantSlug}`}
          style={{ color: "#1d4ed8", fontSize: 13, textDecoration: "none" }}
        >
          ← Release detail
        </Link>
      </div>
      <h1 style={{ margin: "0 0 0.5rem" }}>Reconciliation Summary</h1>

      {loading && <p>Loading…</p>}
      {error && (
        <p role="alert" style={{ color: "#b91c1c" }}>
          {error}
        </p>
      )}

      {report && (
        <>
          <dl style={{ display: "grid", gridTemplateColumns: "160px 1fr", rowGap: 8, fontSize: 14, marginBottom: "1.5rem" }}>
            <dt style={{ color: "#6b7280" }}>Expected</dt>
            <dd style={{ margin: 0 }}>{report.counts.expected}</dd>
            <dt style={{ color: "#6b7280" }}>Extracted</dt>
            <dd style={{ margin: 0 }}>{report.counts.extracted}</dd>
            <dt style={{ color: "#6b7280" }}>Imported</dt>
            <dd style={{ margin: 0 }}>{report.counts.imported}</dd>
            <dt style={{ color: "#6b7280" }}>Failed</dt>
            <dd style={{ margin: 0 }}>{report.counts.failed}</dd>
          </dl>

          <Link
            href={fdaData.releases.reconciliationCsvUrl(publicId)}
            style={{
              display: "inline-block",
              marginBottom: "1rem",
              background: "#374151",
              color: "#fff",
              borderRadius: 6,
              padding: "6px 14px",
              fontSize: 13,
              textDecoration: "none",
              fontWeight: 600,
            }}
          >
            Download CSV
          </Link>

          {report.results.length === 0 ? (
            <p style={{ color: "#6b7280" }}>No row-level results recorded for this release.</p>
          ) : (
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
              <thead>
                <tr style={{ borderBottom: "2px solid #e5e7eb", textAlign: "left" }}>
                  <th style={{ padding: "8px 10px" }} scope="col">
                    Row
                  </th>
                  <th style={{ padding: "8px 10px" }} scope="col">
                    Result
                  </th>
                  <th style={{ padding: "8px 10px" }} scope="col">
                    Reason code
                  </th>
                </tr>
              </thead>
              <tbody>
                {report.results.map((r) => (
                  <tr key={r.public_id} style={{ borderBottom: "1px solid #f3f4f6" }}>
                    <td style={{ padding: "8px 10px", fontFamily: "monospace" }}>{r.row_locator}</td>
                    <td style={{ padding: "8px 10px" }}>
                      <span
                        style={{
                          fontSize: 11,
                          fontWeight: 600,
                          padding: "2px 7px",
                          borderRadius: 4,
                          background: RESULT_COLOURS[r.result] ?? "#374151",
                          color: "#fff",
                          textTransform: "uppercase",
                        }}
                      >
                        {r.result.replace("_", " ")}
                      </span>
                    </td>
                    <td style={{ padding: "8px 10px", color: "#6b7280" }}>{r.reason_code || "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </>
      )}
    </main>
  );
}

export default function ReconciliationPage() {
  return (
    <Suspense>
      <ReconciliationPageInner />
    </Suspense>
  );
}
