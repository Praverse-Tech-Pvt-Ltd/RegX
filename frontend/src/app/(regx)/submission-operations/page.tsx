"use client";

/**
 * Submission operations dashboard.
 *
 * A dense operations screen, desktop-first, with every wide table in its own
 * horizontally scrolling region so a tablet degrades rather than breaks.
 *
 * Two rules run through the whole page:
 *   - a restricted dimension renders "Unavailable", never `0`;
 *   - severity carries a word, never colour alone.
 */

import { Suspense, useCallback, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import {
  isRestrictedPage,
  submissionOperations,
  type OperationsActivityRow,
  type OperationsAttentionRow,
  type OperationsCaseRow,
  type OperationsDossierRow,
  type OperationsOverview,
  type OperationsOwnerRow,
} from "@/lib/api";
import {
  EmptyState,
  InternalOnlyNote,
  InternalReadinessBadge,
  MaybeLink,
  SeverityBadge,
  SummaryCard,
  T,
  Unavailable,
  reasonLabel,
} from "./ops-primitives";

type Tab = "dossiers" | "owners" | "activity";

const TABS: { id: Tab; label: string }[] = [
  { id: "dossiers", label: "Dossiers" },
  { id: "owners", label: "Owner workload" },
  { id: "activity", label: "Recent activity" },
];

const cell: React.CSSProperties = {
  padding: "0.5rem 0.65rem",
  borderBottom: `1px solid ${T.line}`,
  fontSize: "0.85rem",
  color: T.text,
  textAlign: "left",
  verticalAlign: "top",
};

const headCell: React.CSSProperties = {
  ...cell,
  fontWeight: 600,
  color: T.ink,
  backgroundColor: T.panel,
  whiteSpace: "nowrap",
};

/**
 * Wide tables scroll inside their own region rather than the page body.
 *
 * The label is suffixed "table" because this region sits inside a titled
 * `<section>`, which is itself a region: two nested regions sharing one name
 * announce identically and tell a screen-reader user nothing about which they
 * have entered.
 */
function TableScroll({ children, label }: { children: React.ReactNode; label: string }) {
  return (
    <div
      role="region"
      aria-label={`${label} table`}
      tabIndex={0}
      style={{ overflowX: "auto", border: `1px solid ${T.line}`, borderRadius: "0.5rem" }}
    >
      {children}
    </div>
  );
}

function SubmissionOperationsPage() {
  const searchParams = useSearchParams();
  const tenantSlug = searchParams.get("tenant") ?? "";

  const [overview, setOverview] = useState<OperationsOverview | null>(null);
  const [attention, setAttention] = useState<OperationsAttentionRow[]>([]);
  const [attentionTruncated, setAttentionTruncated] = useState(false);
  const [cases, setCases] = useState<OperationsCaseRow[] | null>(null);
  const [casesRestricted, setCasesRestricted] = useState(false);
  const [dossiers, setDossiers] = useState<OperationsDossierRow[] | null>(null);
  const [dossiersRestricted, setDossiersRestricted] = useState(false);
  const [owners, setOwners] = useState<OperationsOwnerRow[]>([]);
  const [activity, setActivity] = useState<OperationsActivityRow[]>([]);
  const [tab, setTab] = useState<Tab>("dossiers");
  const [severity, setSeverity] = useState<string>("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [ov, att, casePage, dossierPage, ownerPage, act] = await Promise.all([
        submissionOperations.overview(tenantSlug),
        submissionOperations.attention(tenantSlug, severity ? { severity } : {}),
        submissionOperations.cases(tenantSlug),
        submissionOperations.dossiers(tenantSlug),
        submissionOperations.owners(tenantSlug),
        submissionOperations.recentActivity(tenantSlug),
      ]);
      setOverview(ov);
      setAttention(att.results ?? []);
      setAttentionTruncated(Boolean(att.truncated));

      if (isRestrictedPage(casePage)) {
        setCases(null);
        setCasesRestricted(true);
      } else {
        setCases(casePage.results);
        setCasesRestricted(false);
      }

      if (isRestrictedPage(dossierPage)) {
        setDossiers(null);
        setDossiersRestricted(true);
      } else {
        setDossiers(dossierPage.results);
        setDossiersRestricted(false);
      }

      setOwners(isRestrictedPage(ownerPage) ? [] : ownerPage.results);
      setActivity(act.results);
      setError(null);
    } catch {
      setError("Could not load the operations dashboard.");
    } finally {
      setLoading(false);
    }
  }, [tenantSlug, severity]);

  useEffect(() => {
    void load();
  }, [load]);

  if (loading && overview === null) {
    return (
      <main style={{ padding: "1.5rem" }}>
        <h1 style={{ color: T.ink }}>Submission operations</h1>
        <p role="status" data-testid="ops-loading" style={{ color: T.muted }}>
          Loading operational summary…
        </p>
      </main>
    );
  }

  if (error) {
    return (
      <main style={{ padding: "1.5rem" }}>
        <h1 style={{ color: T.ink }}>Submission operations</h1>
        <p role="alert" data-testid="ops-error" style={{ color: "#8c1d1d" }}>
          {error}
        </p>
      </main>
    );
  }

  const sections = overview?.sections ?? null;

  return (
    <main style={{ padding: "1.5rem", maxWidth: "80rem" }}>
      <header>
        <h1 style={{ color: T.ink, margin: 0, fontSize: "1.5rem" }}>Submission operations</h1>
        <InternalOnlyNote />
      </header>

      {/* ---------------------------------------------------------------- */}
      <section aria-labelledby="ops-summary-heading" style={{ marginTop: "1.5rem" }}>
        <h2 id="ops-summary-heading" style={{ fontSize: "1.05rem", color: T.ink }}>
          Operational summary
        </h2>
        <div
          data-testid="summary-cards"
          style={{ display: "flex", flexWrap: "wrap", gap: "0.75rem" }}
        >
          <SummaryCard
            testId="card-open-cases"
            label="Open cases"
            value={overview?.cases?.open ?? (overview?.cases === null ? null : 0)}
          />
          <SummaryCard
            testId="card-open-dossiers"
            label="Open dossiers"
            value={overview?.dossiers?.open ?? (overview?.dossiers === null ? null : 0)}
          />
          <SummaryCard
            testId="card-blocked-sections"
            label="Blocked required sections"
            value={sections === null ? null : sections.required_blocked}
          />
          <SummaryCard
            testId="card-overdue-sections"
            label="Overdue required sections"
            value={sections === null ? null : sections.required_overdue}
          />
          <SummaryCard
            testId="card-due-soon-sections"
            label="Required sections due soon"
            hint={
              overview ? `Within ${overview.due_soon_days} days (display window)` : undefined
            }
            value={sections === null ? null : sections.required_due_soon}
          />
          <SummaryCard
            testId="card-open-blockers"
            label="Open blockers"
            value={overview?.blockers === null ? null : (overview?.blockers?.open ?? 0)}
          />
          <SummaryCard
            testId="card-waiting-review"
            label="Workflows waiting review"
            value={
              overview?.workflows === null ? null : (overview?.workflows?.waiting_review ?? 0)
            }
          />
          <SummaryCard
            testId="card-stale-upgrades"
            label="Stale upgrade plans"
            value={overview?.upgrades === null ? null : (overview?.upgrades?.stale ?? 0)}
          />
        </div>
      </section>

      {/* ---------------------------------------------------------------- */}
      <section aria-labelledby="ops-attention-heading" style={{ marginTop: "2rem" }}>
        <div
          style={{
            display: "flex",
            alignItems: "baseline",
            gap: "1rem",
            flexWrap: "wrap",
          }}
        >
          <h2 id="ops-attention-heading" style={{ fontSize: "1.05rem", color: T.ink }}>
            Attention queue
          </h2>
          <label style={{ fontSize: "0.82rem", color: T.text }}>
            Severity{" "}
            <select
              data-testid="severity-filter"
              value={severity}
              onChange={(e) => setSeverity(e.target.value)}
              style={{ padding: "0.2rem 0.35rem" }}
            >
              <option value="">All</option>
              <option value="blocked">Blocked</option>
              <option value="overdue">Overdue</option>
              <option value="attention">Needs attention</option>
              <option value="informational">Informational</option>
            </select>
          </label>
        </div>

        {attention.length === 0 ? (
          <EmptyState
            testId="attention-empty"
            restricted={false}
            emptyMessage="Nothing currently needs attention."
            restrictedMessage="You do not have permission to view this."
          />
        ) : (
          <TableScroll label="Attention queue">
            <table style={{ borderCollapse: "collapse", width: "100%" }}>
              <caption className="sr-only" style={{ textAlign: "left", padding: "0.4rem" }}>
                Items needing operational attention, most urgent first.
              </caption>
              <thead>
                <tr>
                  <th scope="col" style={headCell}>
                    Severity
                  </th>
                  <th scope="col" style={headCell}>
                    Reason
                  </th>
                  <th scope="col" style={headCell}>
                    Item
                  </th>
                  <th scope="col" style={headCell}>
                    Due
                  </th>
                  <th scope="col" style={headCell}>
                    State
                  </th>
                </tr>
              </thead>
              <tbody data-testid="attention-rows">
                {attention.map((row) => (
                  <tr key={`${row.reason_code}-${row.resource_public_id}`}>
                    <td style={cell}>
                      <SeverityBadge severity={row.severity} />
                    </td>
                    <td style={cell}>{reasonLabel(row.reason_code)}</td>
                    <td style={cell}>
                      <MaybeLink
                        testId="attention-link"
                        href={
                          row.dossier_public_id
                            ? `/submission-dossiers/${row.dossier_public_id}?tenant=${tenantSlug}`
                            : null
                        }
                      >
                        {row.resource_label}
                      </MaybeLink>
                    </td>
                    <td style={cell}>{row.due_date ?? "—"}</td>
                    <td style={cell}>{row.operational_state}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </TableScroll>
        )}
        {attentionTruncated && (
          <p data-testid="attention-truncated" style={{ fontSize: "0.78rem", color: T.muted }}>
            Showing the highest-priority items only; more exist than are listed here.
          </p>
        )}
      </section>

      {/* ---------------------------------------------------------------- */}
      <section aria-labelledby="ops-cases-heading" style={{ marginTop: "2rem" }}>
        <h2 id="ops-cases-heading" style={{ fontSize: "1.05rem", color: T.ink }}>
          Cases
        </h2>
        {cases === null || cases.length === 0 ? (
          <EmptyState
            testId="cases-empty"
            restricted={casesRestricted}
            emptyMessage="No cases yet."
            restrictedMessage="You do not have permission to view cases."
          />
        ) : (
          <TableScroll label="Case status">
            <table style={{ borderCollapse: "collapse", width: "100%" }}>
              <thead>
                <tr>
                  <th scope="col" style={headCell}>
                    Case
                  </th>
                  <th scope="col" style={headCell}>
                    Status
                  </th>
                  <th scope="col" style={headCell}>
                    Internal readiness
                  </th>
                  <th scope="col" style={headCell}>
                    Required complete
                  </th>
                  <th scope="col" style={headCell}>
                    Blockers
                  </th>
                  <th scope="col" style={headCell}>
                    Overdue
                  </th>
                </tr>
              </thead>
              <tbody data-testid="case-rows">
                {cases.map((row) => (
                  <tr key={row.public_id}>
                    <th scope="row" style={{ ...cell, fontWeight: 600 }}>
                      <MaybeLink
                        testId="case-link"
                        href={`/regulatory-cases/${row.public_id}?tenant=${tenantSlug}`}
                      >
                        {row.case_number}
                      </MaybeLink>{" "}
                      <span style={{ color: T.muted, fontWeight: 400 }}>{row.title}</span>
                    </th>
                    <td style={cell}>{row.status}</td>
                    <td style={cell}>
                      <InternalReadinessBadge value={row.internal_readiness} />
                    </td>
                    <td style={cell}>
                      {row.sections === null ? (
                        <Unavailable testId="case-sections-unavailable" />
                      ) : (
                        `${row.sections.required_complete} / ${row.sections.required_total}`
                      )}
                    </td>
                    <td style={cell}>
                      {row.open_blockers === null ? (
                        <Unavailable testId="case-blockers-unavailable" />
                      ) : (
                        row.open_blockers
                      )}
                    </td>
                    <td style={cell}>
                      {row.sections === null ? (
                        <Unavailable />
                      ) : (
                        row.sections.overdue
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </TableScroll>
        )}
      </section>

      {/* ---------------------------------------------------------------- */}
      <section aria-labelledby="ops-detail-heading" style={{ marginTop: "2rem" }}>
        <h2 id="ops-detail-heading" style={{ fontSize: "1.05rem", color: T.ink }}>
          Detail
        </h2>
        <div role="tablist" aria-label="Detail panels" style={{ display: "flex", gap: "0.35rem" }}>
          {TABS.map((t) => (
            <button
              key={t.id}
              role="tab"
              type="button"
              id={`tab-${t.id}`}
              aria-selected={tab === t.id}
              aria-controls={`panel-${t.id}`}
              data-testid={`tab-${t.id}`}
              onClick={() => setTab(t.id)}
              style={{
                padding: "0.35rem 0.75rem",
                border: `1px solid ${T.line}`,
                borderRadius: "0.35rem",
                backgroundColor: tab === t.id ? T.soft : "#fff",
                color: tab === t.id ? T.navy : T.text,
                fontWeight: tab === t.id ? 600 : 400,
                cursor: "pointer",
              }}
            >
              {t.label}
            </button>
          ))}
        </div>

        <div
          role="tabpanel"
          id={`panel-${tab}`}
          aria-labelledby={`tab-${tab}`}
          style={{ marginTop: "0.75rem" }}
        >
          {tab === "dossiers" &&
            (dossiers === null || dossiers.length === 0 ? (
              <EmptyState
                testId="dossiers-empty"
                restricted={dossiersRestricted}
                emptyMessage="No dossiers yet."
                restrictedMessage="You do not have permission to view dossiers."
              />
            ) : (
              <TableScroll label="Dossier status">
                <table style={{ borderCollapse: "collapse", width: "100%" }}>
                  <thead>
                    <tr>
                      <th scope="col" style={headCell}>
                        Dossier
                      </th>
                      <th scope="col" style={headCell}>
                        Status
                      </th>
                      <th scope="col" style={headCell}>
                        Internal readiness
                      </th>
                      <th scope="col" style={headCell}>
                        Required
                      </th>
                      <th scope="col" style={headCell}>
                        Blocked
                      </th>
                      <th scope="col" style={headCell}>
                        Overdue
                      </th>
                      <th scope="col" style={headCell}>
                        Upgrades
                      </th>
                    </tr>
                  </thead>
                  <tbody data-testid="dossier-rows">
                    {dossiers.map((row) => (
                      <tr key={row.public_id}>
                        <th scope="row" style={{ ...cell, fontWeight: 600 }}>
                          <MaybeLink
                            testId="dossier-link"
                            href={`/submission-dossiers/${row.public_id}?tenant=${tenantSlug}`}
                          >
                            {row.title}
                          </MaybeLink>
                        </th>
                        <td style={cell}>{row.status}</td>
                        <td style={cell}>
                          <InternalReadinessBadge value={row.internal_readiness} />
                        </td>
                        <td style={cell}>
                          {row.required_complete} / {row.required_total}
                        </td>
                        <td style={cell}>{row.blocked_sections}</td>
                        <td style={cell}>{row.overdue_sections}</td>
                        <td style={cell}>
                          {row.upgrade === null ? (
                            <Unavailable testId="dossier-upgrade-unavailable" />
                          ) : (
                            `${row.upgrade.open} open, ${row.upgrade.stale} stale`
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </TableScroll>
            ))}

          {tab === "owners" &&
            (owners.length === 0 ? (
              <EmptyState
                testId="owners-empty"
                restricted={dossiersRestricted}
                emptyMessage="No outstanding required work is assigned."
                restrictedMessage="You do not have permission to view dossiers."
              />
            ) : (
              <TableScroll label="Owner workload">
                <table style={{ borderCollapse: "collapse", width: "100%" }}>
                  <thead>
                    <tr>
                      <th scope="col" style={headCell}>
                        Owner
                      </th>
                      <th scope="col" style={headCell}>
                        Outstanding
                      </th>
                      <th scope="col" style={headCell}>
                        Blocked
                      </th>
                      <th scope="col" style={headCell}>
                        Overdue
                      </th>
                    </tr>
                  </thead>
                  <tbody data-testid="owner-rows">
                    {owners.map((row) => (
                      <tr key={row.owner?.public_id ?? "unassigned"}>
                        <th scope="row" style={{ ...cell, fontWeight: 600 }}>
                          {row.unassigned ? "Unassigned" : row.owner?.full_name}
                        </th>
                        <td style={cell}>{row.outstanding}</td>
                        <td style={cell}>{row.blocked}</td>
                        <td style={cell}>{row.overdue}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </TableScroll>
            ))}

          {tab === "activity" &&
            (activity.length === 0 ? (
              <EmptyState
                testId="activity-empty"
                restricted={false}
                emptyMessage="No recent activity."
                restrictedMessage="You do not have permission to view this."
              />
            ) : (
              <ul data-testid="activity-rows" style={{ paddingLeft: "1.1rem", margin: 0 }}>
                {activity.map((row, i) => (
                  <li
                    key={`${row.event_type}-${row.resource_public_id}-${i}`}
                    style={{ fontSize: "0.85rem", color: T.text, marginBottom: "0.3rem" }}
                  >
                    <span style={{ color: T.ink, fontWeight: 600 }}>
                      {row.event_type.replace(/[._]/g, " ")}
                    </span>{" "}
                    <span style={{ color: T.muted }}>{row.occurred_at}</span>
                  </li>
                ))}
              </ul>
            ))}
        </div>
      </section>
    </main>
  );
}

export default function Page() {
  return (
    <Suspense fallback={<p style={{ padding: "1.5rem" }}>Loading…</p>}>
      <SubmissionOperationsPage />
    </Suspense>
  );
}
