"use client";

import { Suspense, useEffect, useState, type FormEvent } from "react";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import {
  submissionDossiers,
  ApiError,
  type DossierDetail,
  type DossierSection,
} from "@/lib/api";
import { DossierStatusBadge, ReadinessBadge } from "../readiness-badge";
import { SectionTree } from "../section-tree";
import { SectionPanel } from "./section-panel";

const T = {
  ink: "#001f45",
  text: "#314155",
  muted: "#66768b",
  line: "#dce7f4",
  soft: "#eaf2fd",
  panel: "#f4f8fe",
  blue: "#045e8f",
  navy: "#003865",
} as const;

const field: React.CSSProperties = {
  padding: "0.45rem 0.6rem",
  border: `1px solid ${T.line}`,
  borderRadius: 6,
  background: "#fff",
  color: T.text,
  fontSize: "0.88rem",
};

function ghost(disabled: boolean): React.CSSProperties {
  return {
    padding: "0.35rem 0.8rem",
    border: `1px solid ${T.line}`,
    borderRadius: 6,
    background: "#fff",
    color: T.blue,
    fontSize: "0.84rem",
    fontWeight: 600,
    cursor: disabled ? "not-allowed" : "pointer",
    opacity: disabled ? 0.5 : 1,
  };
}

function Stat({ label, value, testId }: { label: string; value: number | null; testId: string }) {
  // null means the server withheld it. Rendering 0 would assert something false
  // about resources the caller cannot see.
  const withheld = value === null;
  return (
    <div
      data-testid={testId}
      title={withheld ? "Requires permission for that module" : undefined}
      style={{
        padding: "0.6rem 0.8rem",
        border: `1px solid ${T.line}`,
        borderRadius: 8,
        background: "#fff",
        minWidth: 110,
      }}
    >
      <div style={{ fontSize: "1.2rem", fontWeight: 700, color: withheld ? T.muted : T.ink }}>
        {withheld ? "—" : value}
      </div>
      <div style={{ fontSize: "0.72rem", color: T.muted }}>{label}</div>
    </div>
  );
}

function DossierInner() {
  const router = useRouter();
  const params = useParams<{ publicId: string }>();
  const searchParams = useSearchParams();
  const tenantSlug = searchParams.get("tenant") ?? "";
  const publicId = params.publicId;

  const [detail, setDetail] = useState<DossierDetail | null>(null);
  const [selected, setSelected] = useState<DossierSection | null>(null);
  const [loading, setLoading] = useState(true);
  const [notFound, setNotFound] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [showAdd, setShowAdd] = useState(false);
  const [form, setForm] = useState({ section_code: "", title: "", required: true });

  function load(): Promise<void> {
    if (!tenantSlug) return Promise.resolve();
    setLoading(true);
    return submissionDossiers
      .get(tenantSlug, publicId)
      .then((d) => {
        setDetail(d);
        setError(null);
        // Keep the selected section pointing at fresh data after a reload.
        setSelected((prev) =>
          prev ? d.sections.find((s) => s.public_id === prev.public_id) ?? null : null
        );
      })
      .catch((err: unknown) => {
        if (err instanceof ApiError && err.status === 404) setNotFound(true);
        else if (err instanceof ApiError && (err.status === 403 || err.status === 401))
          router.push(
            `/signin?next=${encodeURIComponent(window.location.pathname + window.location.search)}`
          );
        else setError("Failed to load this dossier.");
      })
      .finally(() => setLoading(false));
  }

  useEffect(() => {
    if (!tenantSlug) {
      router.push("/tenants");
      return;
    }
    void load();
  }, [tenantSlug, publicId]); // eslint-disable-line react-hooks/exhaustive-deps

  async function run(fn: () => Promise<unknown>, conflictMessage: string) {
    setBusy(true);
    try {
      await fn();
      await load();
    } catch (err: unknown) {
      // Reload FIRST, then set the message: load() clears the error on success,
      // so setting it beforehand would wipe it -- the ordering bug found in M6,
      // M7 and again in M8.
      await load();
      if (err instanceof ApiError && err.status === 409) setError(conflictMessage);
      else if (err instanceof ApiError && err.status === 403)
        setError("You do not have permission to do that in this tenant.");
      else if (err instanceof ApiError && err.status === 400)
        setError("That request was rejected. Check the values and try again.");
      else setError("The action could not be completed.");
    } finally {
      setBusy(false);
    }
  }

  async function addSection(e: FormEvent) {
    e.preventDefault();
    await run(
      () =>
        submissionDossiers.createSection(tenantSlug, publicId, {
          section_code: form.section_code.trim(),
          title: form.title.trim(),
          required: form.required,
          parent_public_id: selected ? selected.public_id : null,
        }),
      "That section code already exists, or this dossier no longer accepts changes."
    );
    setForm({ section_code: "", title: "", required: true });
    setShowAdd(false);
  }

  if (!tenantSlug) return null;

  if (notFound) {
    return (
      <main style={{ maxWidth: 1100, margin: "2rem auto", padding: "0 1rem" }}>
        <p data-testid="dossier-not-found" style={{ color: T.muted }}>
          This dossier was not found.
        </p>
      </main>
    );
  }

  if (loading && !detail) {
    return (
      <main style={{ maxWidth: 1100, margin: "2rem auto", padding: "0 1rem" }}>
        <p style={{ color: T.muted }}>Loading dossier…</p>
      </main>
    );
  }
  if (!detail) return null;

  const { dossier, sections, summary, permissions, module_counts } = detail;
  const canEdit = permissions.can_manage_sections && !dossier.is_terminal;

  return (
    <main style={{ maxWidth: 1200, margin: "2rem auto", padding: "0 1rem" }}>
      <Link
        href={`/regulatory-cases/${dossier.regulatory_case_public_id}?tenant=${tenantSlug}`}
        data-testid="back-to-case"
        style={{ fontSize: "0.85rem", color: T.muted, textDecoration: "none" }}
      >
        ← Back to case
      </Link>

      <header style={{ marginTop: "0.5rem", marginBottom: "1.25rem" }}>
        <div style={{ display: "flex", gap: "0.6rem", alignItems: "center", flexWrap: "wrap" }}>
          <h1 style={{ margin: 0, fontSize: "1.5rem", fontWeight: 700, color: T.ink }}>
            {dossier.title}
          </h1>
          <DossierStatusBadge status={dossier.status} />
        </div>

        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: "0.6rem",
            marginTop: "0.6rem",
            flexWrap: "wrap",
          }}
        >
          <span style={{ fontSize: "0.8rem", color: T.muted }}>Internal readiness</span>
          <ReadinessBadge readiness={summary.overall_readiness} />
        </div>

        <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap", margin: "1rem 0" }}>
          <Stat label="Sections" value={summary.total_sections} testId="stat-total" />
          <Stat label="Required" value={summary.required_sections} testId="stat-required" />
          <Stat label="Ready" value={summary.ready} testId="stat-ready" />
          <Stat label="Partially" value={summary.partially_ready} testId="stat-partial" />
          <Stat label="Not ready" value={summary.not_ready} testId="stat-notready" />
          <Stat label="N/A" value={summary.not_applicable} testId="stat-na" />
          <Stat label="Open blockers" value={summary.open_blockers} testId="stat-blockers" />
          <Stat
            label="Evidence links"
            value={module_counts.workflow_evidence_links}
            testId="stat-evidence"
          />
        </div>

        <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
          {/* Advisory only -- the API re-checks, and refuses on a terminal dossier. */}
          {permissions.can_complete && !dossier.is_terminal && (
            <button
              type="button"
              data-testid="complete-dossier"
              disabled={busy}
              onClick={() =>
                void run(
                  () => submissionDossiers.complete(tenantSlug, publicId),
                  "Required sections are not internally ready, or this dossier is already closed."
                )
              }
              style={ghost(busy)}
            >
              Complete dossier
            </button>
          )}
          {permissions.can_cancel && !dossier.is_terminal && (
            <button
              type="button"
              data-testid="cancel-dossier"
              disabled={busy}
              onClick={() =>
                void run(
                  () => submissionDossiers.cancel(tenantSlug, publicId),
                  "This dossier is already closed."
                )
              }
              style={ghost(busy)}
            >
              Cancel dossier
            </button>
          )}
          {canEdit && (
            <button
              type="button"
              data-testid="add-section"
              onClick={() => setShowAdd((v) => !v)}
              style={ghost(false)}
            >
              {showAdd ? "Close" : selected ? `Add child of ${selected.section_code}` : "Add section"}
            </button>
          )}
        </div>

        {dossier.is_terminal && (
          <p
            data-testid="dossier-terminal-note"
            style={{
              marginTop: "0.9rem",
              padding: "0.6rem 0.8rem",
              border: `1px solid ${T.line}`,
              borderRadius: 6,
              background: T.panel,
              color: T.muted,
              fontSize: "0.85rem",
            }}
          >
            This dossier is {dossier.status} and no longer accepts changes. Completing a dossier
            records that internal work stopped; it is not a submission to an authority and not a
            regulatory approval.
          </p>
        )}
      </header>

      {error && (
        <p
          role="alert"
          data-testid="dossier-error"
          style={{
            margin: "0 0 1rem",
            padding: "0.6rem 0.8rem",
            border: "1px solid #f3c9c4",
            borderRadius: 6,
            background: "#fdf3f2",
            color: "#8f2c20",
            fontSize: "0.88rem",
          }}
        >
          {error}
        </p>
      )}

      {showAdd && canEdit && (
        <form
          onSubmit={addSection}
          data-testid="add-section-form"
          aria-label="Add section form"
          style={{
            display: "flex",
            gap: "0.5rem",
            flexWrap: "wrap",
            alignItems: "end",
            marginBottom: "1rem",
            padding: "0.9rem",
            border: `1px solid ${T.line}`,
            borderRadius: 8,
            background: T.panel,
          }}
        >
          <label style={{ display: "grid", gap: 4, fontSize: "0.78rem", color: T.ink }}>
            Section code *
            <input
              data-testid="new-section-code"
              value={form.section_code}
              onChange={(e) => setForm({ ...form, section_code: e.target.value })}
              style={field}
            />
          </label>
          <label style={{ display: "grid", gap: 4, fontSize: "0.78rem", color: T.ink }}>
            Title *
            <input
              data-testid="new-section-title"
              value={form.title}
              onChange={(e) => setForm({ ...form, title: e.target.value })}
              style={{ ...field, minWidth: 240 }}
            />
          </label>
          <label style={{ display: "flex", gap: 6, fontSize: "0.82rem", color: T.text }}>
            <input
              type="checkbox"
              data-testid="new-section-required"
              checked={form.required}
              onChange={(e) => setForm({ ...form, required: e.target.checked })}
            />
            Required
          </label>
          <button
            type="submit"
            data-testid="new-section-submit"
            disabled={busy || !form.section_code.trim() || !form.title.trim()}
            style={{
              padding: "0.45rem 1rem",
              border: `1px solid ${busy || !form.section_code.trim() ? T.line : T.navy}`,
              borderRadius: 6,
              background: busy || !form.section_code.trim() ? T.soft : T.blue,
              color: busy || !form.section_code.trim() ? T.muted : "#fff",
              fontWeight: 600,
              cursor: busy || !form.section_code.trim() ? "not-allowed" : "pointer",
            }}
          >
            Add
          </button>
        </form>
      )}

      <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 1.4fr) minmax(0, 1fr)", gap: "1.25rem" }}>
        <section aria-label="Section outline">
          <SectionTree
            sections={sections}
            selectedPublicId={selected?.public_id ?? null}
            onSelect={setSelected}
          />
        </section>

        <SectionPanel
          tenantSlug={tenantSlug}
          section={selected}
          permissions={permissions}
          dossierTerminal={dossier.is_terminal}
          onChanged={() => void load()}
        />
      </div>
    </main>
  );
}

export default function SubmissionDossierPage() {
  return (
    <Suspense fallback={<p>Loading…</p>}>
      <DossierInner />
    </Suspense>
  );
}
