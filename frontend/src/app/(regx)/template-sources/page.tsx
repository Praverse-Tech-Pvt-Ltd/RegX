"use client";

import { Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import { templateSources, type TemplateSourcePackage, ApiError } from "@/lib/api";

function ApprovalBadge({ state }: { state: TemplateSourcePackage["approval_state"] }) {
  const colours: Record<string, string> = { pending: "#8a5a10", approved: "#1a6b46", rejected: "#8f2c20" };
  return (
    <span
      style={{
        fontSize: 11,
        fontWeight: 600,
        padding: "2px 7px",
        borderRadius: 4,
        background: colours[state] ?? "#314155",
        color: "#fff",
        textTransform: "uppercase",
      }}
    >
      {state}
    </span>
  );
}

function TemplateSourcesPageInner() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const tenantSlug = searchParams.get("tenant") ?? "";

  const [items, setItems] = useState<TemplateSourcePackage[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [showForm, setShowForm] = useState(false);
  const [sourceName, setSourceName] = useState("");
  const [sourceType, setSourceType] = useState("anda_checklist");
  const [sourcePath, setSourcePath] = useState("");
  const [payloadJson, setPayloadJson] = useState('{\n  "rows": []\n}');
  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  function load() {
    if (!tenantSlug) return;
    setLoading(true);
    templateSources
      .list(tenantSlug)
      .then((resp) => setItems(resp.results))
      .catch((err: unknown) => {
        if (err instanceof ApiError && err.status === 403) {
          router.push(`/signin?next=${encodeURIComponent(window.location.pathname + window.location.search)}`);
        } else {
          setError("Failed to load source packages.");
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
    let payload: Record<string, unknown>;
    try {
      payload = JSON.parse(payloadJson);
    } catch {
      setFormError("Payload must be valid JSON.");
      setSubmitting(false);
      return;
    }
    try {
      await templateSources.register(tenantSlug, {
        source_name: sourceName,
        source_type: sourceType,
        source_path_or_reference: sourcePath,
        payload,
      });
      setShowForm(false);
      setSourceName("");
      setSourcePath("");
      setPayloadJson('{\n  "rows": []\n}');
      load();
    } catch (err) {
      setFormError(err instanceof ApiError ? err.message : "Registration failed.");
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
        <h1 style={{ margin: 0 }}>Template Source Packages</h1>
        <button
          onClick={() => setShowForm((s) => !s)}
          style={{ background: "#045e8f", color: "#fff", border: "none", borderRadius: 6, padding: "8px 18px", cursor: "pointer", fontWeight: 600 }}
        >
          {showForm ? "Cancel" : "Register source package"}
        </button>
      </div>

      {showForm && (
        <form onSubmit={handleRegister} style={{ border: "1px solid #dce7f4", borderRadius: 8, padding: "1rem", marginBottom: "1.5rem" }}>
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
            Source type
            <select
              value={sourceType}
              onChange={(e) => setSourceType(e.target.value)}
              style={{ display: "block", width: "100%", marginTop: 4, padding: "6px 8px", border: "1px solid #dce7f4", borderRadius: 4 }}
            >
              <option value="anda_checklist">ANDA checklist</option>
              <option value="dmf_checklist">DMF checklist</option>
              <option value="validation_checklist">Validation checklist</option>
              <option value="general_checklist">General checklist</option>
            </select>
          </label>
          <label style={{ display: "block", marginBottom: "0.5rem", fontWeight: 500, fontSize: 13 }}>
            Source path / reference
            <input
              value={sourcePath}
              onChange={(e) => setSourcePath(e.target.value)}
              required
              placeholder="synthetic://anda-export.json"
              style={{ display: "block", width: "100%", marginTop: 4, padding: "6px 8px", border: "1px solid #dce7f4", borderRadius: 4, boxSizing: "border-box" }}
            />
          </label>
          <label style={{ display: "block", marginBottom: "1rem", fontWeight: 500, fontSize: 13 }}>
            Payload (JSON, used for the checksum)
            <textarea
              value={payloadJson}
              onChange={(e) => setPayloadJson(e.target.value)}
              rows={4}
              style={{ display: "block", width: "100%", marginTop: 4, padding: "6px 8px", border: "1px solid #dce7f4", borderRadius: 4, boxSizing: "border-box", fontFamily: "monospace", fontSize: 12 }}
            />
          </label>
          {formError && <p role="alert" style={{ color: "#c0392b", fontSize: 13, marginBottom: 8 }}>{formError}</p>}
          <button
            type="submit"
            disabled={submitting}
            style={{ padding: "8px 18px", borderRadius: 6, border: "none", background: submitting ? "#35b1f6" : "#045e8f", color: "#fff", fontWeight: 600, cursor: submitting ? "not-allowed" : "pointer" }}
          >
            {submitting ? "Registering…" : "Register"}
          </button>
        </form>
      )}

      {loading && <p>Loading…</p>}
      {error && <p role="alert" style={{ color: "#c0392b" }}>{error}</p>}
      {!loading && items.length === 0 && <p style={{ color: "#66768b" }}>No source packages registered yet.</p>}

      {items.length > 0 && (
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 14 }}>
          <thead>
            <tr style={{ borderBottom: "2px solid #dce7f4", textAlign: "left" }}>
              <th style={{ padding: "8px 12px" }}>Name</th>
              <th style={{ padding: "8px 12px" }}>Type</th>
              <th style={{ padding: "8px 12px" }}>Checksum</th>
              <th style={{ padding: "8px 12px" }}>Approval</th>
              <th style={{ padding: "8px 12px" }}>Registered</th>
            </tr>
          </thead>
          <tbody>
            {items.map((pkg) => (
              <tr key={pkg.public_id} style={{ borderBottom: "1px solid #f4f8fe" }}>
                <td style={{ padding: "10px 12px" }}>{pkg.source_name}</td>
                <td style={{ padding: "10px 12px", color: "#66768b" }}>{pkg.source_type}</td>
                <td style={{ padding: "10px 12px", fontFamily: "monospace", fontSize: 12, color: "#66768b" }}>
                  {pkg.source_checksum.slice(0, 12)}…
                </td>
                <td style={{ padding: "10px 12px" }}>
                  <ApprovalBadge state={pkg.approval_state} />
                </td>
                <td style={{ padding: "10px 12px", color: "#66768b", fontSize: 12 }}>
                  {new Date(pkg.imported_at).toLocaleDateString()}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </main>
  );
}

export default function TemplateSourcesPage() {
  return (
    <Suspense>
      <TemplateSourcesPageInner />
    </Suspense>
  );
}
