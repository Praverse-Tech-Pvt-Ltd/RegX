"use client";

import { Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams, useParams } from "next/navigation";
import Link from "next/link";
import { fdaData, type FdaDataSourceRelease, ApiError } from "@/lib/api";
import { ProvenanceLabel } from "@/components/ProvenanceLabel";

function ReleaseDetailInner() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const params = useParams<{ publicId: string }>();
  const tenantSlug = searchParams.get("tenant") ?? "";
  const publicId = params.publicId;

  const [release, setRelease] = useState<FdaDataSourceRelease | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [actionBusy, setActionBusy] = useState(false);

  function load() {
    if (!tenantSlug) return;
    setLoading(true);
    fdaData.releases
      .get(tenantSlug, publicId)
      .then(setRelease)
      .catch((err: unknown) => {
        if (err instanceof ApiError && err.status === 404) {
          setError("Release not found.");
        } else if (err instanceof ApiError && (err.status === 403 || err.status === 401)) {
          router.push("/signin");
        } else {
          setError("Failed to load release.");
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
  }, [tenantSlug, publicId]); // eslint-disable-line react-hooks/exhaustive-deps

  async function runAction(action: "submitReview" | "approve" | "activate") {
    setActionBusy(true);
    setActionError(null);
    try {
      if (action === "submitReview") await fdaData.releases.submitReview(tenantSlug, publicId);
      if (action === "approve") await fdaData.releases.approve(tenantSlug, publicId);
      if (action === "activate") await fdaData.releases.activate(tenantSlug, publicId);
      load();
    } catch (err) {
      setActionError(
        err instanceof ApiError
          ? err.message
          : "Action failed. This is not a regulatory decision -- correct the underlying issue and retry."
      );
    } finally {
      setActionBusy(false);
    }
  }

  if (!tenantSlug) return null;
  if (loading) return <main style={{ maxWidth: 800, margin: "2rem auto" }}>Loading…</main>;
  if (error || !release) {
    return (
      <main style={{ maxWidth: 800, margin: "2rem auto", padding: "0 1rem" }}>
        <p role="alert" style={{ color: "#b91c1c" }}>
          {error ?? "Release not found."}
        </p>
      </main>
    );
  }

  return (
    <main style={{ maxWidth: 800, margin: "2rem auto", padding: "0 1rem" }}>
      <div style={{ marginBottom: "0.5rem" }}>
        <Link href={`/fda-data/releases?tenant=${tenantSlug}`} style={{ color: "#1d4ed8", fontSize: 13, textDecoration: "none" }}>
          ← FDA releases
        </Link>
      </div>
      <h1 style={{ margin: "0 0 0.25rem" }}>{release.source_name}</h1>
      <p style={{ color: "#6b7280", fontSize: 13, marginTop: 0 }}>
        {release.dataset_type} · {release.official_source_reference}
      </p>

      <dl style={{ display: "grid", gridTemplateColumns: "220px 1fr", rowGap: 10, fontSize: 14 }}>
        <dt style={{ color: "#6b7280" }}>Status</dt>
        <dd style={{ margin: 0, fontWeight: 600 }}>{release.status.replace(/_/g, " ")}</dd>

        <dt style={{ color: "#6b7280" }}>Publication date</dt>
        <dd style={{ margin: 0 }}>
          {release.publication_date ?? "not recorded"} <ProvenanceLabel kind="FDA_SOURCE" />
        </dd>

        <dt style={{ color: "#6b7280" }}>Records imported / extracted</dt>
        <dd style={{ margin: 0 }}>
          {release.record_count_imported} / {release.record_count_extracted} ({release.record_count_failed} failed) <ProvenanceLabel kind="CALCULATED" />
        </dd>

        <dt style={{ color: "#6b7280" }}>Approved by</dt>
        <dd style={{ margin: 0 }}>
          {release.approved_by_email ? (
            <>
              {release.approved_by_email} <ProvenanceLabel kind="REVIEWER_CONFIRMED" />
            </>
          ) : (
            "not yet approved"
          )}
        </dd>

        <dt style={{ color: "#6b7280" }}>Activated by</dt>
        <dd style={{ margin: 0 }}>
          {release.activated_by_email ? (
            <>
              {release.activated_by_email} <ProvenanceLabel kind="REVIEWER_CONFIRMED" />
            </>
          ) : (
            "not yet activated"
          )}
        </dd>
      </dl>

      <div style={{ display: "flex", gap: 8, marginTop: "1.5rem", flexWrap: "wrap" }}>
        {release.status === "registered" || release.status === "staged" || release.status === "validated" ? (
          <button onClick={() => runAction("submitReview")} disabled={actionBusy} style={buttonStyle}>
            Submit for review
          </button>
        ) : null}
        {release.status === "under_review" && (
          <button onClick={() => runAction("approve")} disabled={actionBusy} style={buttonStyle}>
            Approve
          </button>
        )}
        {release.status === "approved" && (
          <button onClick={() => runAction("activate")} disabled={actionBusy} style={buttonStyle}>
            Activate
          </button>
        )}
        <Link
          href={fdaData.releases.reconciliationCsvUrl(release.public_id)}
          style={{ ...buttonStyle, background: "#374151", textDecoration: "none", display: "inline-block" }}
        >
          Download reconciliation (CSV)
        </Link>
      </div>
      {actionError && (
        <p role="alert" style={{ color: "#b91c1c", fontSize: 13, marginTop: 8 }}>
          {actionError}
        </p>
      )}
      <p style={{ fontSize: 12, color: "#6b7280", marginTop: 12 }}>
        Approving or activating a release is a data-governance action only. It does not
        constitute a regulatory determination about any formulation compared against it.
      </p>
    </main>
  );
}

const buttonStyle: React.CSSProperties = {
  background: "#1d4ed8",
  color: "#fff",
  border: "none",
  borderRadius: 6,
  padding: "8px 18px",
  cursor: "pointer",
  fontWeight: 600,
  fontSize: 13,
};

export default function ReleaseDetailPage() {
  return (
    <Suspense>
      <ReleaseDetailInner />
    </Suspense>
  );
}
