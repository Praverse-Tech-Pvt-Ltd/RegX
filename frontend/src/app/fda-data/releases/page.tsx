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

const DATASET_TYPES = [
  "orange_book_products",
  "orange_book_discontinued",
  "orange_book_patents",
  "orange_book_exclusivity",
  "fda_iid",
  "fda_substance_identifiers",
  "fda_route_terminology",
  "fda_dosage_form_terminology",
];

function FdaReleasesPageInner() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const tenantSlug = searchParams.get("tenant") ?? "";

  const [items, setItems] = useState<FdaDataSourceRelease[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [showForm, setShowForm] = useState(false);
  const [datasetType, setDatasetType] = useState<string>("fda_iid");
  const [sourceName, setSourceName] = useState("");
  const [sourceReference, setSourceReference] = useState("");
  const [rowsJson, setRowsJson] = useState("[]");
  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  function load() {
    if (!tenantSlug) return;
    setLoading(true);
    fdaData.releases
      .list(tenantSlug)
      .then((resp) => setItems(resp.results))
      .catch((err: unknown) => {
        if (err instanceof ApiError && (err.status === 403 || err.status === 401)) {
          router.push("/signin");
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
  }, [tenantSlug]); // eslint-disable-line react-hooks/exhaustive-deps

  async function handleRegister(e: React.FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    setFormError(null);
    let rows: Record<string, unknown>[];
    try {
      rows = JSON.parse(rowsJson);
    } catch {
      setFormError("Rows must be valid JSON (an array of row objects).");
      setSubmitting(false);
      return;
    }
    try {
      await fdaData.releases.register(tenantSlug, {
        dataset_type: datasetType,
        source_name: sourceName,
        official_source_reference: sourceReference,
        rows,
      });
      setShowForm(false);
      setSourceName("");
      setSourceReference("");
      setRowsJson("[]");
      load();
    } catch (err) {
      setFormError(err instanceof ApiError ? err.message : "Registration failed.");
    } finally {
      setSubmitting(false);
    }
  }

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
          <button
            onClick={() => setShowForm((s) => !s)}
            style={{
              background: "#1d4ed8",
              color: "#fff",
              border: "none",
              borderRadius: 6,
              padding: "8px 18px",
              cursor: "pointer",
              fontWeight: 600,
            }}
          >
            {showForm ? "Cancel" : "Register release"}
          </button>
        </div>
      </div>

      <p style={{ fontSize: 13, color: "#6b7280", marginTop: -8, marginBottom: "1rem" }}>
        Registering a release only stages it. Activation always requires an explicit,
        separately-permissioned action after review and approval — nothing here
        auto-activates.
      </p>

      {showForm && (
        <form
          onSubmit={handleRegister}
          style={{ border: "1px solid #e5e7eb", borderRadius: 8, padding: "1rem", marginBottom: "1.5rem" }}
        >
          <label style={{ display: "block", marginBottom: "0.5rem", fontWeight: 500, fontSize: 13 }}>
            Dataset type
            <select
              value={datasetType}
              onChange={(e) => setDatasetType(e.target.value)}
              style={{ display: "block", width: "100%", marginTop: 4, padding: "6px 8px", border: "1px solid #d1d5db", borderRadius: 4 }}
            >
              {DATASET_TYPES.map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </select>
          </label>
          <label style={{ display: "block", marginBottom: "0.5rem", fontWeight: 500, fontSize: 13 }}>
            Source name
            <input
              value={sourceName}
              onChange={(e) => setSourceName(e.target.value)}
              required
              style={{ display: "block", width: "100%", marginTop: 4, padding: "6px 8px", border: "1px solid #d1d5db", borderRadius: 4, boxSizing: "border-box" }}
            />
          </label>
          <label style={{ display: "block", marginBottom: "0.5rem", fontWeight: 500, fontSize: 13 }}>
            Official source reference
            <input
              value={sourceReference}
              onChange={(e) => setSourceReference(e.target.value)}
              required
              placeholder="e.g. FDA Orange Book, 2026-06 edition"
              style={{ display: "block", width: "100%", marginTop: 4, padding: "6px 8px", border: "1px solid #d1d5db", borderRadius: 4, boxSizing: "border-box" }}
            />
          </label>
          <label style={{ display: "block", marginBottom: "1rem", fontWeight: 500, fontSize: 13 }}>
            Rows (JSON array, synthetic/test data only)
            <textarea
              value={rowsJson}
              onChange={(e) => setRowsJson(e.target.value)}
              rows={5}
              style={{ display: "block", width: "100%", marginTop: 4, padding: "6px 8px", border: "1px solid #d1d5db", borderRadius: 4, boxSizing: "border-box", fontFamily: "monospace", fontSize: 12 }}
            />
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
            {submitting ? "Registering…" : "Register"}
          </button>
        </form>
      )}

      {loading && <p>Loading…</p>}
      {error && (
        <p role="alert" style={{ color: "#b91c1c" }}>
          {error}
        </p>
      )}
      {!loading && items.length === 0 && (
        <p style={{ color: "#6b7280" }}>No FDA data-source releases registered yet.</p>
      )}

      {items.length > 0 && (
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 14 }}>
          <thead>
            <tr style={{ borderBottom: "2px solid #e5e7eb", textAlign: "left" }}>
              <th style={{ padding: "8px 12px" }}>Source</th>
              <th style={{ padding: "8px 12px" }}>Dataset type</th>
              <th style={{ padding: "8px 12px" }}>
                Publication date <ProvenanceLabel kind="FDA_SOURCE" />
              </th>
              <th style={{ padding: "8px 12px" }}>Status</th>
              <th style={{ padding: "8px 12px" }}>Records</th>
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
