"use client";

import { Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import { formulations, type ProductDevelopmentRecord, isSignedOut, loadError } from "@/lib/api";

function FormulationsPageInner() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const tenantSlug = searchParams.get("tenant") ?? "";

  const [items, setItems] = useState<ProductDevelopmentRecord[]>([]);
  // QA-13: show "New product record" only when the server says this user may
  // create one here (the POST still checks). Unknown until loaded: hidden.
  const [canCreate, setCanCreate] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  function load() {
    if (!tenantSlug) return;
    setLoading(true);
    formulations.products
      .list(tenantSlug)
      .then((resp) => {
        setItems(resp.results);
        setCanCreate(resp.can_create !== false);
      })
      .catch((err: unknown) => {
        if (isSignedOut(err)) {
          router.push(`/signin?next=${encodeURIComponent(window.location.pathname + window.location.search)}`);
        } else {
          setError(loadError(err, "Failed to load products."));
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
        {canCreate && (
        <Link
          href={`/formulations/new?tenant=${tenantSlug}`}
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
          New product record
        </Link>
        )}
      </div>

      {loading && <p>Loading…</p>}
      {error && (
        <p role="alert" style={{ color: "#c0392b" }}>
          {error}
        </p>
      )}
      {!loading && items.length === 0 && !error && (
        <p style={{ color: "#66768b" }}>No product records yet.</p>
      )}

      {items.length > 0 && (
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 14 }}>
          <thead>
            <tr style={{ borderBottom: "2px solid #dce7f4", textAlign: "left" }}>
              <th style={{ padding: "8px 12px" }} scope="col">
                Product code
              </th>
              <th style={{ padding: "8px 12px" }} scope="col">
                Name
              </th>
              <th style={{ padding: "8px 12px" }} scope="col">
                Active ingredient
              </th>
              <th style={{ padding: "8px 12px" }} scope="col">
                Reference product
              </th>
              <th style={{ padding: "8px 12px" }} scope="col">
                Status
              </th>
            </tr>
          </thead>
          <tbody>
            {items.map((p) => (
              <tr key={p.public_id} style={{ borderBottom: "1px solid #f4f8fe" }}>
                <td style={{ padding: "10px 12px", fontFamily: "monospace", fontSize: 13 }}>
                  <Link href={`/formulations/${p.public_id}?tenant=${tenantSlug}`} style={{ color: "#045e8f", textDecoration: "none" }}>
                    {p.product_code}
                  </Link>
                </td>
                <td style={{ padding: "10px 12px" }}>{p.proposed_product_name}</td>
                <td style={{ padding: "10px 12px", color: "#66768b" }}>{p.active_ingredient}</td>
                <td style={{ padding: "10px 12px", color: "#66768b", fontSize: 12 }}>
                  {p.selected_ob_product_public_id ? "Selected" : "Not yet selected"}
                </td>
                <td style={{ padding: "10px 12px", color: "#66768b", fontSize: 12 }}>{p.status}</td>
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
