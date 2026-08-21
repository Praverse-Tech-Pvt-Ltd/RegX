"use client";

import { Suspense, useEffect, useState } from "react";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import {
  templates,
  type RegulatoryTemplate,
  type TemplateVersion,
  type TemplateSection,
  type TemplateItem,
  type TemplateLifecycleStatus,
  ApiError,
} from "@/lib/api";

const STATUS_COLOURS: Record<TemplateLifecycleStatus, string> = {
  draft: "#314155",
  imported: "#045e8f",
  under_review: "#8a5a10",
  returned: "#8a5a10",
  approved: "#0e6b6b",
  active: "#1a6b46",
  superseded: "#66768b",
  retired: "#66768b",
  rejected: "#8f2c20",
};

function StatusBadge({ status }: { status: TemplateLifecycleStatus }) {
  return (
    <span
      style={{
        fontSize: 11,
        fontWeight: 600,
        padding: "2px 7px",
        borderRadius: 4,
        background: STATUS_COLOURS[status] ?? "#314155",
        color: "#fff",
        textTransform: "uppercase",
        letterSpacing: "0.03em",
      }}
    >
      {status.replace(/_/g, " ")}
    </span>
  );
}

function VersionPreview({
  tenantSlug,
  templateId,
  version,
}: {
  tenantSlug: string;
  templateId: string;
  version: TemplateVersion;
}) {
  const [open, setOpen] = useState(false);
  const [sections, setSections] = useState<TemplateSection[]>([]);
  const [items, setItems] = useState<TemplateItem[]>([]);
  const [loadingPreview, setLoadingPreview] = useState(false);

  function toggle() {
    if (open) {
      setOpen(false);
      return;
    }
    setLoadingPreview(true);
    Promise.all([
      templates.sections(tenantSlug, templateId, version.public_id),
      templates.items(tenantSlug, templateId, version.public_id),
    ])
      .then(([sectionsResp, itemsResp]) => {
        setSections(sectionsResp.results);
        setItems(itemsResp.results);
        setOpen(true);
      })
      .finally(() => setLoadingPreview(false));
  }

  return (
    <div>
      <button
        onClick={toggle}
        style={{
          fontSize: 12,
          padding: "4px 10px",
          borderRadius: 4,
          border: "1px solid #dce7f4",
          cursor: "pointer",
          background: "#f8fbff",
        }}
      >
        {loadingPreview ? "Loading…" : open ? "Hide section/item preview" : "Show section/item preview"}
      </button>
      {open && (
        <div style={{ marginTop: 8, fontSize: 13 }}>
          {sections.length === 0 && <p style={{ color: "#66768b" }}>No sections.</p>}
          {sections.map((section) => {
            const sectionItems = items.filter((it) => it.template_section === section.public_id);
            return (
              <div key={section.public_id} style={{ marginBottom: 12 }}>
                <div style={{ fontWeight: 600, color: "#314155" }}>
                  {section.canonical_section_code} — {section.normalized_title}
                </div>
                {sectionItems.length === 0 ? (
                  <p style={{ color: "#9fb0c4", marginTop: 4, marginLeft: 20 }}>No items.</p>
                ) : (
                  <ul style={{ marginTop: 4, paddingLeft: 20 }}>
                    {sectionItems.map((item) => (
                      <li key={item.public_id} style={{ marginBottom: 4 }}>
                        <span style={{ color: "#66768b", fontFamily: "monospace", fontSize: 12 }}>
                          {item.canonical_item_code}
                        </span>{" "}
                        {item.normalized_text}
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

function VersionRow({
  tenantSlug,
  templateId,
  version,
  onChanged,
}: {
  tenantSlug: string;
  templateId: string;
  version: TemplateVersion;
  onChanged: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  async function run(action: () => Promise<unknown>) {
    setBusy(true);
    setActionError(null);
    try {
      await action();
      onChanged();
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : "Action failed.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div style={{ border: "1px solid #dce7f4", borderRadius: 8, padding: "1rem", marginBottom: "0.75rem" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <div>
          <span style={{ fontWeight: 600 }}>Version {version.version_number}</span>{" "}
          <StatusBadge status={version.status} />
        </div>
        <div style={{ display: "flex", gap: 6 }}>
          {(version.status === "draft" || version.status === "imported" || version.status === "returned") && (
            <button
              disabled={busy}
              onClick={() => run(() => templates.submitReview(tenantSlug, templateId, version.public_id))}
              style={actionBtnStyle}
            >
              Submit for review
            </button>
          )}
          {version.status === "under_review" && (
            <>
              <button
                disabled={busy}
                onClick={() => run(() => templates.approve(tenantSlug, templateId, version.public_id))}
                style={actionBtnStyle}
              >
                Approve
              </button>
              <button
                disabled={busy}
                onClick={() =>
                  run(() => templates.returnForCorrection(tenantSlug, templateId, version.public_id))
                }
                style={actionBtnStyle}
              >
                Return
              </button>
              <button
                disabled={busy}
                onClick={() => run(() => templates.reject(tenantSlug, templateId, version.public_id))}
                style={actionBtnStyle}
              >
                Reject
              </button>
            </>
          )}
          {version.status === "approved" && (
            <button
              disabled={busy}
              onClick={() => run(() => templates.activate(tenantSlug, templateId, version.public_id))}
              style={actionBtnStyle}
            >
              Activate
            </button>
          )}
          {version.status === "active" && (
            <>
              <button
                disabled={busy}
                onClick={() => run(() => templates.supersede(tenantSlug, templateId, version.public_id))}
                style={actionBtnStyle}
              >
                Supersede
              </button>
              <button
                disabled={busy}
                onClick={() => run(() => templates.retire(tenantSlug, templateId, version.public_id))}
                style={actionBtnStyle}
              >
                Retire
              </button>
            </>
          )}
          {version.status === "superseded" && (
            <button
              disabled={busy}
              onClick={() => run(() => templates.retire(tenantSlug, templateId, version.public_id))}
              style={actionBtnStyle}
            >
              Retire
            </button>
          )}
        </div>
      </div>
      {actionError && <p role="alert" style={{ color: "#c0392b", fontSize: 13, marginTop: 6 }}>{actionError}</p>}
      <div style={{ marginTop: "0.75rem" }}>
        <VersionPreview tenantSlug={tenantSlug} templateId={templateId} version={version} />
      </div>
    </div>
  );
}

const actionBtnStyle: React.CSSProperties = {
  fontSize: 12,
  padding: "5px 10px",
  borderRadius: 4,
  border: "1px solid #dce7f4",
  cursor: "pointer",
  background: "#fff",
};

function TemplateDetailPageInner() {
  const { publicId } = useParams<{ publicId: string }>();
  const searchParams = useSearchParams();
  const tenantSlug = searchParams.get("tenant") ?? "";
  const router = useRouter();

  const [template, setTemplate] = useState<RegulatoryTemplate | null>(null);
  const [versions, setVersions] = useState<TemplateVersion[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    if (!tenantSlug) return;
    try {
      const [templateData, versionsData] = await Promise.all([
        templates.get(tenantSlug, publicId),
        templates.versions(tenantSlug, publicId),
      ]);
      setTemplate(templateData);
      setVersions(versionsData.results);
    } catch (err) {
      if (err instanceof ApiError && err.status === 403) {
        router.push(`/signin?next=${encodeURIComponent(window.location.pathname + window.location.search)}`);
      } else {
        setError("Failed to load template.");
      }
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    if (!tenantSlug) {
      router.push("/tenants");
      return;
    }
    load();
  }, [tenantSlug, publicId]); // eslint-disable-line react-hooks/exhaustive-deps

  if (loading) return <main style={{ maxWidth: 900, margin: "2rem auto", padding: "0 1rem" }}><p>Loading…</p></main>;
  if (error) return <main style={{ maxWidth: 900, margin: "2rem auto", padding: "0 1rem" }}><p role="alert" style={{ color: "#c0392b" }}>{error}</p></main>;
  if (!template) return null;

  return (
    <main style={{ maxWidth: 900, margin: "2rem auto", padding: "0 1rem" }}>
      <div style={{ marginBottom: "0.5rem" }}>
        <Link href={`/templates?tenant=${tenantSlug}`} style={{ color: "#045e8f", fontSize: 13, textDecoration: "none" }}>
          ← All templates
        </Link>
      </div>

      <div style={{ marginBottom: "1.5rem" }}>
        <h1 style={{ margin: "0 0 4px" }}>{template.title}</h1>
        <span style={{ fontSize: 12, color: "#66768b", fontFamily: "monospace" }}>{template.canonical_code}</span>{" "}
        <StatusBadge status={template.lifecycle_status} />
        {template.description && <p style={{ color: "#314155", marginTop: 8 }}>{template.description}</p>}
      </div>

      <section>
        <h2 style={{ fontSize: 16, marginBottom: "0.75rem" }}>Versions ({versions.length})</h2>
        {versions.length === 0 && <p style={{ color: "#66768b" }}>No versions found.</p>}
        {versions.map((v) => (
          <VersionRow key={v.public_id} tenantSlug={tenantSlug} templateId={publicId} version={v} onChanged={load} />
        ))}
      </section>
    </main>
  );
}

export default function TemplateDetailPage() {
  return (
    <Suspense>
      <TemplateDetailPageInner />
    </Suspense>
  );
}
