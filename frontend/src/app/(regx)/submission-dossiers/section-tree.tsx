"use client";

import { useMemo, useState } from "react";
import type { DossierSection, Readiness, SectionStatus } from "@/lib/api";
import { buildTreeRows } from "@/lib/tree";
import { BlockerIndicator, ReadinessBadge, SectionStatusBadge } from "./readiness-badge";

const T = {
  ink: "#001f45",
  text: "#314155",
  muted: "#66768b",
  line: "#dce7f4",
  soft: "#eaf2fd",
  panel: "#f4f8fe",
  blue: "#045e8f",
} as const;

/**
 * The outline.
 *
 * **Rendered as a flat list with indentation, not nested DOM.** A dossier can
 * hold 500 sections; nesting them produces 500-deep containers that are slow to
 * lay out and impossible to virtualise later. The server sends a flat array
 * with `parent_public_id`, this builds the order once, and each row is a
 * sibling in the DOM with `paddingLeft` carrying the depth.
 *
 * Collapsing therefore hides descendants by filtering the visible list rather
 * than unmounting a subtree, which keeps the cost proportional to what is on
 * screen.
 */
export interface TreeRow {
  section: DossierSection;
  depth: number;
  hasChildren: boolean;
}

/**
 * Kept as the dossier-facing name and signature; the algorithm now lives in
 * `@/lib/tree` so the blueprint library reuses it instead of growing a second
 * copy. Milestone 10 extracted it rather than duplicating the tree.
 */
export function buildRows(
  sections: DossierSection[],
  collapsed: Set<string>
): TreeRow[] {
  return buildTreeRows(sections, collapsed);
}

export function SectionTree({
  sections,
  blockerCounts = {},
  selectedPublicId,
  onSelect,
}: {
  sections: DossierSection[];
  blockerCounts?: Record<string, number>;
  selectedPublicId?: string | null;
  onSelect?: (section: DossierSection) => void;
}) {
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<"" | SectionStatus>("");
  const [readinessFilter, setReadinessFilter] = useState<"" | Readiness>("");

  const filtered = useMemo(() => {
    const term = search.trim().toLowerCase();
    return sections.filter((s) => {
      if (statusFilter && s.status !== statusFilter) return false;
      if (readinessFilter && s.readiness !== readinessFilter) return false;
      if (!term) return true;
      return (
        s.section_code.toLowerCase().includes(term) || s.title.toLowerCase().includes(term)
      );
    });
  }, [sections, search, statusFilter, readinessFilter]);

  // When a filter is active the tree is shown flat: hiding a parent while
  // keeping its child indented under nothing would misrepresent the hierarchy.
  const isFiltering = Boolean(search.trim() || statusFilter || readinessFilter);
  const rows = useMemo(
    () =>
      isFiltering
        ? filtered.map((section) => ({ section, depth: 0, hasChildren: false }))
        : buildRows(sections, collapsed),
    [isFiltering, filtered, sections, collapsed]
  );

  function toggle(publicId: string) {
    setCollapsed((prev) => {
      const next = new Set(prev);
      if (next.has(publicId)) next.delete(publicId);
      else next.add(publicId);
      return next;
    });
  }

  if (sections.length === 0) {
    return (
      <p
        data-testid="sections-empty"
        style={{
          margin: 0,
          padding: "1.5rem 1rem",
          border: `1px solid ${T.line}`,
          borderRadius: 8,
          background: T.panel,
          color: T.muted,
          fontSize: "0.9rem",
        }}
      >
        No sections yet. Add one to start building the outline.
      </p>
    );
  }

  return (
    <div>
      <div
        style={{
          display: "flex",
          gap: "0.5rem",
          flexWrap: "wrap",
          marginBottom: "0.75rem",
          alignItems: "center",
        }}
      >
        <label htmlFor="section-search" style={{ position: "absolute", left: -9999 }}>
          Search sections by code or title
        </label>
        <input
          id="section-search"
          data-testid="section-search"
          type="search"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search code or title"
          style={{
            padding: "0.4rem 0.6rem",
            border: `1px solid ${T.line}`,
            borderRadius: 6,
            fontSize: "0.85rem",
            minWidth: 200,
          }}
        />
        <label style={{ fontSize: "0.8rem", color: T.muted }}>
          Status{" "}
          <select
            data-testid="section-status-filter"
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value as "" | SectionStatus)}
            style={{ padding: "0.35rem", border: `1px solid ${T.line}`, borderRadius: 6 }}
          >
            <option value="">All</option>
            <option value="not_started">Not started</option>
            <option value="in_progress">In progress</option>
            <option value="blocked">Blocked</option>
            <option value="complete">Complete</option>
            <option value="not_applicable">Not applicable</option>
          </select>
        </label>
        <label style={{ fontSize: "0.8rem", color: T.muted }}>
          Readiness{" "}
          <select
            data-testid="section-readiness-filter"
            value={readinessFilter}
            onChange={(e) => setReadinessFilter(e.target.value as "" | Readiness)}
            style={{ padding: "0.35rem", border: `1px solid ${T.line}`, borderRadius: 6 }}
          >
            <option value="">All</option>
            <option value="ready">Ready</option>
            <option value="partially_ready">Partially ready</option>
            <option value="not_ready">Not ready</option>
            <option value="not_applicable">Not applicable</option>
          </select>
        </label>
      </div>

      {rows.length === 0 && (
        <p data-testid="sections-no-match" style={{ color: T.muted, fontSize: "0.9rem" }}>
          No sections match those filters.
        </p>
      )}

      <ul
        data-testid="section-tree"
        role="tree"
        aria-label="Dossier sections"
        style={{ listStyle: "none", margin: 0, padding: 0 }}
      >
        {rows.map(({ section, depth, hasChildren }) => {
          const selected = selectedPublicId === section.public_id;
          const isCollapsed = collapsed.has(section.public_id);
          return (
            <li
              key={section.public_id}
              role="treeitem"
              aria-level={depth + 1}
              aria-expanded={hasChildren ? !isCollapsed : undefined}
              aria-selected={selected}
              data-testid="section-row"
              data-section-code={section.section_code}
              style={{
                display: "flex",
                alignItems: "center",
                gap: "0.5rem",
                // Depth via padding, not nesting -- see the note at the top.
                paddingLeft: `${depth * 1.25 + 0.5}rem`,
                paddingRight: "0.5rem",
                paddingTop: "0.45rem",
                paddingBottom: "0.45rem",
                borderBottom: `1px solid ${T.line}`,
                background: selected ? T.soft : "transparent",
              }}
            >
              {hasChildren ? (
                <button
                  type="button"
                  data-testid={`toggle-${section.public_id}`}
                  aria-label={`${isCollapsed ? "Expand" : "Collapse"} ${section.section_code}`}
                  onClick={() => toggle(section.public_id)}
                  style={{
                    width: 20,
                    height: 20,
                    border: `1px solid ${T.line}`,
                    borderRadius: 4,
                    background: "#fff",
                    color: T.muted,
                    cursor: "pointer",
                    fontSize: "0.7rem",
                    lineHeight: 1,
                  }}
                >
                  {isCollapsed ? "+" : "−"}
                </button>
              ) : (
                <span style={{ width: 20 }} aria-hidden="true" />
              )}

              <button
                type="button"
                data-testid={`select-${section.public_id}`}
                onClick={() => onSelect?.(section)}
                style={{
                  flex: 1,
                  display: "flex",
                  alignItems: "center",
                  gap: "0.6rem",
                  border: "none",
                  background: "none",
                  padding: 0,
                  textAlign: "left",
                  cursor: onSelect ? "pointer" : "default",
                  minWidth: 0,
                }}
              >
                <span
                  style={{
                    fontWeight: 700,
                    fontSize: "0.82rem",
                    color: T.blue,
                    whiteSpace: "nowrap",
                  }}
                >
                  {section.section_code}
                </span>
                <span
                  style={{
                    fontSize: "0.88rem",
                    color: T.ink,
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                    whiteSpace: "nowrap",
                  }}
                >
                  {section.title}
                </span>
                {!section.required && (
                  <span style={{ fontSize: "0.75rem", color: T.muted }}>optional</span>
                )}
              </button>

              <BlockerIndicator count={blockerCounts[section.public_id] ?? 0} />
              <SectionStatusBadge status={section.status} />
              <ReadinessBadge readiness={section.readiness} />

              <span
                style={{
                  fontSize: "0.78rem",
                  color: T.muted,
                  minWidth: 90,
                  textAlign: "right",
                }}
              >
                {section.owner ? section.owner.full_name : "—"}
              </span>
              <span
                style={{
                  fontSize: "0.78rem",
                  color: section.due_date ? T.text : T.muted,
                  minWidth: 90,
                  textAlign: "right",
                }}
              >
                {section.due_date ? new Date(section.due_date).toLocaleDateString() : "—"}
              </span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
