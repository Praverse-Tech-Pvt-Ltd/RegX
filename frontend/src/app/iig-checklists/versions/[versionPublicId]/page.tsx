"use client";

import { Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams, useParams } from "next/navigation";
import { iigChecklists, type ChecklistVersion, ApiError } from "@/lib/api";

function VersionDetailInner() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const params = useParams<{ versionPublicId: string }>();
  const tenantSlug = searchParams.get("tenant") ?? "";
  const publicId = params.versionPublicId;

  const [version, setVersion] = useState<ChecklistVersion | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [actionBusy, setActionBusy] = useState(false);
  const [returnReason, setReturnReason] = useState("");

  function load() {
    if (!tenantSlug) return;
    setLoading(true);
    iigChecklists.versions
      .get(tenantSlug, publicId)
      .then(setVersion)
      .catch((err: unknown) => {
        if (err instanceof ApiError && err.status === 404) {
          setError("Checklist version not found.");
        } else if (err instanceof ApiError && (err.status === 403 || err.status === 401)) {
          router.push("/signin");
        } else {
          setError("Failed to load checklist version.");
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

  async function runAction(
    action: "submitReview" | "approve" | "return" | "reject" | "activate" | "supersede" | "retire"
  ) {
    setActionBusy(true);
    setActionError(null);
    try {
      if (action === "submitReview") await iigChecklists.versions.submitReview(tenantSlug, publicId);
      if (action === "approve") await iigChecklists.versions.approve(tenantSlug, publicId);
      if (action === "return") {
        if (!returnReason.trim()) {
          setActionError("A return reason is required.");
          setActionBusy(false);
          return;
        }
        await iigChecklists.versions.return(tenantSlug, publicId, returnReason);
      }
      if (action === "reject") await iigChecklists.versions.reject(tenantSlug, publicId);
      if (action === "activate") await iigChecklists.versions.activate(tenantSlug, publicId);
      if (action === "supersede") await iigChecklists.versions.supersede(tenantSlug, publicId);
      if (action === "retire") await iigChecklists.versions.retire(tenantSlug, publicId);
      setReturnReason("");
      load();
    } catch (err) {
      setActionError(
        err instanceof ApiError
          ? err.message
          : "Action failed. Correct the underlying issue and retry."
      );
    } finally {
      setActionBusy(false);
    }
  }

  if (!tenantSlug) return null;
  if (loading) return <main style={{ maxWidth: 800, margin: "2rem auto" }}>Loading…</main>;
  if (error || !version) {
    return (
      <main style={{ maxWidth: 800, margin: "2rem auto", padding: "0 1rem" }}>
        <p role="alert" style={{ color: "#b91c1c" }}>
          {error ?? "Checklist version not found."}
        </p>
      </main>
    );
  }

  return (
    <main style={{ maxWidth: 800, margin: "2rem auto", padding: "0 1rem" }}>
      <h1 style={{ margin: "0 0 0.25rem" }}>Checklist version {version.version_number}</h1>

      {version.scope_type === "platform_master" && (
        <p style={{ fontSize: 12, color: "#92400e", background: "#fffbeb", padding: "6px 10px", borderRadius: 4, marginTop: 0 }}>
          This is platform-master content, visible to every tenant. Modifying it
          (lifecycle actions, sections, questions, applicability rules) requires a
          separate, explicit platform-level authorization beyond ordinary permissions
          — the server will reject any action below that you are not authorized for.
        </p>
      )}

      <dl style={{ display: "grid", gridTemplateColumns: "220px 1fr", rowGap: 10, fontSize: 14 }}>
        <dt style={{ color: "#6b7280" }}>Status</dt>
        <dd style={{ margin: 0, fontWeight: 600 }}>{version.status.replace(/_/g, " ")}</dd>

        <dt style={{ color: "#6b7280" }}>Effective date</dt>
        <dd style={{ margin: 0 }}>{version.effective_date ?? "not set"}</dd>

        <dt style={{ color: "#6b7280" }}>Submitted by</dt>
        <dd style={{ margin: 0 }}>{version.submitted_by_email ?? "not yet submitted"}</dd>

        <dt style={{ color: "#6b7280" }}>Approved by</dt>
        <dd style={{ margin: 0 }}>{version.approved_by_email ?? "not yet approved"}</dd>

        <dt style={{ color: "#6b7280" }}>Activated by</dt>
        <dd style={{ margin: 0 }}>{version.activated_by_email ?? "not yet activated"}</dd>

        {version.return_reason && (
          <>
            <dt style={{ color: "#6b7280" }}>Last return reason</dt>
            <dd style={{ margin: 0 }}>{version.return_reason}</dd>
          </>
        )}
      </dl>

      <h2 style={{ fontSize: 16, marginTop: "1.5rem" }}>Sections</h2>
      {!version.sections || version.sections.length === 0 ? (
        <p style={{ color: "#6b7280", fontSize: 14 }}>No sections defined yet.</p>
      ) : (
        version.sections.map((section) => (
          <div key={section.public_id} style={{ marginBottom: 12 }}>
            <strong style={{ fontSize: 14 }}>
              {section.display_order}. {section.title}
            </strong>
            <ul style={{ fontSize: 13, color: "#374151" }}>
              {(section.questions ?? []).map((q) => (
                <li key={q.public_id}>{q.question_text}</li>
              ))}
            </ul>
          </div>
        ))
      )}

      <div style={{ display: "flex", gap: 8, marginTop: "1.5rem", flexWrap: "wrap", alignItems: "center" }}>
        {(version.status === "draft" || version.status === "returned") && (
          <button onClick={() => runAction("submitReview")} disabled={actionBusy} style={buttonStyle}>
            Submit for review
          </button>
        )}
        {version.status === "under_review" && (
          <>
            <button onClick={() => runAction("approve")} disabled={actionBusy} style={buttonStyle}>
              Approve
            </button>
            <button onClick={() => runAction("reject")} disabled={actionBusy} style={{ ...buttonStyle, background: "#991b1b" }}>
              Reject
            </button>
          </>
        )}
        {version.status === "approved" && (
          <button onClick={() => runAction("activate")} disabled={actionBusy} style={buttonStyle}>
            Activate
          </button>
        )}
        {version.status === "active" && (
          <button onClick={() => runAction("supersede")} disabled={actionBusy} style={{ ...buttonStyle, background: "#6b7280" }}>
            Supersede
          </button>
        )}
        {["draft", "approved", "active", "returned"].includes(version.status) && (
          <button onClick={() => runAction("retire")} disabled={actionBusy} style={{ ...buttonStyle, background: "#6b7280" }}>
            Retire
          </button>
        )}
      </div>

      {version.status === "under_review" && (
        <div style={{ marginTop: 12 }}>
          <label style={{ display: "block", fontSize: 13, fontWeight: 500, marginBottom: 4 }}>
            Return reason (required to return)
            <input
              value={returnReason}
              onChange={(e) => setReturnReason(e.target.value)}
              style={{ display: "block", width: "100%", marginTop: 4, padding: "6px 8px", border: "1px solid #d1d5db", borderRadius: 4, boxSizing: "border-box" }}
            />
          </label>
          <button onClick={() => runAction("return")} disabled={actionBusy} style={{ ...buttonStyle, background: "#b45309" }}>
            Return for edits
          </button>
        </div>
      )}

      {actionError && (
        <p role="alert" style={{ color: "#b91c1c", fontSize: 13, marginTop: 8 }}>
          {actionError}
        </p>
      )}
      <p style={{ fontSize: 12, color: "#6b7280", marginTop: 12 }}>
        This screen governs checklist structure and lifecycle only. It does not present
        or run checklist execution, responses, or calculation outcomes.
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

export default function VersionDetailPage() {
  return (
    <Suspense>
      <VersionDetailInner />
    </Suspense>
  );
}
