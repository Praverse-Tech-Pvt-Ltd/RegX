"use client";

import { Suspense, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import { fdaData, ApiError } from "@/lib/api";

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

function NewReleasePageInner() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const tenantSlug = searchParams.get("tenant") ?? "";

  const [datasetType, setDatasetType] = useState<string>("fda_iid");
  const [sourceName, setSourceName] = useState("");
  const [sourceReference, setSourceReference] = useState("");
  const [schemaVersion, setSchemaVersion] = useState("");
  const [rowsJson, setRowsJson] = useState("[]");
  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

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
      const release = await fdaData.releases.register(tenantSlug, {
        dataset_type: datasetType,
        source_name: sourceName,
        official_source_reference: sourceReference,
        rows,
        schema_version: schemaVersion || undefined,
      });
      router.push(`/fda-data/releases/${release.public_id}?tenant=${tenantSlug}`);
    } catch (err) {
      if (err instanceof ApiError && (err.status === 403 || err.status === 401)) {
        router.push(`/signin?next=${encodeURIComponent(window.location.pathname + window.location.search)}`);
        return;
      }
      setFormError(err instanceof ApiError ? err.message : "Registration failed.");
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
        <Link href={`/fda-data/releases?tenant=${tenantSlug}`} style={{ color: "#045e8f", fontSize: 13, textDecoration: "none" }}>
          ← FDA releases
        </Link>
      </div>
      <h1 style={{ margin: "0 0 0.5rem" }}>Register FDA Data-Source Release</h1>
      <p style={{ fontSize: 13, color: "#66768b", marginTop: 0, marginBottom: "1rem" }}>
        Registration only stages the release for validation and review. It is never
        activated automatically — activation is a separate, explicitly permissioned
        step after approval.
      </p>

      <form onSubmit={handleRegister}>
        <label style={{ display: "block", marginBottom: "0.5rem", fontWeight: 500, fontSize: 13 }}>
          Dataset type
          <select
            value={datasetType}
            onChange={(e) => setDatasetType(e.target.value)}
            style={{ display: "block", width: "100%", marginTop: 4, padding: "6px 8px", border: "1px solid #dce7f4", borderRadius: 4 }}
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
            style={{ display: "block", width: "100%", marginTop: 4, padding: "6px 8px", border: "1px solid #dce7f4", borderRadius: 4, boxSizing: "border-box" }}
          />
        </label>
        <label style={{ display: "block", marginBottom: "0.5rem", fontWeight: 500, fontSize: 13 }}>
          Official source reference
          <input
            value={sourceReference}
            onChange={(e) => setSourceReference(e.target.value)}
            required
            placeholder="e.g. FDA Orange Book, 2026-06 edition"
            style={{ display: "block", width: "100%", marginTop: 4, padding: "6px 8px", border: "1px solid #dce7f4", borderRadius: 4, boxSizing: "border-box" }}
          />
        </label>
        <label style={{ display: "block", marginBottom: "0.5rem", fontWeight: 500, fontSize: 13 }}>
          Schema version (optional)
          <input
            value={schemaVersion}
            onChange={(e) => setSchemaVersion(e.target.value)}
            style={{ display: "block", width: "100%", marginTop: 4, padding: "6px 8px", border: "1px solid #dce7f4", borderRadius: 4, boxSizing: "border-box" }}
          />
        </label>
        <label style={{ display: "block", marginBottom: "1rem", fontWeight: 500, fontSize: 13 }}>
          Rows (JSON array, synthetic/test data only)
          <textarea
            value={rowsJson}
            onChange={(e) => setRowsJson(e.target.value)}
            rows={6}
            style={{ display: "block", width: "100%", marginTop: 4, padding: "6px 8px", border: "1px solid #dce7f4", borderRadius: 4, boxSizing: "border-box", fontFamily: "monospace", fontSize: 12 }}
          />
        </label>
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
          {submitting ? "Registering…" : "Register"}
        </button>
      </form>
    </main>
  );
}

export default function NewReleasePage() {
  return (
    <Suspense>
      <NewReleasePageInner />
    </Suspense>
  );
}
