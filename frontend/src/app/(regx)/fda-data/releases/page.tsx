"use client";

import { Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import { fdaData, type FdaDataSourceRelease, type FdaReleaseStatus, isSignedOut, loadError } from "@/lib/api";
import { ProvenanceLabel } from "@/components/ProvenanceLabel";

const STATUS_COLOURS: Record<FdaReleaseStatus, string> = {
  registered: "#314155",
  staged: "#314155",
  validated: "#045e8f",
  under_review: "#8a5a10",
  approved: "#0e6b6b",
  active: "#1a6b46",
  superseded: "#66768b",
  rejected: "#8f2c20",
};

function StatusBadge({ status }: { status: FdaReleaseStatus }) {
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
        if (isSignedOut(err)) {
          router.push(`/signin?next=${encodeURIComponent(window.location.pathname + window.location.search)}`);
        } else {
          setError(loadError(err, "Failed to load FDA data-source releases."));
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
            style={{ fontSize: 13, color: "#045e8f", textDecoration: "none" }}
          >
            Orange Book search
          </Link>
          <Link
            href={`/fda-data/mappings?tenant=${tenantSlug}`}
            style={{ fontSize: 13, color: "#045e8f", textDecoration: "none" }}
          >
            Terminology mappings
          </Link>
          <Link
            href={`/fda-data/releases/new?tenant=${tenantSlug}`}
            style={{
              background: "#045e8f",
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

      <p style={{ fontSize: 13, color: "#66768b", marginTop: -8, marginBottom: "1rem" }}>
        Registering a release only stages it. Activation always requires an explicit,
        separately-permissioned action after review and approval — nothing here
        auto-activates.
      </p>

      <div style={{ marginBottom: "1rem" }}>
        <label style={{ fontSize: 13, color: "#314155" }}>
          Filter by dataset type:{" "}
          <select
            value={datasetFilter}
            onChange={(e) => setDatasetFilter(e.target.value)}
            style={{ padding: "4px 8px", borderRadius: 4, border: "1px solid #dce7f4", fontSize: 13 }}
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
        <p role="alert" style={{ color: "#c0392b" }}>
          {error}
        </p>
      )}
      {!loading && items.length === 0 && !error && (
        <p style={{ color: "#66768b" }}>No FDA data-source releases registered yet.</p>
      )}

      {items.length > 0 && (
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 14 }}>
          <thead>
            <tr style={{ borderBottom: "2px solid #dce7f4", textAlign: "left" }}>
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
              <tr key={release.public_id} style={{ borderBottom: "1px solid #f4f8fe" }}>
                <td style={{ padding: "10px 12px" }}>
                  <Link
                    href={`/fda-data/releases/${release.public_id}?tenant=${tenantSlug}`}
                    style={{ color: "#045e8f", textDecoration: "none" }}
                  >
                    {release.source_name}
                  </Link>
                </td>
                <td style={{ padding: "10px 12px", color: "#66768b", fontFamily: "monospace", fontSize: 12 }}>
                  {release.dataset_type}
                </td>
                <td style={{ padding: "10px 12px", color: "#66768b", fontSize: 12 }}>
                  {release.publication_date ?? "—"}
                </td>
                <td style={{ padding: "10px 12px" }}>
                  <StatusBadge status={release.status} />
                </td>
                <td style={{ padding: "10px 12px", color: "#66768b", fontSize: 12 }}>
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
