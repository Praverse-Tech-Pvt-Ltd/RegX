"use client";

import { Suspense, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import { formulations, ApiError } from "@/lib/api";

function NewProductPageInner() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const tenantSlug = searchParams.get("tenant") ?? "";

  const [productCode, setProductCode] = useState("");
  const [productName, setProductName] = useState("");
  const [activeIngredient, setActiveIngredient] = useState("");
  const [route, setRoute] = useState("");
  const [dosageForm, setDosageForm] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    setFormError(null);
    try {
      const product = await formulations.products.create(tenantSlug, {
        product_code: productCode,
        proposed_product_name: productName,
        active_ingredient: activeIngredient,
        route: route || undefined,
        dosage_form: dosageForm || undefined,
      });
      router.push(`/formulations/${product.public_id}?tenant=${tenantSlug}`);
    } catch (err) {
      if (err instanceof ApiError && (err.status === 403 || err.status === 401)) {
        router.push("/signin");
        return;
      }
      setFormError(err instanceof ApiError ? err.message : "Could not create product record.");
    } finally {
      setSubmitting(false);
    }
  }

  if (!tenantSlug) {
    return (
      <main style={{ maxWidth: 700, margin: "2rem auto", padding: "0 1rem" }}>
        <p role="alert" style={{ color: "#b91c1c" }}>
          Select a tenant first.
        </p>
      </main>
    );
  }

  return (
    <main style={{ maxWidth: 700, margin: "2rem auto", padding: "0 1rem" }}>
      <div style={{ marginBottom: "0.5rem" }}>
        <Link href={`/formulations?tenant=${tenantSlug}`} style={{ color: "#1d4ed8", fontSize: 13, textDecoration: "none" }}>
          ← Product records
        </Link>
      </div>
      <h1 style={{ margin: "0 0 1rem" }}>New Product Development Record</h1>

      <form onSubmit={handleCreate}>
        <label style={{ display: "block", marginBottom: "0.5rem", fontWeight: 500, fontSize: 13 }}>
          Product code
          <input
            value={productCode}
            onChange={(e) => setProductCode(e.target.value)}
            required
            style={{ display: "block", width: "100%", marginTop: 4, padding: "6px 8px", border: "1px solid #d1d5db", borderRadius: 4, boxSizing: "border-box" }}
          />
        </label>
        <label style={{ display: "block", marginBottom: "0.5rem", fontWeight: 500, fontSize: 13 }}>
          Proposed product name
          <input
            value={productName}
            onChange={(e) => setProductName(e.target.value)}
            required
            style={{ display: "block", width: "100%", marginTop: 4, padding: "6px 8px", border: "1px solid #d1d5db", borderRadius: 4, boxSizing: "border-box" }}
          />
        </label>
        <label style={{ display: "block", marginBottom: "0.5rem", fontWeight: 500, fontSize: 13 }}>
          Active ingredient
          <input
            value={activeIngredient}
            onChange={(e) => setActiveIngredient(e.target.value)}
            required
            style={{ display: "block", width: "100%", marginTop: 4, padding: "6px 8px", border: "1px solid #d1d5db", borderRadius: 4, boxSizing: "border-box" }}
          />
        </label>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8, marginBottom: "1rem" }}>
          <label style={{ fontWeight: 500, fontSize: 13 }}>
            Intended route (optional)
            <input
              value={route}
              onChange={(e) => setRoute(e.target.value)}
              style={{ display: "block", width: "100%", marginTop: 4, padding: "6px 8px", border: "1px solid #d1d5db", borderRadius: 4, boxSizing: "border-box" }}
            />
          </label>
          <label style={{ fontWeight: 500, fontSize: 13 }}>
            Intended dosage form (optional)
            <input
              value={dosageForm}
              onChange={(e) => setDosageForm(e.target.value)}
              style={{ display: "block", width: "100%", marginTop: 4, padding: "6px 8px", border: "1px solid #d1d5db", borderRadius: 4, boxSizing: "border-box" }}
            />
          </label>
        </div>
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
          {submitting ? "Creating…" : "Create"}
        </button>
      </form>
    </main>
  );
}

export default function NewProductPage() {
  return (
    <Suspense>
      <NewProductPageInner />
    </Suspense>
  );
}
