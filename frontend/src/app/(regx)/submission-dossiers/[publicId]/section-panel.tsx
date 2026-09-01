"use client";

import { useEffect, useState, type FormEvent } from "react";
import {
  submissionDossiers,
  ApiError,
  type DossierPermissions,
  type DossierSection,
  type SectionDetail,
} from "@/lib/api";
import { ReadinessBadge, SectionStatusBadge } from "../readiness-badge";

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

const TABS = ["overview", "documents", "workflows", "checklists", "blockers"] as const;
type Tab = (typeof TABS)[number];

const TAB_LABELS: Record<Tab, string> = {
  overview: "Overview",
  documents: "Documents",
  workflows: "Workflow",
  checklists: "Checklists",
  blockers: "Blockers",
};

const field: React.CSSProperties = {
  padding: "0.4rem 0.55rem",
  border: `1px solid ${T.line}`,
  borderRadius: 6,
  background: "#fff",
  color: T.text,
  fontSize: "0.85rem",
};

function ghost(disabled: boolean): React.CSSProperties {
  return {
    padding: "0.3rem 0.7rem",
    border: `1px solid ${T.line}`,
    borderRadius: 6,
    background: "#fff",
    color: T.blue,
    fontSize: "0.8rem",
    fontWeight: 600,
    cursor: disabled ? "not-allowed" : "pointer",
    opacity: disabled ? 0.5 : 1,
  };
}

/** A linked resource the caller may see exists but not identify. */
function Restricted() {
  return (
    <span data-testid="link-restricted" title="Requires permission for that module">
      <em style={{ color: T.muted }}>Linked resource — access restricted</em>
    </span>
  );
}

export function SectionPanel({
  tenantSlug,
  section,
  permissions,
  dossierTerminal,
  onChanged,
}: {
  tenantSlug: string;
  section: DossierSection | null;
  permissions: DossierPermissions;
  dossierTerminal: boolean;
  onChanged: () => void;
}) {
  const [detail, setDetail] = useState<SectionDetail | null>(null);
  const [tab, setTab] = useState<Tab>("overview");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [linkId, setLinkId] = useState("");
  const [blockerTitle, setBlockerTitle] = useState("");

  function load(): Promise<void> {
    if (!section) return Promise.resolve();
    return submissionDossiers
      .getSection(tenantSlug, section.public_id)
      .then((d) => {
        setDetail(d);
        setError(null);
      })
      .catch(() => setError("Failed to load this section."));
  }

  useEffect(() => {
    setDetail(null);
    void load();
  }, [section?.public_id]); // eslint-disable-line react-hooks/exhaustive-deps

  async function run(fn: () => Promise<unknown>, conflictMessage: string) {
    setBusy(true);
    try {
      await fn();
      await load();
      onChanged();
    } catch (err: unknown) {
      // Reload first, then set the message -- load() clears it on success.
      await load();
      if (err instanceof ApiError && err.status === 409) setError(conflictMessage);
      else if (err instanceof ApiError && err.status === 403)
        setError("You do not have permission to do that.");
      else if (err instanceof ApiError && err.status === 400)
        setError("That item is not available to link to this section.");
      else setError("The action could not be completed.");
    } finally {
      setBusy(false);
    }
  }

  if (!section) {
    return (
      <aside
        data-testid="section-panel-empty"
        style={{
          padding: "1.5rem 1rem",
          border: `1px solid ${T.line}`,
          borderRadius: 8,
          background: T.panel,
          color: T.muted,
          fontSize: "0.9rem",
          alignSelf: "start",
        }}
      >
        Select a section to see its documents, workflow items, checklists and blockers.
      </aside>
    );
  }

  const canLink = permissions.can_manage_links && !dossierTerminal;
  const canBlock = permissions.can_manage_blockers && !dossierTerminal;
  const canEdit = permissions.can_manage_sections && !dossierTerminal;
  const linkKind: "documents" | "workflows" | "checklists" =
    tab === "workflows" ? "workflows" : tab === "checklists" ? "checklists" : "documents";

  return (
    <aside
      data-testid="section-panel"
      style={{
        border: `1px solid ${T.line}`,
        borderRadius: 8,
        background: "#fff",
        padding: "1rem",
        alignSelf: "start",
      }}
    >
      <div style={{ display: "flex", gap: "0.5rem", alignItems: "center", flexWrap: "wrap" }}>
        <span style={{ fontWeight: 700, color: T.blue, fontSize: "0.85rem" }}>
          {section.section_code}
        </span>
        <h2 style={{ margin: 0, fontSize: "1.05rem", fontWeight: 700, color: T.ink }}>
          {section.title}
        </h2>
      </div>

      <div style={{ display: "flex", gap: "0.4rem", margin: "0.6rem 0", flexWrap: "wrap" }}>
        <SectionStatusBadge status={section.status} />
        <ReadinessBadge readiness={section.readiness} />
        {!section.required && (
          <span style={{ fontSize: "0.78rem", color: T.muted, alignSelf: "center" }}>optional</span>
        )}
      </div>

      {canEdit && (
        <div style={{ display: "flex", gap: "0.4rem", flexWrap: "wrap", marginBottom: "0.75rem" }}>
          {section.status !== "complete" && (
            <button
              type="button"
              data-testid="mark-complete"
              disabled={busy}
              onClick={() =>
                void run(
                  () =>
                    submissionDossiers.updateSection(tenantSlug, section.public_id, {
                      status: "complete",
                    }),
                  "This dossier no longer accepts changes."
                )
              }
              style={ghost(busy)}
            >
              Mark complete
            </button>
          )}
          {section.status !== "not_applicable" && (
            <button
              type="button"
              data-testid="mark-na"
              disabled={busy}
              onClick={() =>
                void run(
                  () =>
                    submissionDossiers.updateSection(tenantSlug, section.public_id, {
                      status: "not_applicable",
                    }),
                  "This dossier no longer accepts changes."
                )
              }
              style={ghost(busy)}
            >
              Mark N/A
            </button>
          )}
        </div>
      )}

      {error && (
        <p
          role="alert"
          data-testid="section-error"
          style={{
            margin: "0 0 0.75rem",
            padding: "0.5rem 0.7rem",
            border: "1px solid #f3c9c4",
            borderRadius: 6,
            background: "#fdf3f2",
            color: "#8f2c20",
            fontSize: "0.84rem",
          }}
        >
          {error}
        </p>
      )}

      <nav
        role="tablist"
        aria-label="Section detail"
        style={{
          display: "flex",
          gap: "0.2rem",
          borderBottom: `1px solid ${T.line}`,
          marginBottom: "0.75rem",
          flexWrap: "wrap",
        }}
      >
        {TABS.map((t) => (
          <button
            key={t}
            role="tab"
            aria-selected={tab === t}
            data-testid={`section-tab-${t}`}
            onClick={() => setTab(t)}
            style={{
              padding: "0.4rem 0.7rem",
              border: "none",
              borderBottom: tab === t ? `2px solid ${T.blue}` : "2px solid transparent",
              background: "none",
              color: tab === t ? T.ink : T.muted,
              fontWeight: 600,
              fontSize: "0.84rem",
              cursor: "pointer",
            }}
          >
            {TAB_LABELS[t]}
          </button>
        ))}
      </nav>

      {!detail && <p style={{ color: T.muted, fontSize: "0.85rem" }}>Loading…</p>}

      {detail && tab === "overview" && (
        <div data-testid="section-tab-panel-overview" style={{ fontSize: "0.85rem", color: T.text }}>
          <p style={{ margin: "0 0 0.5rem", color: T.muted }}>
            Owner: {section.owner ? section.owner.full_name : "—"} · Due:{" "}
            {section.due_date ? new Date(section.due_date).toLocaleDateString() : "—"}
          </p>
          {section.description ? (
            <p style={{ lineHeight: 1.6 }}>{section.description}</p>
          ) : (
            <p style={{ color: T.muted }}>No description.</p>
          )}
          {detail.children.length > 0 && (
            <p style={{ color: T.muted }}>
              {detail.children.length} child section{detail.children.length === 1 ? "" : "s"}.
            </p>
          )}
        </div>
      )}

      {detail && (tab === "documents" || tab === "workflows" || tab === "checklists") && (
        <div data-testid={`section-tab-panel-${tab}`}>
          {canLink && (
            <form
              onSubmit={(e: FormEvent) => {
                e.preventDefault();
                const id = linkId.trim();
                if (!id) return;
                void run(
                  () =>
                    submissionDossiers.linkTarget(tenantSlug, section.public_id, linkKind, id),
                  "Already linked, or this dossier no longer accepts changes."
                );
                setLinkId("");
              }}
              data-testid="section-link-form"
              aria-label="Link resource form"
              style={{ display: "flex", gap: "0.4rem", marginBottom: "0.75rem", flexWrap: "wrap" }}
            >
              <label htmlFor="section-link-target" style={{ position: "absolute", left: -9999 }}>
                Target public ID
              </label>
              <input
                id="section-link-target"
                data-testid="section-link-input"
                value={linkId}
                onChange={(e) => setLinkId(e.target.value)}
                placeholder={`${TAB_LABELS[tab]} public ID (UUID)`}
                style={{ ...field, flex: 1, minWidth: 200 }}
              />
              <button
                type="submit"
                data-testid="section-link-submit"
                disabled={busy || !linkId.trim()}
                style={ghost(busy || !linkId.trim())}
              >
                Link
              </button>
            </form>
          )}

          <LinkList
            tab={tab}
            detail={detail}
            canLink={canLink}
            busy={busy}
            onUnlink={(id) =>
              void run(
                () =>
                  submissionDossiers.unlinkTarget(tenantSlug, section.public_id, linkKind, id),
                "This dossier no longer accepts changes."
              )
            }
          />
        </div>
      )}

      {detail && tab === "blockers" && (
        <div data-testid="section-tab-panel-blockers">
          {canBlock && (
            <form
              onSubmit={(e: FormEvent) => {
                e.preventDefault();
                const title = blockerTitle.trim();
                if (!title) return;
                void run(
                  () =>
                    submissionDossiers.createBlocker(tenantSlug, section.public_id, { title }),
                  "This dossier no longer accepts changes."
                );
                setBlockerTitle("");
              }}
              data-testid="blocker-form"
              aria-label="Add blocker form"
              style={{ display: "flex", gap: "0.4rem", marginBottom: "0.75rem", flexWrap: "wrap" }}
            >
              <label htmlFor="blocker-title" style={{ position: "absolute", left: -9999 }}>
                Blocker title
              </label>
              <input
                id="blocker-title"
                data-testid="blocker-title-input"
                value={blockerTitle}
                onChange={(e) => setBlockerTitle(e.target.value)}
                placeholder="What is blocking this section?"
                style={{ ...field, flex: 1, minWidth: 200 }}
              />
              <button
                type="submit"
                data-testid="blocker-submit"
                disabled={busy || !blockerTitle.trim()}
                style={ghost(busy || !blockerTitle.trim())}
              >
                Add blocker
              </button>
            </form>
          )}

          {detail.blockers.length === 0 ? (
            <p data-testid="blockers-empty" style={{ color: T.muted, fontSize: "0.85rem" }}>
              No blockers recorded.
            </p>
          ) : (
            <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
              {detail.blockers.map((b) => (
                <li
                  key={b.public_id}
                  data-testid="blocker-row"
                  data-status={b.status}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: "0.5rem",
                    padding: "0.5rem 0",
                    borderBottom: `1px solid ${T.line}`,
                    fontSize: "0.85rem",
                  }}
                >
                  <span style={{ flex: 1, color: b.status === "open" ? T.ink : T.muted }}>
                    {b.title}
                  </span>
                  <span style={{ fontSize: "0.75rem", color: T.muted }}>{b.severity}</span>
                  <span style={{ fontSize: "0.75rem", color: T.muted }}>{b.status}</span>
                  {canBlock && b.status === "open" && (
                    <button
                      type="button"
                      data-testid={`resolve-${b.public_id}`}
                      disabled={busy}
                      onClick={() =>
                        void run(
                          () => submissionDossiers.resolveBlocker(tenantSlug, b.public_id),
                          "That blocker is already resolved."
                        )
                      }
                      style={ghost(busy)}
                    >
                      Resolve
                    </button>
                  )}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </aside>
  );
}

function LinkList({
  tab,
  detail,
  canLink,
  busy,
  onUnlink,
}: {
  tab: "documents" | "workflows" | "checklists";
  detail: SectionDetail;
  canLink: boolean;
  busy: boolean;
  onUnlink: (linkPublicId: string) => void;
}) {
  const rows =
    tab === "documents"
      ? detail.documents
      : tab === "workflows"
        ? detail.workflows
        : detail.checklists;

  if (rows.length === 0) {
    return (
      <p data-testid={`section-${tab}-empty`} style={{ color: "#66768b", fontSize: "0.85rem" }}>
        Nothing linked yet.
      </p>
    );
  }

  return (
    <ul data-testid={`section-${tab}-list`} style={{ listStyle: "none", margin: 0, padding: 0 }}>
      {rows.map((row) => (
        <li
          key={row.public_id}
          style={{
            display: "flex",
            alignItems: "center",
            gap: "0.5rem",
            padding: "0.5rem 0",
            borderBottom: "1px solid #dce7f4",
            fontSize: "0.85rem",
          }}
        >
          <span style={{ flex: 1, minWidth: 0 }}>
            {"document" in row && row.document ? (
              row.document.title
            ) : "workflow" in row && row.workflow ? (
              row.workflow.title
            ) : "checklist" in row && row.checklist ? (
              row.checklist.status
            ) : (
              <Restricted />
            )}
          </span>
          {canLink && (
            <button
              type="button"
              data-testid={`unlink-${row.public_id}`}
              disabled={busy}
              onClick={() => onUnlink(row.public_id)}
              style={ghost(busy)}
            >
              Unlink
            </button>
          )}
        </li>
      ))}
    </ul>
  );
}
