"use client";

import { Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams, useParams } from "next/navigation";
import Link from "next/link";
import { fdaData, type OrangeBookProduct, ApiError, isSignedOut, loadError } from "@/lib/api";
import { ProvenanceLabel } from "@/components/ProvenanceLabel";

function OrangeBookDetailInner() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const params = useParams<{ publicId: string }>();
  const tenantSlug = searchParams.get("tenant") ?? "";
  const publicId = params.publicId;

  const [product, setProduct] = useState<OrangeBookProduct | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!tenantSlug) {
      router.push("/tenants");
      return;
    }
    setLoading(true);
    fdaData.orangeBook
      .get(tenantSlug, publicId)
      .then(setProduct)
      .catch((err: unknown) => {
        if (err instanceof ApiError && err.status === 404) setError("Product not found.");
        else if (isSignedOut(err))
          router.push(`/signin?next=${encodeURIComponent(window.location.pathname + window.location.search)}`);
        else setError(loadError(err, "Failed to load product."));
      })
      .finally(() => setLoading(false));
  }, [tenantSlug, publicId]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!tenantSlug) return null;
  if (loading) return <main style={{ maxWidth: 700, margin: "2rem auto" }}>Loading…</main>;
  if (error || !product) {
    return (
      <main style={{ maxWidth: 700, margin: "2rem auto", padding: "0 1rem" }}>
        <p role="alert" style={{ color: "#c0392b" }}>
          {error ?? "Product not found."}
        </p>
      </main>
    );
  }

  return (
    <main style={{ maxWidth: 700, margin: "2rem auto", padding: "0 1rem" }}>
      <div style={{ marginBottom: "0.5rem" }}>
        <Link href={`/fda-data/orange-book?tenant=${tenantSlug}`} style={{ color: "#045e8f", fontSize: 13, textDecoration: "none" }}>
          ← Orange Book search
        </Link>
      </div>
      <h1 style={{ margin: "0 0 0.25rem" }}>
        {product.trade_name || "(untitled)"} <ProvenanceLabel kind="FDA_SOURCE" />
      </h1>
      <p style={{ color: "#66768b", fontSize: 13, marginTop: 0 }}>
        Application {product.application_number}-{product.product_number} ({product.application_type})
      </p>

      <dl style={{ display: "grid", gridTemplateColumns: "220px 1fr", rowGap: 10, fontSize: 14 }}>
        <dt style={{ color: "#66768b" }}>Active ingredient</dt>
        <dd style={{ margin: 0 }}>{product.active_ingredient_raw}</dd>

        <dt style={{ color: "#66768b" }}>Route / dosage form</dt>
        <dd style={{ margin: 0 }}>
          {product.route_normalized ?? product.route_raw} / {product.dosage_form_normalized ?? product.dosage_form_raw}
        </dd>

        <dt style={{ color: "#66768b" }}>Strength (raw)</dt>
        <dd style={{ margin: 0, fontFamily: "monospace" }}>{product.strength_raw}</dd>

        <dt style={{ color: "#66768b" }}>Strength (parsed)</dt>
        <dd style={{ margin: 0 }}>
          {product.strength_parse_status === "parsed" && product.strength_amount
            ? product.strength_amount
            : "REVIEW REQUIRED"}
        </dd>

        <dt style={{ color: "#66768b" }}>TE code</dt>
        <dd style={{ margin: 0 }}>{product.te_code || "—"}</dd>

        <dt style={{ color: "#66768b" }}>Approval date</dt>
        <dd style={{ margin: 0 }}>
          {product.approval_date ?? (product.approval_date_text || "not recorded")}
        </dd>

        <dt style={{ color: "#66768b" }}>RLD</dt>
        <dd style={{ margin: 0 }}>{product.rld_flag ? "Yes" : "No"}</dd>

        <dt style={{ color: "#66768b" }}>Reference standard</dt>
        <dd style={{ margin: 0 }}>{product.reference_standard_flag ? "Yes" : "No"}</dd>

        <dt style={{ color: "#66768b" }}>Discontinued</dt>
        <dd style={{ margin: 0 }}>{product.discontinued ? "Yes" : "No"}</dd>

        <dt style={{ color: "#66768b" }}>Source release</dt>
        <dd style={{ margin: 0, fontFamily: "monospace", fontSize: 12 }}>{product.release}</dd>
      </dl>

      <p style={{ fontSize: 12, color: "#66768b", marginTop: 16 }}>
        Being marked RLD or reference standard here is FDA-sourced metadata only. Selecting
        this product as a formulation&apos;s reference product is always a separate, explicit
        action on the product record — it is never inferred from these flags.
      </p>
    </main>
  );
}

export default function OrangeBookDetailPage() {
  return (
    <Suspense>
      <OrangeBookDetailInner />
    </Suspense>
  );
}
