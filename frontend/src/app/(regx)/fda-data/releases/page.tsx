"use client";

import { Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import { fdaData, type FdaDataSourceRelease, type FdaReleaseStatus, ApiError } from "@/lib/api";
import { ProvenanceLabel } from "@/components/ProvenanceLabel";

const STATUS_COLOURS: Record<FdaReleaseStatus, string> = {
  registered: "#374151",
  staged: "#374151",
  validated: "#1d4ed8",
  under_review: "#92400e",
  approved: "#0f766e",
  active: "#166534",
  superseded: "#6b7280",
  rejected: "#991b1b",
};

function StatusBadge({ status }: { status: FdaReleaseStatus }) {
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
      }}
    >
      {status.replace(/_/g, " ")}
    </span>
  );
}

function FdaReleasesPageInner() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const tenantSlug = searchParams.get("tenant") ?? "";

  const [items, setItems] = useState<FdaDataSourceRelease[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [datasetFilter, setDatasetFilter] = useState("");

  function load() {
    if (!tenantSlug) return;
    setLoading(true);
    fdaData.releases
      .list(tenantSlug, datasetFilter ? { dataset_type: datasetFilter } : undefined)
      .then((resp) => setItems(resp.results))
      .catch((err: unknown) => {
        if (err instanceof ApiError && (err.status === 403 || err.status === 401)) {
          router.push(`/signin?next=${encodeURIComponent(window.location.pathname + window.location.search)}`);
        } else {
          setError("Failed to load FDA data-source releases.");
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
  }, [tenantSlug, datasetFilter]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!tenantSlug) return null;

  return (
    <main style={{ maxWidth: 960, margin: "2rem auto", padding: "0 1rem" }}>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          marginBottom: "1.5rem",
        }}
      >
        <h1 style={{ margin: 0 }}>FDA Data-Source Releases</h1>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <Link
            href={`/fda-data/orange-book?tenant=${tenantSlug}`}
            style={{ fontSize: 13, color: "#1d4ed8", textDecoration: "none" }}
          >
            Orange Book search
          </Link>
          <Link
            href={`/fda-data/mappings?tenant=${tenantSlug}`}
            style={{ fontSize: 13, color: "#1d4ed8", textDecoration: "none" }}
          >
            Terminology mappings
          </Link>
          <Link
            href={`/fda-data/releases/new?tenant=${tenantSlug}`}
            style={{
              background: "#1d4ed8",
              color: "#fff",
              border: "none",
              borderRadius: 6,
              padding: "8px 18px",
              cursor: "pointer",
              fontWeight: 600,
              textDecoration: "none",
              display: "inline-block",
            }}
          >
            Register release
          </Link>
        </div>
      </div>

      <p style={{ fontSize: 13, color: "#6b7280", marginTop: -8, marginBottom: "1rem" }}>
        Registering a release only stages it. Activation always requires an explicit,
        separately-permissioned action after review and approval — nothing here
        auto-activates.
      </p>

      <div style={{ marginBottom: "1rem" }}>
        <label style={{ fontSize: 13, color: "#374151" }}>
          Filter by dataset type:{" "}
          <select
            value={datasetFilter}
            onChange={(e) => setDatasetFilter(e.target.value)}
            style={{ padding: "4px 8px", borderRadius: 4, border: "1px solid #d1d5db", fontSize: 13 }}
          >
            <option value="">All</option>
            <option value="orange_book_products">Orange Book products</option>
            <option value="orange_book_discontinued">Orange Book discontinued</option>
            <option value="orange_book_patents">Orange Book patents</option>
            <option value="orange_book_exclusivity">Orange Book exclusivity</option>
            <option value="fda_iid">FDA IID</option>
            <option value="fda_substance_identifiers">FDA substance identifiers</option>
            <option value="fda_route_terminology">FDA route terminology</option>
            <option value="fda_dosage_form_terminology">FDA dosage-form terminology</option>
          </select>
        </label>
      </div>

      {loading && <p>Loading…</p>}
      {error && (
        <p role="alert" style={{ color: "#b91c1c" }}>
          {error}
        </p>
      )}
      {!loading && items.length === 0 && !error && (
        <p style={{ color: "#6b7280" }}>No FDA data-source releases registered yet.</p>
      )}

      {items.length > 0 && (
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 14 }}>
          <thead>
            <tr style={{ borderBottom: "2px solid #e5e7eb", textAlign: "left" }}>
              <th style={{ padding: "8px 12px" }} scope="col">
                Source
              </th>
              <th style={{ padding: "8px 12px" }} scope="col">
                Dataset type
              </th>
              <th style={{ padding: "8px 12px" }} scope="col">
                Publication date <ProvenanceLabel kind="FDA_SOURCE" />
              </th>
              <th style={{ padding: "8px 12px" }} scope="col">
                Status
              </th>
              <th style={{ padding: "8px 12px" }} scope="col">
                Records
              </th>
            </tr>
          </thead>
          <tbody>
            {items.map((release) => (
              <tr key={release.public_id} style={{ borderBottom: "1px solid #f3f4f6" }}>
                <td style={{ padding: "10px 12px" }}>
                  <Link
                    href={`/fda-data/releases/${release.public_id}?tenant=${tenantSlug}`}
                    style={{ color: "#1d4ed8", textDecoration: "none" }}
                  >
                    {release.source_name}
                  </Link>
                </td>
                <td style={{ padding: "10px 12px", color: "#6b7280", fontFamily: "monospace", fontSize: 12 }}>
                  {release.dataset_type}
                </td>
                <td style={{ padding: "10px 12px", color: "#6b7280", fontSize: 12 }}>
                  {release.publication_date ?? "—"}
                </td>
                <td style={{ padding: "10px 12px" }}>
                  <StatusBadge status={release.status} />
                </td>
                <td style={{ padding: "10px 12px", color: "#6b7280", fontSize: 12 }}>
                  {release.record_count_imported}/{release.record_count_extracted}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </main>
  );
}

export default function FdaReleasesPage() {
  return (
    <Suspense>
      <FdaReleasesPageInner />
    </Suspense>
  );
}
