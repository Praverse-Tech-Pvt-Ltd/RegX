"use client";

import { Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import { fdaData, type OrangeBookProduct, ApiError } from "@/lib/api";
import { ProvenanceLabel } from "@/components/ProvenanceLabel";

function OrangeBookSearchInner() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const tenantSlug = searchParams.get("tenant") ?? "";

  const [ingredient, setIngredient] = useState("");
  const [route, setRoute] = useState("");
  const [dosageForm, setDosageForm] = useState("");
  const [results, setResults] = useState<OrangeBookProduct[]>([]);
  const [searched, setSearched] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSearch(e: React.FormEvent) {
    e.preventDefault();
    if (!tenantSlug) return;
    setLoading(true);
    setError(null);
    try {
      const resp = await fdaData.orangeBook.search(tenantSlug, {
        active_ingredient: ingredient || undefined,
        route: route || undefined,
        dosage_form: dosageForm || undefined,
      });
      setResults(resp.results);
      setSearched(true);
    } catch (err) {
      if (err instanceof ApiError && (err.status === 403 || err.status === 401)) {
        router.push("/signin");
      } else {
        setError("Search failed.");
      }
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    if (!tenantSlug) router.push("/tenants");
  }, [tenantSlug]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!tenantSlug) return null;

  return (
    <main style={{ maxWidth: 960, margin: "2rem auto", padding: "0 1rem" }}>
      <div style={{ marginBottom: "0.5rem" }}>
        <Link href={`/fda-data/releases?tenant=${tenantSlug}`} style={{ color: "#1d4ed8", fontSize: 13, textDecoration: "none" }}>
          ← FDA releases
        </Link>
      </div>
      <h1 style={{ margin: "0 0 1rem" }}>Orange Book Product Search</h1>
      <p style={{ fontSize: 13, color: "#6b7280", marginTop: -8, marginBottom: "1rem" }}>
        Results shown here are FDA-sourced reference records only. Selecting one as your
        reference product is always a separate, explicit step on your product record — no
        product is ever auto-selected as an RLD or reference standard.
      </p>

      <form onSubmit={handleSearch} style={{ display: "flex", gap: 8, marginBottom: "1.5rem", flexWrap: "wrap" }}>
        <input
          value={ingredient}
          onChange={(e) => setIngredient(e.target.value)}
          placeholder="Active ingredient"
          style={{ padding: "6px 10px", border: "1px solid #d1d5db", borderRadius: 4, flex: 1, minWidth: 160 }}
        />
        <input
          value={route}
          onChange={(e) => setRoute(e.target.value)}
          placeholder="Route code (e.g. oral)"
          style={{ padding: "6px 10px", border: "1px solid #d1d5db", borderRadius: 4, width: 160 }}
        />
        <input
          value={dosageForm}
          onChange={(e) => setDosageForm(e.target.value)}
          placeholder="Dosage form code (e.g. tablet)"
          style={{ padding: "6px 10px", border: "1px solid #d1d5db", borderRadius: 4, width: 200 }}
        />
        <button
          type="submit"
          disabled={loading}
          style={{ background: "#1d4ed8", color: "#fff", border: "none", borderRadius: 6, padding: "8px 18px", cursor: loading ? "not-allowed" : "pointer", fontWeight: 600 }}
        >
          {loading ? "Searching…" : "Search"}
        </button>
      </form>

      {error && (
        <p role="alert" style={{ color: "#b91c1c" }}>
          {error}
        </p>
      )}
      {searched && results.length === 0 && !error && (
        <p style={{ color: "#6b7280" }}>No matching Orange Book products found.</p>
      )}

      {results.length > 0 && (
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 14 }}>
          <thead>
            <tr style={{ borderBottom: "2px solid #e5e7eb", textAlign: "left" }}>
              <th style={{ padding: "8px 12px" }}>
                Trade name <ProvenanceLabel kind="FDA_SOURCE" />
              </th>
              <th style={{ padding: "8px 12px" }}>Application</th>
              <th style={{ padding: "8px 12px" }}>Strength</th>
              <th style={{ padding: "8px 12px" }}>Route / dosage form</th>
              <th style={{ padding: "8px 12px" }}>RLD / RS</th>
            </tr>
          </thead>
          <tbody>
            {results.map((p) => (
              <tr key={p.public_id} style={{ borderBottom: "1px solid #f3f4f6" }}>
                <td style={{ padding: "10px 12px" }}>{p.trade_name || "—"}</td>
                <td style={{ padding: "10px 12px", color: "#6b7280", fontSize: 12 }}>
                  {p.application_number}-{p.product_number}
                </td>
                <td style={{ padding: "10px 12px" }}>{p.strength_raw}</td>
                <td style={{ padding: "10px 12px", color: "#6b7280", fontSize: 12 }}>
                  {p.route_normalized ?? p.route_raw} / {p.dosage_form_normalized ?? p.dosage_form_raw}
                </td>
                <td style={{ padding: "10px 12px", fontSize: 12 }}>
                  {p.rld_flag ? "RLD" : ""} {p.reference_standard_flag ? "RS" : ""}
                  {!p.rld_flag && !p.reference_standard_flag && "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </main>
  );
}

export default function OrangeBookSearchPage() {
  return (
    <Suspense>
      <OrangeBookSearchInner />
    </Suspense>
  );
}
