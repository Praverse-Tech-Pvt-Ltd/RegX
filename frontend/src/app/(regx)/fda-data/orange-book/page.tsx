"use client";

import { Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import { fdaData, type OrangeBookProduct, isSignedOut, loadError } from "@/lib/api";
import { ProvenanceLabel } from "@/components/ProvenanceLabel";

function OrangeBookSearchInner() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const tenantSlug = searchParams.get("tenant") ?? "";

  const [ingredient, setIngredient] = useState("");
  const [tradeName, setTradeName] = useState("");
  const [applicationNumber, setApplicationNumber] = useState("");
  const [route, setRoute] = useState("");
  const [dosageForm, setDosageForm] = useState("");
  const [strength, setStrength] = useState("");
  const [applicationType, setApplicationType] = useState("");
  const [rldOnly, setRldOnly] = useState(false);
  const [referenceStandardOnly, setReferenceStandardOnly] = useState(false);
  const [discontinuedFilter, setDiscontinuedFilter] = useState<"" | "true" | "false">("");

  const [results, setResults] = useState<OrangeBookProduct[]>([]);
  const [page, setPage] = useState(1);
  const [hasNext, setHasNext] = useState(false);
  const [searched, setSearched] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function runSearch(targetPage: number) {
    if (!tenantSlug) return;
    setLoading(true);
    setError(null);
    try {
      const resp = await fdaData.orangeBook.search(tenantSlug, {
        active_ingredient: ingredient || undefined,
        trade_name: tradeName.trim() || undefined,
        application_number: applicationNumber.trim() || undefined,
        route: route || undefined,
        dosage_form: dosageForm || undefined,
        strength: strength || undefined,
        application_type: applicationType || undefined,
        rld: rldOnly ? true : undefined,
        reference_standard: referenceStandardOnly ? true : undefined,
        discontinued: discontinuedFilter ? discontinuedFilter === "true" : undefined,
        page: targetPage,
      });
      setResults(resp.results);
      setHasNext(resp.next !== null);
      setPage(targetPage);
      setSearched(true);
    } catch (err) {
      if (isSignedOut(err)) {
        router.push(`/signin?next=${encodeURIComponent(window.location.pathname + window.location.search)}`);
      } else {
        setError(loadError(err, "Search failed."));
      }
    } finally {
      setLoading(false);
    }
  }

  async function handleSearch(e: React.FormEvent) {
    e.preventDefault();
    await runSearch(1);
  }

  useEffect(() => {
    if (!tenantSlug) router.push("/tenants");
  }, [tenantSlug]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!tenantSlug) return null;

  return (
    <main style={{ maxWidth: 1000, margin: "2rem auto", padding: "0 1rem" }}>
      <div style={{ marginBottom: "0.5rem" }}>
        <Link href={`/fda-data/releases?tenant=${tenantSlug}`} style={{ color: "#045e8f", fontSize: 13, textDecoration: "none" }}>
          ← FDA releases
        </Link>
      </div>
      <h1 style={{ margin: "0 0 1rem" }}>Orange Book Product Search</h1>
      <p style={{ fontSize: 13, color: "#66768b", marginTop: -8, marginBottom: "1rem" }}>
        Results shown here are FDA-sourced reference records only. Selecting one as your
        reference product is always a separate, explicit step on your product record — no
        product is ever auto-selected as an RLD or reference standard, even when it is the
        only candidate returned.
      </p>

      <form onSubmit={handleSearch} style={{ display: "flex", gap: 8, marginBottom: "0.75rem", flexWrap: "wrap" }}>
        <input
          value={tradeName}
          onChange={(e) => setTradeName(e.target.value)}
          placeholder="Trade name (e.g. AMZEEQ)"
          aria-label="Trade name"
          style={{ padding: "6px 10px", border: "1px solid #dce7f4", borderRadius: 4, width: 170 }}
        />
        <input
          value={applicationNumber}
          onChange={(e) => setApplicationNumber(e.target.value)}
          placeholder="Application number (e.g. N212379)"
          aria-label="Application number"
          style={{ padding: "6px 10px", border: "1px solid #dce7f4", borderRadius: 4, width: 220 }}
        />
        <input
          value={ingredient}
          onChange={(e) => setIngredient(e.target.value)}
          placeholder="Active ingredient"
          style={{ padding: "6px 10px", border: "1px solid #dce7f4", borderRadius: 4, flex: 1, minWidth: 160 }}
        />
        <input
          value={route}
          onChange={(e) => setRoute(e.target.value)}
          placeholder="Route code (e.g. oral)"
          style={{ padding: "6px 10px", border: "1px solid #dce7f4", borderRadius: 4, width: 150 }}
        />
        <input
          value={dosageForm}
          onChange={(e) => setDosageForm(e.target.value)}
          placeholder="Dosage form code (e.g. tablet)"
          style={{ padding: "6px 10px", border: "1px solid #dce7f4", borderRadius: 4, width: 180 }}
        />
        <input
          value={strength}
          onChange={(e) => setStrength(e.target.value)}
          placeholder="Strength (e.g. 500MG)"
          style={{ padding: "6px 10px", border: "1px solid #dce7f4", borderRadius: 4, width: 140 }}
        />
        <input
          value={applicationType}
          onChange={(e) => setApplicationType(e.target.value)}
          placeholder="Application type (e.g. A)"
          style={{ padding: "6px 10px", border: "1px solid #dce7f4", borderRadius: 4, width: 160 }}
        />
        <button
          type="submit"
          disabled={loading}
          style={{ background: "#045e8f", color: "#fff", border: "none", borderRadius: 6, padding: "8px 18px", cursor: loading ? "not-allowed" : "pointer", fontWeight: 600 }}
        >
          {loading ? "Searching…" : "Search"}
        </button>
      </form>

      <div style={{ display: "flex", gap: 16, marginBottom: "1.5rem", fontSize: 13, alignItems: "center" }}>
        <label style={{ display: "flex", alignItems: "center", gap: 4 }}>
          <input type="checkbox" checked={rldOnly} onChange={(e) => setRldOnly(e.target.checked)} />
          RLD only
        </label>
        <label style={{ display: "flex", alignItems: "center", gap: 4 }}>
          <input
            type="checkbox"
            checked={referenceStandardOnly}
            onChange={(e) => setReferenceStandardOnly(e.target.checked)}
          />
          Reference standard only
        </label>
        <label style={{ display: "flex", alignItems: "center", gap: 4 }}>
          Discontinued:{" "}
          <select
            value={discontinuedFilter}
            onChange={(e) => setDiscontinuedFilter(e.target.value as "" | "true" | "false")}
            style={{ padding: "4px 8px", borderRadius: 4, border: "1px solid #dce7f4" }}
          >
            <option value="">Any</option>
            <option value="false">Active only</option>
            <option value="true">Discontinued only</option>
          </select>
        </label>
      </div>

      {error && (
        <p role="alert" style={{ color: "#c0392b" }}>
          {error}
        </p>
      )}
      {searched && results.length === 0 && !error && (
        <p style={{ color: "#66768b" }}>No matching Orange Book products found.</p>
      )}

      {results.length > 0 && (
        <>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 14 }}>
            <thead>
              <tr style={{ borderBottom: "2px solid #dce7f4", textAlign: "left" }}>
                <th style={{ padding: "8px 12px" }} scope="col">
                  Trade name <ProvenanceLabel kind="FDA_SOURCE" />
                </th>
                <th style={{ padding: "8px 12px" }} scope="col">
                  Application
                </th>
                <th style={{ padding: "8px 12px" }} scope="col">
                  Strength
                </th>
                <th style={{ padding: "8px 12px" }} scope="col">
                  Route / dosage form
                </th>
                <th style={{ padding: "8px 12px" }} scope="col">
                  RLD / RS
                </th>
                <th style={{ padding: "8px 12px" }} scope="col">
                  Discontinued
                </th>
              </tr>
            </thead>
            <tbody>
              {results.map((p) => (
                <tr key={p.public_id} style={{ borderBottom: "1px solid #f4f8fe" }}>
                  <td style={{ padding: "10px 12px" }}>
                    <Link
                      href={`/fda-data/orange-book/${p.public_id}?tenant=${tenantSlug}`}
                      style={{ color: "#045e8f", textDecoration: "none" }}
                    >
                      {p.trade_name || "(untitled)"}
                    </Link>
                  </td>
                  <td style={{ padding: "10px 12px", color: "#66768b", fontSize: 12 }}>
                    {p.application_number}-{p.product_number}
                  </td>
                  <td style={{ padding: "10px 12px" }}>{p.strength_raw}</td>
                  <td style={{ padding: "10px 12px", color: "#66768b", fontSize: 12 }}>
                    {p.route_normalized ?? p.route_raw} / {p.dosage_form_normalized ?? p.dosage_form_raw}
                  </td>
                  <td style={{ padding: "10px 12px", fontSize: 12 }}>
                    {p.rld_flag ? "RLD" : ""} {p.reference_standard_flag ? "RS" : ""}
                    {!p.rld_flag && !p.reference_standard_flag && "—"}
                  </td>
                  <td style={{ padding: "10px 12px", fontSize: 12 }}>{p.discontinued ? "Yes" : "No"}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
            <button
              onClick={() => runSearch(page - 1)}
              disabled={page <= 1 || loading}
              style={{ padding: "4px 12px", borderRadius: 4, border: "1px solid #dce7f4", background: "#fff", cursor: page <= 1 ? "not-allowed" : "pointer", fontSize: 13 }}
            >
              Previous
            </button>
            <span style={{ fontSize: 13, color: "#66768b", alignSelf: "center" }}>Page {page}</span>
            <button
              onClick={() => runSearch(page + 1)}
              disabled={!hasNext || loading}
              style={{ padding: "4px 12px", borderRadius: 4, border: "1px solid #dce7f4", background: "#fff", cursor: !hasNext ? "not-allowed" : "pointer", fontSize: 13 }}
            >
              Next
            </button>
          </div>
        </>
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
