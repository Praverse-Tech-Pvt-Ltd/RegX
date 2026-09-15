"use client";

/**
 * P7 -- the Gap Analysis panel on an execution.
 *
 * What this deliberately does not render:
 *
 * * no percentage. The legacy on-demand endpoint still returns `score_percent`
 *   and `completeness_percent` for API compatibility, but no governed scoring
 *   formula exists, so showing one here would give an unapproved number the
 *   authority of a product feature;
 * * no "ready", "compliant", "approved" or agency language. A gap is a
 *   checklist requirement the execution has not met, and nothing more;
 * * no derived severity. `configured_criticality` is displayed exactly as the
 *   checklist definition set it, and blank reads as "not configured" rather
 *   than sorting as the lowest rank.
 *
 * A superseded checklist version is reported as information, not as a verdict:
 * an analysis taken against the version that was current at the time is still a
 * true record of what the checklist said then.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  ApiError,
  iigChecklists,
  type GapAnalysisDetailDTO,
  type GapAnalysisDTO,
  type GapAnalysisItemDTO,
  type GapStatus,
} from "@/lib/api";

const STATUS_LABELS: Record<GapStatus, string> = {
  gap: "Checklist gap",
  no_gap: "No gap",
  unanswered: "Unanswered",
  review_required: "Review required",
  not_applicable: "Not applicable",
};

const STATUS_ORDER: GapStatus[] = [
  "gap",
  "review_required",
  "unanswered",
  "no_gap",
  "not_applicable",
];

/** Operational grouping for the filter bar, not a regulatory ranking. */
const NEEDS_ATTENTION: GapStatus[] = ["gap", "review_required", "unanswered"];

const REASON_LABELS: Record<string, string> = {
  ANSWER_NO: 'Answered "no"',
  ANSWER_YES: 'Answered "yes"',
  NOT_GAPPABLE_TYPE: "Answered; this question type cannot record a gap",
  ANSWER_MISSING: "No answer recorded",
  APPLICABILITY_NOT_APPLICABLE: "Applicability rule excluded this question",
  APPLICABILITY_REVIEW_REQUIRED: "Applicability could not be determined automatically",
};

type Filter = "all" | "attention" | GapStatus;

function statusStyle(status: GapStatus): React.CSSProperties {
  const palette: Record<GapStatus, [string, string]> = {
    gap: ["#7f1d1d", "#fee2e2"],
    review_required: ["#78350f", "#fef3c7"],
    unanswered: ["#374151", "#f3f4f6"],
    no_gap: ["#14532d", "#dcfce7"],
    not_applicable: ["#3730a3", "#e0e7ff"],
  };
  const [color, background] = palette[status];
  return {
    color,
    background,
    borderRadius: 4,
    padding: "0.1rem 0.45rem",
    fontSize: "0.8rem",
    whiteSpace: "nowrap",
  };
}

/**
 * Visually hidden but announced. This codebase has no `sr-only` utility class,
 * and `display: none` would remove the caption from the accessibility tree —
 * which would defeat the reason for having one.
 */
const VISUALLY_HIDDEN: React.CSSProperties = {
  position: "absolute",
  width: 1,
  height: 1,
  padding: 0,
  margin: -1,
  overflow: "hidden",
  clip: "rect(0, 0, 0, 0)",
  whiteSpace: "nowrap",
  border: 0,
};

function formatTimestamp(value: string): string {
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString();
}

export function GapAnalysis({
  tenantSlug,
  executionPublicId,
}: {
  tenantSlug: string;
  executionPublicId: string;
}) {
  const [history, setHistory] = useState<GapAnalysisDTO[]>([]);
  const [latestIsCurrent, setLatestIsCurrent] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<GapAnalysisDetailDTO | null>(null);
  const [loading, setLoading] = useState(true);
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Generation is permission-gated server-side. A 403 hides the control rather
  // than offering a button that is guaranteed to fail; the server stays
  // authoritative either way.
  const [mayGenerate, setMayGenerate] = useState(true);

  const [filter, setFilter] = useState<Filter>("attention");
  const [sectionFilter, setSectionFilter] = useState<string>("all");
  const [criticalityFilter, setCriticalityFilter] = useState<string>("all");

  const loadHistory = useCallback(async () => {
    if (!tenantSlug || !executionPublicId) return;
    setLoading(true);
    setError(null);
    try {
      const page = await iigChecklists.executions.gapAnalyses.list(tenantSlug, executionPublicId);
      // Defensive: a proxy, a stub or a future API change can return a body
      // without `results`. Reading `.length` off undefined would take the whole
      // execution page down, and this panel is a section of that page rather
      // than the point of it.
      const results = Array.isArray(page?.results) ? page.results : [];
      setHistory(results);
      setLatestIsCurrent(Boolean(page?.latest_is_current));
      setSelectedId((current) => current ?? results[0]?.public_id ?? null);
    } catch (err) {
      setError(
        err instanceof ApiError && err.status === 403
          ? "You do not have permission to view gap analyses for this execution."
          : "Failed to load gap analyses."
      );
    } finally {
      setLoading(false);
    }
  }, [tenantSlug, executionPublicId]);

  useEffect(() => {
    void loadHistory();
  }, [loadHistory]);

  useEffect(() => {
    if (!selectedId) {
      setDetail(null);
      return;
    }
    let cancelled = false;
    iigChecklists.executions.gapAnalyses
      .get(tenantSlug, executionPublicId, selectedId)
      .then((loaded) => {
        if (cancelled) return;
        setDetail(Array.isArray(loaded?.items) ? loaded : null);
      })
      .catch(() => {
        if (!cancelled) setError("Failed to load the selected analysis.");
      });
    return () => {
      cancelled = true;
    };
  }, [selectedId, tenantSlug, executionPublicId]);

  async function generate() {
    setGenerating(true);
    setError(null);
    try {
      const created = await iigChecklists.executions.gapAnalyses.generate(
        tenantSlug,
        executionPublicId
      );
      setDetail(Array.isArray(created?.items) ? created : null);
      setSelectedId(created?.public_id ?? null);
      await loadHistory();
    } catch (err) {
      if (err instanceof ApiError && err.status === 403) {
        setMayGenerate(false);
        setError("You do not have permission to generate a gap analysis.");
      } else {
        setError("Failed to generate a gap analysis.");
      }
    } finally {
      setGenerating(false);
    }
  }

  const sections = useMemo(() => {
    if (!detail) return [];
    const seen = new Map<string, { code: string; title: string; order: number }>();
    for (const item of detail.items) {
      if (!seen.has(item.section_code)) {
        seen.set(item.section_code, {
          code: item.section_code,
          title: item.section_title,
          order: item.section_display_order,
        });
      }
    }
    return [...seen.values()].sort((a, b) => a.order - b.order || a.code.localeCompare(b.code));
  }, [detail]);

  // Only offered when the checklist actually configures it, so the control
  // never implies a severity model that does not exist.
  const criticalities = useMemo(() => {
    if (!detail) return [];
    return [...new Set(detail.items.map((i) => i.configured_criticality).filter(Boolean))].sort();
  }, [detail]);

  const visibleItems = useMemo(() => {
    if (!detail) return [];
    return detail.items.filter((item) => {
      if (filter === "attention" && !NEEDS_ATTENTION.includes(item.status)) return false;
      if (filter !== "all" && filter !== "attention" && item.status !== filter) return false;
      if (sectionFilter !== "all" && item.section_code !== sectionFilter) return false;
      if (criticalityFilter !== "all" && item.configured_criticality !== criticalityFilter) {
        return false;
      }
      return true;
    });
  }, [detail, filter, sectionFilter, criticalityFilter]);

  const grouped = useMemo(() => {
    const buckets = new Map<string, GapAnalysisItemDTO[]>();
    for (const item of visibleItems) {
      const list = buckets.get(item.section_code) ?? [];
      list.push(item);
      buckets.set(item.section_code, list);
    }
    return sections
      .filter((section) => buckets.has(section.code))
      .map((section) => ({
        ...section,
        items: (buckets.get(section.code) ?? []).sort(
          (a, b) => a.display_order - b.display_order || a.question_code.localeCompare(b.question_code)
        ),
      }));
  }, [visibleItems, sections]);

  return (
    <section style={{ marginTop: "2rem" }} aria-labelledby="gap-analysis-heading">
      <div
        style={{
          display: "flex",
          alignItems: "baseline",
          justifyContent: "space-between",
          gap: "1rem",
          flexWrap: "wrap",
        }}
      >
        <h2 id="gap-analysis-heading" style={{ margin: 0 }}>
          Gap analysis
        </h2>
        {mayGenerate && (
          <button type="button" onClick={generate} disabled={generating}>
            {generating ? "Generating…" : "Generate analysis"}
          </button>
        )}
      </div>

      <p style={{ margin: "0.35rem 0 1rem", fontSize: "0.85rem", color: "#4b5563" }}>
        Reports what this checklist records. It is not a regulatory assessment and does not
        indicate submission readiness.
      </p>

      {error && (
        <p role="alert" style={{ color: "#b91c1c" }}>
          {error}
        </p>
      )}

      {loading && <p>Loading gap analyses…</p>}

      {!loading && history.length === 0 && !error && (
        <p>
          No gap analysis has been generated for this execution yet.
          {mayGenerate ? " Generate one to record what the checklist currently reports." : ""}
        </p>
      )}

      {history.length > 0 && (
        <div style={{ display: "flex", gap: "0.75rem", alignItems: "center", flexWrap: "wrap" }}>
          <label>
            Snapshot{" "}
            <select
              value={selectedId ?? ""}
              onChange={(e) => setSelectedId(e.target.value)}
              aria-label="Select gap analysis snapshot"
            >
              {history.map((entry, index) => (
                <option key={entry.public_id} value={entry.public_id}>
                  {formatTimestamp(entry.generated_at)}
                  {index === 0 ? " (latest)" : ""}
                </option>
              ))}
            </select>
          </label>
          {!latestIsCurrent && (
            <span style={{ fontSize: "0.85rem", color: "#78350f" }}>
              Answers have changed since the latest analysis was generated.
            </span>
          )}
        </div>
      )}

      {detail && detail.counts && (
        <>
          <dl
            style={{
              display: "grid",
              gridTemplateColumns: "auto 1fr",
              gap: "0.25rem 1rem",
              margin: "1rem 0",
              fontSize: "0.88rem",
            }}
          >
            <dt>Generated</dt>
            <dd style={{ margin: 0 }}>
              {formatTimestamp(detail.generated_at)}
              {detail.generated_by_email ? ` by ${detail.generated_by_email}` : ""}
            </dd>
            <dt>Checklist version</dt>
            <dd style={{ margin: 0 }}>
              Version {detail.checklist_version_number}
              {detail.checklist_version_status === "superseded" && (
                <>
                  {" "}
                  <span style={{ color: "#78350f" }}>
                    — this version is no longer current. The analysis remains a valid record of
                    what that version reported.
                  </span>
                </>
              )}
            </dd>
            <dt>Input fingerprint</dt>
            <dd style={{ margin: 0 }}>
              <code>{detail.input_hash.slice(0, 16)}…</code> (algorithm v
              {detail.algorithm_version})
            </dd>
          </dl>

          <ul
            style={{
              display: "flex",
              gap: "0.5rem",
              flexWrap: "wrap",
              listStyle: "none",
              padding: 0,
              margin: "0 0 1rem",
            }}
          >
            {STATUS_ORDER.map((status) => (
              <li key={status} style={{ ...statusStyle(status), padding: "0.35rem 0.6rem" }}>
                {STATUS_LABELS[status]}: <strong>{detail.counts[status]}</strong>
              </li>
            ))}
            <li style={{ padding: "0.35rem 0.6rem", fontSize: "0.8rem", color: "#374151" }}>
              Applicable: <strong>{detail.counts.applicable}</strong> of{" "}
              {detail.counts.total_questions}
            </li>
          </ul>

          <div
            style={{ display: "flex", gap: "1rem", flexWrap: "wrap", marginBottom: "0.75rem" }}
          >
            <label>
              Show{" "}
              <select
                value={filter}
                onChange={(e) => setFilter(e.target.value as Filter)}
                aria-label="Filter by status"
              >
                <option value="attention">Needs attention</option>
                <option value="all">All questions</option>
                {STATUS_ORDER.map((status) => (
                  <option key={status} value={status}>
                    {STATUS_LABELS[status]}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Section{" "}
              <select
                value={sectionFilter}
                onChange={(e) => setSectionFilter(e.target.value)}
                aria-label="Filter by section"
              >
                <option value="all">All sections</option>
                {sections.map((section) => (
                  <option key={section.code} value={section.code}>
                    {section.code} — {section.title}
                  </option>
                ))}
              </select>
            </label>
            {criticalities.length > 0 && (
              <label>
                Criticality{" "}
                <select
                  value={criticalityFilter}
                  onChange={(e) => setCriticalityFilter(e.target.value)}
                  aria-label="Filter by configured criticality"
                >
                  <option value="all">Any</option>
                  {criticalities.map((value) => (
                    <option key={value} value={value}>
                      {value}
                    </option>
                  ))}
                </select>
              </label>
            )}
          </div>

          {grouped.length === 0 ? (
            <p>No questions match the current filters.</p>
          ) : (
            grouped.map((section) => (
              <div key={section.code} style={{ marginBottom: "1.25rem" }}>
                <h3 style={{ fontSize: "0.95rem", margin: "0 0 0.4rem" }}>
                  {section.code} — {section.title}
                </h3>
                <table style={{ borderCollapse: "collapse", width: "100%", fontSize: "0.85rem" }}>
                  <caption style={VISUALLY_HIDDEN}>
                    Gap analysis results for section {section.title}
                  </caption>
                  <thead>
                    <tr>
                      <th scope="col" style={{ textAlign: "left", padding: "0.3rem" }}>
                        Question
                      </th>
                      <th scope="col" style={{ textAlign: "left", padding: "0.3rem" }}>
                        Status
                      </th>
                      <th scope="col" style={{ textAlign: "left", padding: "0.3rem" }}>
                        Reason
                      </th>
                      <th scope="col" style={{ textAlign: "left", padding: "0.3rem" }}>
                        Criticality
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {section.items.map((item) => (
                      <tr key={item.question_public_id} style={{ borderTop: "1px solid #e5e7eb" }}>
                        <td style={{ padding: "0.3rem", verticalAlign: "top" }}>
                          <strong>{item.question_code}</strong>
                          <br />
                          {item.question_text}
                        </td>
                        <td style={{ padding: "0.3rem", verticalAlign: "top" }}>
                          <span style={statusStyle(item.status)}>
                            {STATUS_LABELS[item.status]}
                          </span>
                        </td>
                        <td style={{ padding: "0.3rem", verticalAlign: "top" }}>
                          {REASON_LABELS[item.reason_code] ?? item.reason_code}
                        </td>
                        <td style={{ padding: "0.3rem", verticalAlign: "top" }}>
                          {item.configured_criticality || (
                            <span style={{ color: "#6b7280" }}>Not configured</span>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ))
          )}
        </>
      )}
    </section>
  );
}
