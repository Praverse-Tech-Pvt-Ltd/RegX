"use client";

import { Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams, useParams } from "next/navigation";
import Link from "next/link";
import { iidAssessments, type AssessmentSnapshotDetail, ApiError } from "@/lib/api";
import { ProvenanceLabel } from "@/components/ProvenanceLabel";

const DECISION_STATUS_LABELS: Record<string, string> = {
  PASS_WITH_IID_PRECEDENT: "Within IID precedent",
  REVIEW_REQUIRED: "Review required",
  EXCEEDS_IID_PRECEDENT: "Exceeds IID precedent",
  NO_MATCH: "No matching precedent",
  NOT_COMPARABLE: "Not comparable",
};

const DECISION_COLOURS: Record<string, string> = {
  PASS_WITH_IID_PRECEDENT: "#166534",
  REVIEW_REQUIRED: "#92400e",
  EXCEEDS_IID_PRECEDENT: "#991b1b",
  NO_MATCH: "#6b7280",
  NOT_COMPARABLE: "#6b7280",
};

function CalculationBlock({ label, calc }: { label: string; calc: Record<string, unknown> | undefined }) {
  if (!calc) return null;
  const ok = calc.status === "OK";
  return (
    <div style={{ marginBottom: 8, fontSize: 13 }}>
      <strong>{label}</strong> <ProvenanceLabel kind="CALCULATED" />
      {ok ? (
        <span style={{ marginLeft: 8 }}>
          {String(calc.value)} {calc.unit ? String(calc.unit) : ""}
        </span>
      ) : (
        <span style={{ marginLeft: 8, color: "#92400e" }}>Blocked: {String(calc.status)}</span>
      )}
    </div>
  );
}

function SnapshotDetailInner() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const params = useParams<{ publicId: string }>();
  const tenantSlug = searchParams.get("tenant") ?? "";
  const publicId = params.publicId;

  const [snapshot, setSnapshot] = useState<AssessmentSnapshotDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!tenantSlug) {
      router.push("/tenants");
      return;
    }
    setLoading(true);
    iidAssessments
      .get(tenantSlug, publicId)
      .then(setSnapshot)
      .catch((err: unknown) => {
        if (err instanceof ApiError && err.status === 404) setError("Assessment snapshot not found.");
        else if (err instanceof ApiError && (err.status === 403 || err.status === 401))
          router.push(`/signin?next=${encodeURIComponent(window.location.pathname + window.location.search)}`);
        else setError("Failed to load assessment snapshot.");
      })
      .finally(() => setLoading(false));
  }, [tenantSlug, publicId]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!tenantSlug) return null;
  if (loading) return <main style={{ maxWidth: 900, margin: "2rem auto" }}>Loading…</main>;
  if (error || !snapshot) {
    return (
      <main style={{ maxWidth: 900, margin: "2rem auto", padding: "0 1rem" }}>
        <p role="alert" style={{ color: "#b91c1c" }}>
          {error ?? "Assessment snapshot not found."}
        </p>
      </main>
    );
  }

  return (
    <main style={{ maxWidth: 900, margin: "2rem auto", padding: "0 1rem" }}>
      <div style={{ marginBottom: "0.5rem" }}>
        <Link href={`/iid-assessments/preview?tenant=${tenantSlug}`} style={{ color: "#1d4ed8", fontSize: 13, textDecoration: "none" }}>
          ← New assessment preview
        </Link>
      </div>
      <h1 style={{ margin: "0 0 0.25rem" }}>Persisted IID Assessment</h1>
      <p style={{ color: "#6b7280", fontSize: 13, marginTop: 0, marginBottom: "1rem" }}>
        This is a frozen, immutable record. Later FDA data refreshes can never retroactively
        change what is displayed here — a correction always creates a new assessment, never an
        edit of this one.
      </p>

      <section aria-label="Selected IID precedent" style={{ marginBottom: 16, fontSize: 13 }}>
        <strong>Selected IID precedent</strong> <ProvenanceLabel kind="FDA_SOURCE" />
        <p style={{ margin: "4px 0 0" }}>
          {snapshot.iid_ingredient_name || "—"} — {snapshot.iid_potency_amount ?? "FDA VALUE UNAVAILABLE"}{" "}
          {snapshot.iid_potency_unit} potency, {snapshot.iid_mde ?? "MDE UNAVAILABLE"} {snapshot.iid_mde_unit} MDE
        </p>
        <p style={{ margin: "4px 0 0", color: "#6b7280" }}>
          Route: {snapshot.iid_route || "—"} · Dosage form: {snapshot.iid_dosage_form || "—"}
        </p>
      </section>

      <section aria-label="Proposed formulation values" style={{ marginBottom: 16, fontSize: 13 }}>
        <strong>Proposed formulation</strong> <ProvenanceLabel kind="USER_INPUT" />
        <p style={{ margin: "4px 0 0" }}>
          {snapshot.proposed_quantity_per_unit ?? "—"} {snapshot.proposed_quantity_unit}
          {snapshot.proposed_daily_exposure && ` (${snapshot.proposed_daily_exposure} daily exposure)`}
        </p>
      </section>

      <section aria-label="Calculations" style={{ marginBottom: 16 }}>
        <h2 style={{ fontSize: 14 }}>Calculations</h2>
        {Object.entries(snapshot.calculation_results).map(([key, calc]) => (
          <CalculationBlock key={key} label={key.replace(/_/g, " ")} calc={calc} />
        ))}
      </section>

      <div
        role="status"
        style={{
          border: `1px solid ${DECISION_COLOURS[snapshot.decision_status] ?? "#6b7280"}`,
          borderRadius: 8,
          padding: "1rem",
        }}
      >
        <p style={{ margin: "0 0 4px", fontWeight: 700, color: DECISION_COLOURS[snapshot.decision_status] ?? "#374151" }}>
          {DECISION_STATUS_LABELS[snapshot.decision_status] ?? snapshot.decision_status}
        </p>
        <p style={{ margin: 0, fontSize: 13 }}>{snapshot.decision_note}</p>
        {snapshot.reviewer_confirmed_match && (
          <p style={{ margin: "8px 0 0", fontSize: 13 }}>
            Match confirmed by reviewer <ProvenanceLabel kind="REVIEWER_CONFIRMED" />
          </p>
        )}
        {snapshot.override_applied && (
          <p style={{ margin: "8px 0 0", fontSize: 13, color: "#92400e" }}>
            Override applied: {snapshot.override_justification}
          </p>
        )}
      </div>
    </main>
  );
}

export default function SnapshotDetailPage() {
  return (
    <Suspense>
      <SnapshotDetailInner />
    </Suspense>
  );
}
