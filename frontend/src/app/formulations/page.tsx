"use client";

import { Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import { formulations, type ProductDevelopmentRecord, ApiError } from "@/lib/api";

function FormulationsPageInner() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const tenantSlug = searchParams.get("tenant") ?? "";

  const [items, setItems] = useState<ProductDevelopmentRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [showForm, setShowForm] = useState(false);
  const [productCode, setProductCode] = useState("");
  const [productName, setProductName] = useState("");
  const [activeIngredient, setActiveIngredient] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  function load() {
    if (!tenantSlug) return;
    setLoading(true);
    formulations.products
      .list(tenantSlug)
      .then((resp) => setItems(resp.results))
      .catch((err: unknown) => {
        if (err instanceof ApiError && (err.status === 403 || err.status === 401)) {
          router.push("/signin");
        } else {
          setError("Failed to load products.");
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

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    setFormError(null);
    try {
      const product = await formulations.products.create(tenantSlug, {
        product_code: productCode,
        proposed_product_name: productName,
        active_ingredient: activeIngredient,
      });
      router.push(`/formulations/${product.public_id}?tenant=${tenantSlug}`);
    } catch (err) {
      setFormError(err instanceof ApiError ? err.message : "Could not create product record.");
    } finally {
      setSubmitting(false);
    }
  }

  if (!tenantSlug) return null;

  return (
    <main style={{ maxWidth: 900, margin: "2rem auto", padding: "0 1rem" }}>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          marginBottom: "1.5rem",
        }}
      >
        <h1 style={{ margin: 0 }}>Product Development Records</h1>
        <button
          onClick={() => setShowForm((s) => !s)}
          style={{ background: "#1d4ed8", color: "#fff", border: "none", borderRadius: 6, padding: "8px 18px", cursor: "pointer", fontWeight: 600 }}
        >
          {showForm ? "Cancel" : "New product record"}
        </button>
      </div>

      {showForm && (
        <form onSubmit={handleCreate} style={{ border: "1px solid #e5e7eb", borderRadius: 8, padding: "1rem", marginBottom: "1.5rem" }}>
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
          <label style={{ display: "block", marginBottom: "1rem", fontWeight: 500, fontSize: 13 }}>
            Active ingredient
            <input
              value={activeIngredient}
              onChange={(e) => setActiveIngredient(e.target.value)}
              required
              style={{ display: "block", width: "100%", marginTop: 4, padding: "6px 8px", border: "1px solid #d1d5db", borderRadius: 4, boxSizing: "border-box" }}
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
            {submitting ? "Creating…" : "Create"}
          </button>
        </form>
      )}

      {loading && <p>Loading…</p>}
      {error && (
        <p role="alert" style={{ color: "#b91c1c" }}>
          {error}
        </p>
      )}
      {!loading && items.length === 0 && <p style={{ color: "#6b7280" }}>No product records yet.</p>}

      {items.length > 0 && (
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 14 }}>
          <thead>
            <tr style={{ borderBottom: "2px solid #e5e7eb", textAlign: "left" }}>
              <th style={{ padding: "8px 12px" }}>Product code</th>
              <th style={{ padding: "8px 12px" }}>Name</th>
              <th style={{ padding: "8px 12px" }}>Active ingredient</th>
              <th style={{ padding: "8px 12px" }}>Reference product</th>
              <th style={{ padding: "8px 12px" }}>Status</th>
            </tr>
          </thead>
          <tbody>
            {items.map((p) => (
              <tr key={p.public_id} style={{ borderBottom: "1px solid #f3f4f6" }}>
                <td style={{ padding: "10px 12px", fontFamily: "monospace", fontSize: 13 }}>
                  <Link href={`/formulations/${p.public_id}?tenant=${tenantSlug}`} style={{ color: "#1d4ed8", textDecoration: "none" }}>
                    {p.product_code}
                  </Link>
                </td>
                <td style={{ padding: "10px 12px" }}>{p.proposed_product_name}</td>
                <td style={{ padding: "10px 12px", color: "#6b7280" }}>{p.active_ingredient}</td>
                <td style={{ padding: "10px 12px", color: "#6b7280", fontSize: 12 }}>
                  {p.selected_ob_product_public_id ? "Selected" : "Not yet selected"}
                </td>
                <td style={{ padding: "10px 12px", color: "#6b7280", fontSize: 12 }}>{p.status}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </main>
  );
}

export default function FormulationsPage() {
  return (
    <Suspense>
      <FormulationsPageInner />
    </Suspense>
  );
}
