"use client";

import { Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams, useParams } from "next/navigation";
import Link from "next/link";
import {
  formulations,
  type ProductDevelopmentRecord,
  type FormulationVersion,
  ApiError,
} from "@/lib/api";
import { ProvenanceLabel } from "@/components/ProvenanceLabel";

function FormulationDetailInner() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const params = useParams<{ publicId: string }>();
  const tenantSlug = searchParams.get("tenant") ?? "";
  const publicId = params.publicId;

  const [product, setProduct] = useState<ProductDevelopmentRecord | null>(null);
  const [versions, setVersions] = useState<FormulationVersion[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Reference-product selection -- requires explicit confirmation, never
  // pre-filled or auto-picked.
  const [showSelectForm, setShowSelectForm] = useState(false);
  const [selApplicationNumber, setSelApplicationNumber] = useState("");
  const [selProductNumber, setSelProductNumber] = useState("");
  const [selProductPublicId, setSelProductPublicId] = useState("");
  const [selReleasePublicId, setSelReleasePublicId] = useState("");
  const [selJustification, setSelJustification] = useState("");
  const [selConfirmed, setSelConfirmed] = useState(false);
  const [selSubmitting, setSelSubmitting] = useState(false);
  const [selError, setSelError] = useState<string | null>(null);

  // Formulation version creation
  const [showVersionForm, setShowVersionForm] = useState(false);
  const [totalWeight, setTotalWeight] = useState("");
  const [totalWeightUnit, setTotalWeightUnit] = useState("milligram");
  const [maxUnitsPerDay, setMaxUnitsPerDay] = useState("");
  const [versionSubmitting, setVersionSubmitting] = useState(false);
  const [versionError, setVersionError] = useState<string | null>(null);

  function load() {
    if (!tenantSlug) return;
    setLoading(true);
    Promise.all([
      formulations.products.get(tenantSlug, publicId),
      formulations.versions.list(tenantSlug, publicId),
    ])
      .then(([p, v]) => {
        setProduct(p);
        setVersions(v.results);
      })
      .catch((err: unknown) => {
        if (err instanceof ApiError && err.status === 404) setError("Product not found.");
        else if (err instanceof ApiError && (err.status === 403 || err.status === 401))
          router.push(`/signin?next=${encodeURIComponent(window.location.pathname + window.location.search)}`);
        else setError("Failed to load product.");
      })
      .finally(() => setLoading(false));
  }

  useEffect(() => {
    if (!tenantSlug) {
      router.push("/tenants");
      return;
    }
    load();
  }, [tenantSlug, publicId]); // eslint-disable-line react-hooks/exhaustive-deps

  async function handleSelectReference(e: React.FormEvent) {
    e.preventDefault();
    if (!selConfirmed) {
      setSelError("You must explicitly confirm this is the correct reference product.");
      return;
    }
    setSelSubmitting(true);
    setSelError(null);
    try {
      const updated = await formulations.products.selectReference(tenantSlug, publicId, {
        application_number: selApplicationNumber,
        product_number: selProductNumber,
        product_public_id: selProductPublicId,
        release_public_id: selReleasePublicId,
        justification: selJustification,
      });
      setProduct(updated);
      setShowSelectForm(false);
      setSelConfirmed(false);
    } catch (err) {
      setSelError(err instanceof ApiError ? err.message : "Selection failed.");
    } finally {
      setSelSubmitting(false);
    }
  }

  async function handleCreateVersion(e: React.FormEvent) {
    e.preventDefault();
    setVersionSubmitting(true);
    setVersionError(null);
    try {
      const v = await formulations.versions.create(tenantSlug, publicId, {
        total_dosage_unit_weight: totalWeight,
        total_dosage_unit_weight_unit: totalWeightUnit,
        maximum_dosage_units_per_day: maxUnitsPerDay || undefined,
      });
      router.push(`/formulations/${publicId}/versions/${v.public_id}?tenant=${tenantSlug}`);
    } catch (err) {
      setVersionError(err instanceof ApiError ? err.message : "Could not create formulation version.");
    } finally {
      setVersionSubmitting(false);
    }
  }

  if (!tenantSlug) return null;
  if (loading) return <main style={{ maxWidth: 900, margin: "2rem auto" }}>Loading…</main>;
  if (error || !product) {
    return (
      <main style={{ maxWidth: 900, margin: "2rem auto", padding: "0 1rem" }}>
        <p role="alert" style={{ color: "#b91c1c" }}>
          {error ?? "Product not found."}
        </p>
      </main>
    );
  }

  return (
    <main style={{ maxWidth: 900, margin: "2rem auto", padding: "0 1rem" }}>
      <div style={{ marginBottom: "0.5rem" }}>
        <Link href={`/formulations?tenant=${tenantSlug}`} style={{ color: "#1d4ed8", fontSize: 13, textDecoration: "none" }}>
          ← Product records
        </Link>
      </div>
      <h1 style={{ margin: "0 0 0.25rem" }}>{product.proposed_product_name}</h1>
      <p style={{ color: "#6b7280", fontSize: 13, marginTop: 0 }}>
        {product.product_code} · {product.active_ingredient} <ProvenanceLabel kind="USER_INPUT" />
      </p>

      {/* Reference product selection */}
      <section style={{ marginTop: "1.5rem", border: "1px solid #e5e7eb", borderRadius: 8, padding: "1rem" }}>
        <h2 style={{ fontSize: 16, margin: "0 0 0.5rem" }}>Reference product</h2>
        {product.selected_ob_product_public_id ? (
          <div style={{ fontSize: 14 }}>
            <p style={{ margin: "0 0 4px" }}>
              Application {product.selected_ob_application_number}-{product.selected_ob_product_number}{" "}
              <ProvenanceLabel kind="FDA_SOURCE" />
            </p>
            <p style={{ margin: "0 0 4px", color: "#6b7280", fontSize: 13 }}>
              Selected by {product.selecting_user_email ?? "—"} <ProvenanceLabel kind="REVIEWER_CONFIRMED" />
            </p>
            {product.selection_justification && (
              <p style={{ margin: 0, color: "#6b7280", fontSize: 13 }}>
                Justification: {product.selection_justification}
              </p>
            )}
          </div>
        ) : (
          <p style={{ color: "#6b7280", fontSize: 13 }}>
            No reference product selected. A reference must be explicitly chosen and confirmed
            -- the system never auto-selects an RLD or reference standard.
          </p>
        )}
        <button
          onClick={() => setShowSelectForm((s) => !s)}
          style={{ marginTop: 8, background: "#1d4ed8", color: "#fff", border: "none", borderRadius: 6, padding: "6px 14px", cursor: "pointer", fontWeight: 600, fontSize: 13 }}
        >
          {showSelectForm ? "Cancel" : product.selected_ob_product_public_id ? "Change reference" : "Select reference product"}
        </button>

        {showSelectForm && (
          <form onSubmit={handleSelectReference} style={{ marginTop: 12 }}>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8, marginBottom: 8 }}>
              <label style={{ fontSize: 13 }}>
                Application number
                <input value={selApplicationNumber} onChange={(e) => setSelApplicationNumber(e.target.value)} required style={inputStyle} />
              </label>
              <label style={{ fontSize: 13 }}>
                Product number
                <input value={selProductNumber} onChange={(e) => setSelProductNumber(e.target.value)} required style={inputStyle} />
              </label>
              <label style={{ fontSize: 13 }}>
                Orange Book product ID
                <input value={selProductPublicId} onChange={(e) => setSelProductPublicId(e.target.value)} required style={inputStyle} />
              </label>
              <label style={{ fontSize: 13 }}>
                FDA release ID
                <input value={selReleasePublicId} onChange={(e) => setSelReleasePublicId(e.target.value)} required style={inputStyle} />
              </label>
            </div>
            <label style={{ display: "block", fontSize: 13, marginBottom: 8 }}>
              Justification
              <textarea value={selJustification} onChange={(e) => setSelJustification(e.target.value)} rows={2} style={inputStyle} />
            </label>
            <label style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 13, marginBottom: 8 }}>
              <input type="checkbox" checked={selConfirmed} onChange={(e) => setSelConfirmed(e.target.checked)} />
              I confirm this is the correct reference product for this formulation.
            </label>
            {selError && (
              <p role="alert" style={{ color: "#b91c1c", fontSize: 13, marginBottom: 8 }}>
                {selError}
              </p>
            )}
            <button type="submit" disabled={selSubmitting} style={smallButtonStyle}>
              {selSubmitting ? "Confirming…" : "Confirm selection"}
            </button>
          </form>
        )}
      </section>

      {/* Formulation versions */}
      <section style={{ marginTop: "1.5rem", border: "1px solid #e5e7eb", borderRadius: 8, padding: "1rem" }}>
        <h2 style={{ fontSize: 16, margin: "0 0 0.5rem" }}>Formulation versions</h2>
        {versions.length > 0 ? (
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13, marginBottom: 12 }}>
            <thead>
              <tr style={{ borderBottom: "1px solid #e5e7eb", textAlign: "left" }}>
                <th style={{ padding: "6px 8px" }} scope="col">
                  Version
                </th>
                <th style={{ padding: "6px 8px" }} scope="col">
                  Total dosage-unit weight <ProvenanceLabel kind="USER_INPUT" />
                </th>
                <th style={{ padding: "6px 8px" }} scope="col">
                  Status
                </th>
              </tr>
            </thead>
            <tbody>
              {versions.map((v) => (
                <tr key={v.public_id} style={{ borderBottom: "1px solid #f3f4f6" }}>
                  <td style={{ padding: "6px 8px" }}>
                    <Link
                      href={`/formulations/${publicId}/versions/${v.public_id}?tenant=${tenantSlug}`}
                      style={{ color: "#1d4ed8", textDecoration: "none" }}
                    >
                      v{v.version_number}
                    </Link>
                  </td>
                  <td style={{ padding: "6px 8px" }}>
                    {v.total_dosage_unit_weight} {v.total_dosage_unit_weight_unit}
                  </td>
                  <td style={{ padding: "6px 8px", color: "#6b7280" }}>{v.status}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <p style={{ color: "#6b7280", fontSize: 13 }}>No formulation version created yet.</p>
        )}
        <button onClick={() => setShowVersionForm((s) => !s)} style={smallButtonStyle}>
          {showVersionForm ? "Cancel" : "Create formulation version"}
        </button>
        {showVersionForm && (
          <form onSubmit={handleCreateVersion} style={{ marginTop: 12 }}>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8, marginBottom: 8 }}>
              <label style={{ fontSize: 13 }}>
                Total dosage-unit weight
                <input value={totalWeight} onChange={(e) => setTotalWeight(e.target.value)} required style={inputStyle} />
              </label>
              <label style={{ fontSize: 13 }}>
                Unit
                <input value={totalWeightUnit} onChange={(e) => setTotalWeightUnit(e.target.value)} required style={inputStyle} />
              </label>
              <label style={{ fontSize: 13 }}>
                Maximum dosage units/day
                <input value={maxUnitsPerDay} onChange={(e) => setMaxUnitsPerDay(e.target.value)} style={inputStyle} />
              </label>
            </div>
            {versionError && (
              <p role="alert" style={{ color: "#b91c1c", fontSize: 13, marginBottom: 8 }}>
                {versionError}
              </p>
            )}
            <button type="submit" disabled={versionSubmitting} style={smallButtonStyle}>
              {versionSubmitting ? "Creating…" : "Create version"}
            </button>
          </form>
        )}
      </section>
    </main>
  );
}

const inputStyle: React.CSSProperties = {
  display: "block",
  width: "100%",
  marginTop: 4,
  padding: "6px 8px",
  border: "1px solid #d1d5db",
  borderRadius: 4,
  boxSizing: "border-box",
};

const smallButtonStyle: React.CSSProperties = {
  background: "#1d4ed8",
  color: "#fff",
  border: "none",
  borderRadius: 6,
  padding: "6px 14px",
  cursor: "pointer",
  fontWeight: 600,
  fontSize: 13,
};

export default function FormulationDetailPage() {
  return (
    <Suspense>
      <FormulationDetailInner />
    </Suspense>
  );
}
