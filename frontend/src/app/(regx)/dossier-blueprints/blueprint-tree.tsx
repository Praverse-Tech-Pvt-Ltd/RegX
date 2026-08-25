"use client";

import { useMemo, useState } from "react";
import type { BlueprintSection } from "@/lib/api";
import { buildTreeRows } from "@/lib/tree";
import { RequiredBadge } from "./status-badge";

/**
 * The blueprint outline.
 *
 * Reuses `buildTreeRows` -- the same flattening the Milestone 9 dossier tree
 * uses, extracted rather than copied. The presentation is separate on purpose:
 * a dossier row shows readiness and blockers, a blueprint row shows
 * required/optional and draft editing controls, and one component doing both
 * would serve neither well.
 *
 * Flat DOM with `paddingLeft` for depth, never nested containers: a version can
 * hold hundreds of sections, and collapsing filters the visible list rather
 * than unmounting a subtree.
 */

const T = {
  ink: "#001f45",
  text: "#314155",
  muted: "#66768b",
  line: "#dce7f4",
  soft: "#eaf2fd",
  panel: "#f4f8fe",
  blue: "#045e8f",
} as const;

export function BlueprintTree({
  sections,
  editable,
  selectedPublicId,
  onSelect,
  onReorder,
  onRetire,
}: {
  sections: BlueprintSection[];
  editable: boolean;
  selectedPublicId?: string | null;
  onSelect?: (section: BlueprintSection) => void;
  onReorder?: (section: BlueprintSection, direction: -1 | 1) => void;
  onRetire?: (section: BlueprintSection) => void;
}) {
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());
  const [search, setSearch] = useState("");

  const filtered = useMemo(() => {
    const term = search.trim().toLowerCase();
    if (!term) return sections;
    return sections.filter(
      (s) =>
        s.section_code.toLowerCase().includes(term) || s.title.toLowerCase().includes(term)
    );
  }, [sections, search]);

  // While filtering the list is shown flat: indenting a child under a parent
  // that the filter removed would misrepresent the hierarchy.
  const isFiltering = Boolean(search.trim());
  const rows = useMemo(
    () =>
      isFiltering
        ? filtered.map((section) => ({ section, depth: 0, hasChildren: false }))
        : buildTreeRows(sections, collapsed),
    [isFiltering, filtered, sections, collapsed]
  );

  const toggle = (publicId: string) =>
    setCollapsed((prev) => {
      const next = new Set(prev);
      if (next.has(publicId)) next.delete(publicId);
      else next.add(publicId);
      return next;
    });

  return (
    <div data-testid="blueprint-tree">
      <div style={{ marginBottom: "0.75rem" }}>
        <label htmlFor="blueprint-tree-search" style={{ position: "absolute", left: -9999 }}>
          Search sections
        </label>
        <input
          id="blueprint-tree-search"
          data-testid="blueprint-tree-search"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search by code or title"
          style={{
            width: "100%",
            maxWidth: 360,
            padding: "0.45rem 0.6rem",
            border: `1px solid ${T.line}`,
            borderRadius: 6,
            background: "#fff",
            color: T.text,
            fontSize: "0.88rem",
          }}
        />
      </div>

      {rows.length === 0 && (
        <p
          data-testid="blueprint-tree-empty"
          style={{
            margin: 0,
            padding: "1.25rem 1rem",
            border: `1px solid ${T.line}`,
            borderRadius: 8,
            background: T.panel,
            color: T.muted,
            fontSize: "0.9rem",
          }}
        >
          {isFiltering ? "No sections match that search." : "No sections yet."}
        </p>
      )}

      {rows.length > 0 && (
        <ul
          role="tree"
          aria-label="Blueprint sections"
          data-testid="blueprint-tree-list"
          style={{ listStyle: "none", margin: 0, padding: 0 }}
        >
          {rows.map(({ section, depth, hasChildren }) => {
            const isSelected = section.public_id === selectedPublicId;
            return (
              <li
                key={section.public_id}
                role="treeitem"
                aria-level={depth + 1}
                aria-selected={isSelected}
                aria-expanded={hasChildren ? !collapsed.has(section.public_id) : undefined}
                data-testid="blueprint-tree-row"
                data-section-code={section.section_code}
                data-depth={depth}
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: "0.5rem",
                  // Indentation, not nesting: depth is a style, not a container.
                  paddingLeft: `${depth * 1.25 + 0.5}rem`,
                  paddingRight: "0.5rem",
                  paddingTop: "0.4rem",
                  paddingBottom: "0.4rem",
                  borderBottom: `1px solid ${T.line}`,
                  background: isSelected ? T.soft : "transparent",
                }}
              >
                {hasChildren ? (
                  <button
                    type="button"
                    onClick={() => toggle(section.public_id)}
                    aria-label={`${collapsed.has(section.public_id) ? "Expand" : "Collapse"} ${section.section_code}`}
                    style={{
                      width: 20,
                      height: 20,
                      border: `1px solid ${T.line}`,
                      borderRadius: 4,
                      background: "#fff",
                      color: T.text,
                      cursor: "pointer",
                      lineHeight: 1,
                    }}
                  >
                    {collapsed.has(section.public_id) ? "+" : "−"}
                  </button>
                ) : (
                  <span style={{ width: 20 }} aria-hidden="true" />
                )}

                <button
                  type="button"
                  onClick={() => onSelect?.(section)}
                  data-testid="blueprint-tree-select"
                  style={{
                    flex: 1,
                    display: "flex",
                    alignItems: "center",
                    gap: "0.6rem",
                    border: "none",
                    background: "transparent",
                    padding: 0,
                    textAlign: "left",
                    cursor: onSelect ? "pointer" : "default",
                    color: T.ink,
                    fontSize: "0.9rem",
                  }}
                >
                  <span style={{ fontWeight: 600, minWidth: 70 }}>{section.section_code}</span>
                  <span style={{ color: T.text }}>{section.title}</span>
                </button>

                <RequiredBadge required={section.required} />

                {section.default_due_offset_days !== null && (
                  <span
                    data-testid="offset-chip"
                    title="Due this many days before the dossier target date"
                    style={{ fontSize: "0.78rem", color: T.muted, whiteSpace: "nowrap" }}
                  >
                    −{section.default_due_offset_days}d
                  </span>
                )}

                {editable && onReorder && (
                  <>
                    <button
                      type="button"
                      data-testid="move-up"
                      onClick={() => onReorder(section, -1)}
                      aria-label={`Move ${section.section_code} up`}
                      style={miniButton}
                    >
                      ↑
                    </button>
                    <button
                      type="button"
                      data-testid="move-down"
                      onClick={() => onReorder(section, 1)}
                      aria-label={`Move ${section.section_code} down`}
                      style={miniButton}
                    >
                      ↓
                    </button>
                  </>
                )}
                {editable && onRetire && !hasChildren && (
                  <button
                    type="button"
                    data-testid="retire-section"
                    onClick={() => onRetire(section)}
                    aria-label={`Remove ${section.section_code}`}
                    style={miniButton}
                  >
                    ✕
                  </button>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

const miniButton: React.CSSProperties = {
  width: 24,
  height: 24,
  border: `1px solid ${T.line}`,
  borderRadius: 4,
  background: "#fff",
  color: T.blue,
  cursor: "pointer",
  lineHeight: 1,
  fontSize: "0.8rem",
};
