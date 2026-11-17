"use client";

import { Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams, useParams } from "next/navigation";
import Link from "next/link";
import { fdaData, type TerminologyMapping, type AffectedRecord, ApiError, isSignedOut, loadError } from "@/lib/api";
import { ProvenanceLabel } from "@/components/ProvenanceLabel";

function MappingDetailInner() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const params = useParams<{ publicId: string }>();
  const tenantSlug = searchParams.get("tenant") ?? "";
  const publicId = params.publicId;

  const [mapping, setMapping] = useState<TerminologyMapping | null>(null);
  const [records, setRecords] = useState<AffectedRecord[]>([]);
  const [count, setCount] = useState(0);
  const [page, setPage] = useState(1);
  const [hasNext, setHasNext] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  function loadRecords(targetPage: number) {
    setLoading(true);
    setError(null);
    Promise.all([
      fdaData.mappings.get(tenantSlug, publicId),
      fdaData.mappings.affectedRecords(tenantSlug, publicId, targetPage),
    ])
      .then(([m, recs]) => {
        setMapping(m);
        setRecords(recs.results);
        setCount(recs.count);
        setHasNext(Boolean(recs.next));
        setPage(targetPage);
      })
      .catch((err: unknown) => {
        if (err instanceof ApiError && err.status === 404) setError("Mapping not found.");
        else if (isSignedOut(err))
          router.push(`/signin?next=${encodeURIComponent(window.location.pathname + window.location.search)}`);
        else setError(loadError(err, "Failed to load affected records."));
      })
      .finally(() => setLoading(false));
  }

  useEffect(() => {
    if (!tenantSlug) {
      router.push("/tenants");
      return;
    }
    loadRecords(1);
  }, [tenantSlug, publicId]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!tenantSlug) return null;

  return (
    <main style={{ maxWidth: 1000, margin: "2rem auto", padding: "0 1rem" }}>
      <div style={{ marginBottom: "0.5rem" }}>
        <Link
          href={`/fda-data/mappings?tenant=${tenantSlug}`}
          style={{ color: "#045e8f", fontSize: 13, textDecoration: "none" }}
        >
          ← Terminology mapping review
        </Link>
      </div>
      <h1 style={{ margin: "0 0 0.25rem" }}>Affected records</h1>

      {loading && <p>Loading…</p>}
      {error && (
        <div role="alert" style={{ color: "#c0392b" }}>
          <p>{error}</p>
          <button
            onClick={() => loadRecords(page)}
            style={{
              color: "#fff",
              background: "#045e8f",
              border: "none",
              borderRadius: 6,
              padding: "6px 12px",
              cursor: "pointer",
              fontWeight: 600,
              fontSize: 12,
            }}
          >
            Retry
          </button>
        </div>
      )}

      {mapping && !error && (
        <>
          <section
            style={{
              background: "#f8fbff",
              border: "1px solid #dce7f4",
              borderRadius: 8,
              padding: "1rem 1.25rem",
              marginBottom: "1.25rem",
            }}
          >
            <dl
              style={{
                display: "grid",
                gridTemplateColumns: "220px 1fr",
                rowGap: 8,
                fontSize: 14,
                margin: 0,
              }}
            >
              <dt style={{ color: "#66768b" }}>Source value</dt>
              <dd style={{ margin: 0, fontFamily: "monospace" }}>
                {mapping.source_raw_value} <ProvenanceLabel kind="FDA_SOURCE" />
              </dd>

              <dt style={{ color: "#66768b" }}>Mapping type</dt>
              <dd style={{ margin: 0 }}>{mapping.mapping_type.replace("_", " ")}</dd>

              <dt style={{ color: "#66768b" }}>Proposed value</dt>
              <dd style={{ margin: 0 }}>{mapping.proposed_controlled_value ?? "—"}</dd>

              {mapping.mapping_type === "substance" && (
                <>
                  <dt style={{ color: "#66768b" }}>Proposed UNII</dt>
                  <dd style={{ margin: 0, fontFamily: "monospace" }}>
                    {mapping.proposed_unii ?? "—"}
                  </dd>
                  <dt style={{ color: "#66768b" }}>Proposed CAS</dt>
                  <dd style={{ margin: 0, fontFamily: "monospace" }}>
                    {mapping.proposed_cas_number ?? "—"}
                  </dd>
                  <dt style={{ color: "#66768b" }}>Mapping method</dt>
                  <dd style={{ margin: 0 }}>{mapping.mapping_method ?? "—"}</dd>
                </>
              )}

              <dt style={{ color: "#66768b" }}>Status</dt>
              <dd style={{ margin: 0, textTransform: "uppercase", fontWeight: 600 }}>
                {mapping.status.replace("_", " ")}
              </dd>

              <dt style={{ color: "#66768b" }}>FDA release</dt>
              <dd style={{ margin: 0, fontFamily: "monospace", fontSize: 12 }}>
                {mapping.release_public_id ?? "platform master (no single release)"}
              </dd>

              <dt style={{ color: "#66768b" }}>Affected records</dt>
              <dd style={{ margin: 0 }}>{count}</dd>
            </dl>
          </section>

          {records.length === 0 && (
            <p style={{ color: "#66768b" }}>No records reference this mapping&apos;s raw value.</p>
          )}

          {records.length > 0 && (
            <div style={{ overflowX: "auto" }}>
              <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
                <thead>
                  <tr style={{ borderBottom: "2px solid #dce7f4", textAlign: "left" }}>
                    <th style={{ padding: "8px 10px" }} scope="col">
                      Record
                    </th>
                    <th style={{ padding: "8px 10px" }} scope="col">
                      Dataset
                    </th>
                    <th style={{ padding: "8px 10px" }} scope="col">
                      Raw value
                    </th>
                    <th style={{ padding: "8px 10px" }} scope="col">
                      Normalized
                    </th>
                    <th style={{ padding: "8px 10px" }} scope="col">
                      Calculability
                    </th>
                    <th style={{ padding: "8px 10px" }} scope="col">
                      Blocked
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {records.map((r) => (
                    <tr key={r.record_public_id} style={{ borderBottom: "1px solid #f4f8fe" }}>
                      <td style={{ padding: "8px 10px", fontFamily: "monospace", fontSize: 11 }}>
                        {r.dataset_type.startsWith("orange_book") ? (
                          <Link
                            href={`/fda-data/orange-book/${r.record_public_id}?tenant=${tenantSlug}`}
                            style={{ color: "#045e8f", textDecoration: "none" }}
                          >
                            {r.record_public_id.slice(0, 8)}…
                          </Link>
                        ) : (
                          `${r.record_public_id.slice(0, 8)}…`
                        )}
                      </td>
                      <td style={{ padding: "8px 10px", color: "#66768b" }}>{r.dataset_type}</td>
                      <td style={{ padding: "8px 10px", fontFamily: "monospace" }}>{r.raw_value}</td>
                      <td style={{ padding: "8px 10px" }}>{r.normalized_value ?? "—"}</td>
                      <td style={{ padding: "8px 10px", color: "#66768b" }}>
                        {r.calculability_status ?? "—"}
                      </td>
                      <td style={{ padding: "8px 10px" }}>
                        {r.blocked ? (
                          <span style={{ color: "#c0392b", fontWeight: 600 }}>Blocked</span>
                        ) : (
                          <span style={{ color: "#1a6b46" }}>OK</span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {(page > 1 || hasNext) && (
            <div style={{ display: "flex", gap: 8, marginTop: 12, alignItems: "center" }}>
              <button
                onClick={() => loadRecords(page - 1)}
                disabled={page <= 1 || loading}
                style={pagerButtonStyle}
              >
                Previous
              </button>
              <span style={{ fontSize: 13, color: "#66768b" }}>Page {page}</span>
              <button
                onClick={() => loadRecords(page + 1)}
                disabled={!hasNext || loading}
                style={pagerButtonStyle}
              >
                Next
              </button>
            </div>
          )}
        </>
      )}
    </main>
  );
}

const pagerButtonStyle: React.CSSProperties = {
  fontSize: 13,
  padding: "5px 12px",
  borderRadius: 6,
  border: "1px solid #dce7f4",
  background: "#fff",
  cursor: "pointer",
};

export default function MappingDetailPage() {
  return (
    <Suspense>
      <MappingDetailInner />
    </Suspense>
  );
}
