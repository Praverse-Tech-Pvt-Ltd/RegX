"use client";

import { Suspense, useCallback, useEffect, useState, type FormEvent } from "react";
import Link from "next/link";
import { useParams, useSearchParams } from "next/navigation";
import {
  ApiError,
  dossierBlueprints,
  regulatoryCases,
  type BlueprintSection,
  type BlueprintVersionDetail,
  type RegulatoryCase,
} from "@/lib/api";
import { BlueprintTree } from "../../../blueprint-tree";
import { ActiveMeaningNote, VersionStatusBadge } from "../../../status-badge";

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

function VersionDetailInner() {
  const params = useParams<{ publicId: string; versionPublicId: string }>();
  const search = useSearchParams();
  const tenantSlug = search.get("tenant") ?? "";
  const { publicId, versionPublicId } = params;

  const [detail, setDetail] = useState<BlueprintVersionDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [selected, setSelected] = useState<BlueprintSection | null>(null);

  const [showAdd, setShowAdd] = useState(false);
  const [code, setCode] = useState("");
  const [title, setTitle] = useState("");
  const [required, setRequired] = useState(true);
  const [offset, setOffset] = useState("");
  const [parentId, setParentId] = useState("");

  const [showInstantiate, setShowInstantiate] = useState(false);

  const load = useCallback((): Promise<void> => {
    setLoading(true);
    return dossierBlueprints
      .getVersion(tenantSlug, versionPublicId)
      .then((d) => {
        setDetail(d);
        setError(null);
      })
      .catch((err: unknown) => {
        if (err instanceof ApiError && err.status === 404) setError("Version not found.");
        else setError("Failed to load this version.");
      })
      .finally(() => setLoading(false));
  }, [tenantSlug, versionPublicId]);

  useEffect(() => {
    void load();
  }, [load]);

  async function act(fn: () => Promise<unknown>, conflictMessage: string) {
    setBusy(true);
    try {
      await fn();
      await load();
    } catch (err: unknown) {
      // Reload first, then set the message: load() clears errors on success.
      await load();
      if (err instanceof ApiError && err.status === 409) setError(conflictMessage);
      else if (err instanceof ApiError && err.status === 403)
        setError("You do not have permission to do that in this tenant.");
      else if (err instanceof ApiError && err.status === 400)
        setError("Check the values and try again.");
      else setError("The action could not be completed.");
    } finally {
      setBusy(false);
    }
  }

  async function addSection(e: FormEvent) {
    e.preventDefault();
    await act(
      () =>
        dossierBlueprints.createSection(tenantSlug, versionPublicId, {
          section_code: code.trim(),
          title: title.trim(),
          required,
          parent_public_id: parentId || null,
          default_due_offset_days: offset.trim() ? Number(offset) : null,
        }),
      "A section with that code already exists in this version."
    );
    setCode("");
    setTitle("");
    setOffset("");
  }

  function move(section: BlueprintSection, direction: -1 | 1) {
    if (!detail) return;
    const siblings = detail.sections
      .filter((s) => s.parent_public_id === section.parent_public_id)
      .sort((a, b) => a.sequence - b.sequence || a.public_id.localeCompare(b.public_id));
    const index = siblings.findIndex((s) => s.public_id === section.public_id);
    const target = index + direction;
    if (target < 0 || target >= siblings.length) return;
    void act(
      () => dossierBlueprints.reorderSection(tenantSlug, section.public_id, target),
      "That section could not be moved."
    );
  }

  if (loading && !detail) return <main style={page}>Loading version…</main>;
  if (!detail)
    return (
      <main style={page}>
        <p role="alert" data-testid="version-error" style={alertStyle}>
          {error ?? "Version not found."}
        </p>
      </main>
    );

  const p = detail.permissions;
  const editable = detail.is_editable && p.can_manage_sections;
  const canActivate = detail.is_editable && p.can_activate;
  const canRetire = detail.status !== "retired" && p.can_retire;
  const canInstantiate = detail.status === "active" && p.can_instantiate;

  return (
    <main style={page}>
      <nav style={{ marginBottom: "0.75rem", fontSize: "0.85rem" }}>
        <Link href={`/dossier-blueprints/${publicId}?tenant=${tenantSlug}`} data-testid="back-to-blueprint">
          ← {detail.blueprint.name}
        </Link>
      </nav>

      <header style={{ marginBottom: "1rem" }}>
        <div style={{ display: "flex", alignItems: "center", gap: "0.6rem", flexWrap: "wrap" }}>
          <h1 style={{ margin: 0, color: T.ink, fontSize: "1.35rem" }} data-testid="version-heading">
            Version {detail.version_number}
          </h1>
          <VersionStatusBadge status={detail.status} />
          <span style={{ color: T.muted, fontSize: "0.85rem" }} data-testid="version-section-count">
            {detail.section_count} section{detail.section_count === 1 ? "" : "s"}
          </span>
          <span style={{ color: T.muted, fontSize: "0.85rem" }} data-testid="version-usage">
            · used by {detail.instantiation_count} dossier
            {detail.instantiation_count === 1 ? "" : "s"}
          </span>
        </div>

        {!detail.is_editable && (
          <p
            data-testid="read-only-note"
            style={{
              margin: "0.6rem 0 0",
              padding: "0.6rem 0.8rem",
              border: `1px solid ${T.line}`,
              borderRadius: 6,
              background: T.panel,
              color: T.muted,
              fontSize: "0.85rem",
              lineHeight: 1.6,
            }}
          >
            This version is {detail.status} and its structure is read-only. Start a new version to
            make changes; dossiers already created from this one are unaffected.
          </p>
        )}
        <div style={{ marginTop: "0.6rem" }}>
          <ActiveMeaningNote />
        </div>
      </header>

      {error && (
        <p role="alert" data-testid="version-error" style={alertStyle}>
          {error}
        </p>
      )}

      <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap", marginBottom: "1rem" }}>
        {editable && (
          <button type="button" data-testid="add-section" onClick={() => setShowAdd((v) => !v)} style={primary}>
            {showAdd ? "Close" : "Add section"}
          </button>
        )}
        {canActivate && (
          <button
            type="button"
            data-testid="activate-version"
            disabled={busy}
            onClick={() =>
              void act(
                () => dossierBlueprints.activateVersion(tenantSlug, versionPublicId),
                "This version cannot be activated yet — it needs at least one section and a valid structure."
              )
            }
            style={busy ? disabledPrimary : primary}
          >
            Activate
          </button>
        )}
        {canInstantiate && (
          <button
            type="button"
            data-testid="open-instantiate"
            onClick={() => setShowInstantiate((v) => !v)}
            style={primary}
          >
            {showInstantiate ? "Close" : "Create dossier from this version"}
          </button>
        )}
        {canRetire && (
          <button
            type="button"
            data-testid="retire-version"
            disabled={busy}
            onClick={() =>
              void act(
                () => dossierBlueprints.retireVersion(tenantSlug, versionPublicId),
                "This version is already retired."
              )
            }
            style={secondary}
          >
            Retire
          </button>
        )}
      </div>

      {showInstantiate && canInstantiate && (
        <InstantiateForm
          tenantSlug={tenantSlug}
          versionPublicId={versionPublicId}
          // Refresh the usage count, but do NOT close the panel: the result
          // carries the only link to the dossier that was just created, and
          // unmounting it here threw that away.
          onCreated={() => void load()}
          onError={setError}
        />
      )}

      {showAdd && editable && (
        <form
          onSubmit={addSection}
          data-testid="add-section-form"
          aria-label="Add blueprint section"
          style={{
            display: "flex",
            gap: "0.5rem",
            flexWrap: "wrap",
            alignItems: "center",
            marginBottom: "1rem",
            padding: "0.9rem",
            border: `1px solid ${T.line}`,
            borderRadius: 8,
            background: T.panel,
          }}
        >
          <label htmlFor="section-code" style={hidden}>
            Section code
          </label>
          <input
            id="section-code"
            data-testid="section-code-input"
            value={code}
            onChange={(e) => setCode(e.target.value)}
            placeholder="Code, e.g. A or A.1"
            style={{ ...field, width: 160 }}
          />
          <label htmlFor="section-title" style={hidden}>
            Section title
          </label>
          <input
            id="section-title"
            data-testid="section-title-input"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="Title"
            style={{ ...field, flex: 1, minWidth: 200 }}
          />
          <label htmlFor="section-parent" style={hidden}>
            Parent section
          </label>
          <select
            id="section-parent"
            data-testid="section-parent-select"
            value={parentId}
            onChange={(e) => setParentId(e.target.value)}
            style={{ ...field, minWidth: 160 }}
          >
            <option value="">No parent (top level)</option>
            {detail.sections.map((s) => (
              <option key={s.public_id} value={s.public_id}>
                {s.section_code} — {s.title}
              </option>
            ))}
          </select>
          <label
            style={{ display: "flex", alignItems: "center", gap: "0.35rem", fontSize: "0.85rem", color: T.text }}
          >
            <input
              type="checkbox"
              data-testid="section-required"
              checked={required}
              onChange={(e) => setRequired(e.target.checked)}
            />
            Required
          </label>
          <label htmlFor="section-offset" style={hidden}>
            Days before the target date
          </label>
          <input
            id="section-offset"
            data-testid="section-offset-input"
            value={offset}
            onChange={(e) => setOffset(e.target.value.replace(/[^0-9]/g, ""))}
            placeholder="Due offset (days)"
            title="Optional. Sets the section due date this many days before the dossier target date."
            style={{ ...field, width: 150 }}
          />
          <button
            type="submit"
            data-testid="add-section-submit"
            disabled={busy || !code.trim() || !title.trim()}
            style={busy || !code.trim() || !title.trim() ? disabledPrimary : primary}
          >
            Add
          </button>
        </form>
      )}

      <BlueprintTree
        sections={detail.sections}
        editable={editable}
        selectedPublicId={selected?.public_id ?? null}
        onSelect={setSelected}
        onReorder={editable ? move : undefined}
        onRetire={
          editable
            ? (section) =>
                void act(
                  () => dossierBlueprints.retireSection(tenantSlug, section.public_id),
                  "That section could not be removed — retire its children first."
                )
            : undefined
        }
      />
    </main>
  );
}

/**
 * The instantiate dialog.
 *
 * The case picker reuses the existing permission-scoped case list rather than
 * introducing a global case enumeration endpoint: a blueprint permission must
 * not become a way to enumerate cases.
 */
function InstantiateForm({
  tenantSlug,
  versionPublicId,
  onCreated,
  onError,
}: {
  tenantSlug: string;
  versionPublicId: string;
  onCreated: () => void;
  onError: (message: string) => void;
}) {
  const [cases, setCases] = useState<RegulatoryCase[]>([]);
  const [casePublicId, setCasePublicId] = useState("");
  const [title, setTitle] = useState("");
  const [targetDate, setTargetDate] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<{ route: string; count: number } | null>(null);

  useEffect(() => {
    regulatoryCases
      .list(tenantSlug)
      .then((r) => setCases(r.results.filter((c) => !c.is_terminal)))
      .catch(() => onError("Could not load the case list."));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tenantSlug]);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      const created = await dossierBlueprints.instantiate(tenantSlug, versionPublicId, {
        regulatory_case_public_id: casePublicId,
        title: title.trim(),
        target_date: targetDate || null,
      });
      setResult({ route: created.dossier_route, count: created.section_count });
      onCreated();
    } catch (err: unknown) {
      if (err instanceof ApiError && err.status === 400)
        onError("That case is not available to you.");
      else if (err instanceof ApiError && err.status === 409)
        onError("This version cannot be used right now.");
      else if (err instanceof ApiError && err.status === 403)
        onError("You do not have permission to create dossiers in this tenant.");
      else onError("The dossier could not be created.");
    } finally {
      setBusy(false);
    }
  }

  if (result) {
    return (
      <p
        data-testid="instantiate-result"
        style={{
          margin: "0 0 1rem",
          padding: "0.8rem",
          border: `1px solid ${T.line}`,
          borderRadius: 8,
          background: T.soft,
          fontSize: "0.9rem",
          color: T.text,
        }}
      >
        Created a dossier with {result.count} sections.{" "}
        <Link href={`${result.route}?tenant=${tenantSlug}`} data-testid="go-to-dossier">
          Open the dossier
        </Link>
      </p>
    );
  }

  return (
    <form
      onSubmit={submit}
      data-testid="instantiate-form"
      aria-label="Create dossier from blueprint version"
      style={{
        display: "flex",
        gap: "0.5rem",
        flexWrap: "wrap",
        alignItems: "center",
        marginBottom: "1rem",
        padding: "0.9rem",
        border: `1px solid ${T.line}`,
        borderRadius: 8,
        background: T.panel,
      }}
    >
      <label htmlFor="instantiate-case" style={hidden}>
        Case
      </label>
      <select
        id="instantiate-case"
        data-testid="instantiate-case"
        value={casePublicId}
        onChange={(e) => setCasePublicId(e.target.value)}
        style={{ ...field, minWidth: 220 }}
      >
        <option value="">Select a case…</option>
        {cases.map((c) => (
          <option key={c.public_id} value={c.public_id}>
            {c.case_number} — {c.title}
          </option>
        ))}
      </select>

      <label htmlFor="instantiate-title" style={hidden}>
        Dossier title
      </label>
      <input
        id="instantiate-title"
        data-testid="instantiate-title"
        value={title}
        onChange={(e) => setTitle(e.target.value)}
        placeholder="Dossier title"
        style={{ ...field, flex: 1, minWidth: 200 }}
      />

      <label htmlFor="instantiate-target" style={hidden}>
        Target date
      </label>
      <input
        id="instantiate-target"
        data-testid="instantiate-target"
        type="date"
        value={targetDate}
        onChange={(e) => setTargetDate(e.target.value)}
        title="Optional. Section due dates are derived from this using each section's offset."
        style={{ ...field, width: 170 }}
      />

      <button
        type="submit"
        data-testid="instantiate-submit"
        disabled={busy || !casePublicId || !title.trim()}
        style={busy || !casePublicId || !title.trim() ? disabledPrimary : primary}
      >
        Create dossier
      </button>
    </form>
  );
}

const page: React.CSSProperties = { padding: "1.5rem", maxWidth: 1000, margin: "0 auto" };
const hidden: React.CSSProperties = { position: "absolute", left: -9999 };

const field: React.CSSProperties = {
  padding: "0.45rem 0.6rem",
  border: `1px solid ${T.line}`,
  borderRadius: 6,
  background: "#fff",
  color: T.text,
  fontSize: "0.88rem",
};

const primary: React.CSSProperties = {
  padding: "0.45rem 0.9rem",
  border: `1px solid ${T.navy}`,
  borderRadius: 8,
  background: T.blue,
  color: "#fff",
  fontWeight: 600,
  cursor: "pointer",
  whiteSpace: "nowrap",
};

const disabledPrimary: React.CSSProperties = {
  ...primary,
  border: `1px solid ${T.line}`,
  background: T.soft,
  color: T.muted,
  cursor: "not-allowed",
};

const secondary: React.CSSProperties = {
  padding: "0.45rem 0.9rem",
  border: `1px solid ${T.line}`,
  borderRadius: 8,
  background: "#fff",
  color: T.blue,
  fontWeight: 600,
  cursor: "pointer",
  whiteSpace: "nowrap",
};

const alertStyle: React.CSSProperties = {
  margin: "0 0 0.9rem",
  padding: "0.6rem 0.8rem",
  border: "1px solid #f3c9c4",
  borderRadius: 6,
  background: "#fdf3f2",
  color: "#8f2c20",
  fontSize: "0.88rem",
};

export default function BlueprintVersionPage() {
  return (
    <Suspense fallback={null}>
      <VersionDetailInner />
    </Suspense>
  );
}
