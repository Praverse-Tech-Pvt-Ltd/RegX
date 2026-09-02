"use client";

import { useCallback, useEffect, useState } from "react";
import {
  ApiError,
  dossierUpgrades,
  type UpgradePlanDetail,
  type UpgradePlanList,
} from "@/lib/api";
import {
  BlockingReason,
  ChangeTypeBadge,
  ItemStatusBadge,
  PlanStatusBadge,
  ReadyMeaningNote,
} from "./upgrade-badges";

/**
 * The Blueprint Upgrade tab on a dossier.
 *
 * **Nothing here applies anything by itself.** Generate produces a proposal,
 * accept records a decision, and only the explicit Apply button writes -- and
 * only the accepted items. The three are deliberately separate controls with
 * separate confirmations, because collapsing them is how an "upgrade" quietly
 * becomes an overwrite.
 */

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

export function UpgradePanel({
  tenantSlug,
  dossierPublicId,
  dossierTerminal,
}: {
  tenantSlug: string;
  dossierPublicId: string;
  dossierTerminal: boolean;
}) {
  const [list, setList] = useState<UpgradePlanList | null>(null);
  const [openPlan, setOpenPlan] = useState<UpgradePlanDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [applied, setApplied] = useState<string | null>(null);
  const load = useCallback(async (): Promise<void> => {
    setLoading(true);
    try {
      const data = await dossierUpgrades.listForDossier(tenantSlug, dossierPublicId);
      setList(data);
      const open = data.results.find((p) => p.status === "draft" || p.status === "ready");
      setOpenPlan(open ? await dossierUpgrades.get(tenantSlug, open.public_id) : null);
      setError(null);
    } catch {
      setError("Failed to load upgrade plans.");
    } finally {
      setLoading(false);
    }
  }, [tenantSlug, dossierPublicId]);
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
        setError("That version is not available to you.");
      else setError("The action could not be completed.");
    } finally {
      setBusy(false);
    }
  }
  if (loading && !list) return <p style={{ color: T.muted }}>Loading upgrade plans…</p>;
  if (!list)
    return (
      <p role="alert" data-testid="upgrade-error" style={alertStyle}>
        {error ?? "Failed to load upgrade plans."}
      </p>
    );
  const p = list.permissions;
  const targets = list.available_targets;
  const canGenerate = p.can_generate && !openPlan && targets.length > 0;
  return (
    <section data-testid="tab-panel-upgrade">
      <div style={{ marginBottom: "1rem" }}>
        <p style={{ margin: "0 0 0.5rem", fontSize: "0.9rem", color: T.muted, lineHeight: 1.6 }}>
          A newer blueprint version never changes this dossier on its own. Generate a plan to see
          what differs, review each change, then apply only what you accept.
        </p>
        <ReadyMeaningNote />
      </div>
      {error && (
        <p role="alert" data-testid="upgrade-error" style={alertStyle}>
          {error}
        </p>
      )}
      {applied && (
        <p data-testid="upgrade-applied" style={{ ...alertStyle, ...successStyle }}>
          {applied}
        </p>
      )}

      {/* Provenance and what is available ------------------------------- */}
      <div
        style={{
          display: "flex",
          gap: "1rem",
          flexWrap: "wrap",
          alignItems: "center",
          padding: "0.8rem",
          border: `1px solid ${T.line}`,
          borderRadius: 8,
          background: T.panel,
          marginBottom: "1rem",
        }}
      >
        <span style={{ fontSize: "0.9rem", color: T.text }} data-testid="current-version">
          {list.current_version ? (
            <>
              Currently at <strong>version {list.current_version.version_number}</strong>
              {list.current_version.name ? ` of ${list.current_version.name}` : ""}
              {list.current_version.restricted ? " of a controlled blueprint" : ""}
            </>
          ) : (
            "This dossier was not created from a blueprint."
          )}
        </span>
        <span style={{ flex: 1 }} />
        {canGenerate && !dossierTerminal && (
          <div style={{ display: "flex", gap: "0.5rem", alignItems: "center", flexWrap: "wrap" }}>
            <label htmlFor="upgrade-target" style={hidden}>
              Target version
            </label>
            <select id="upgrade-target" data-testid="upgrade-target" style={field} defaultValue="">
              <option value="" disabled>
                Choose a version…
              </option>
              {targets.map((v) => (
                <option key={v.public_id} value={v.public_id}>
                  Version {v.version_number}
                  {v.name ? ` — ${v.name}` : ""}
                </option>
              ))}
            </select>
            <button
              type="button"
              data-testid="generate-plan"
              disabled={busy}
              onClick={() => {
                const select = document.getElementById(
                  "upgrade-target"
                ) as HTMLSelectElement | null;
                if (!select?.value) {
                  setError("Choose a version to compare against.");
                  return;
                }
                void act(
                  () =>
                    dossierUpgrades.generate(tenantSlug, dossierPublicId, {
                      target_blueprint_version_public_id: select.value,
                    }),
                  "An open plan for that version already exists."
                );
              }}
              style={busy ? disabledPrimary : primary}
            >
              Compare
            </button>
          </div>
        )}
      </div>
      {targets.length === 0 && !openPlan && (
        <p data-testid="no-targets" style={emptyStyle}>
          No newer blueprint version is available for this dossier.
        </p>
      )}

      {/* The open plan ---------------------------------------------------- */}
      {openPlan && (
        <div data-testid="open-plan">
          <div
            style={{
              display: "flex",
              gap: "0.6rem",
              alignItems: "center",
              flexWrap: "wrap",
              marginBottom: "0.75rem",
            }}
          >
            <h3 style={{ margin: 0, fontSize: "1rem", color: T.ink }}>
              Version {openPlan.source_version?.version_number} →{" "}
              {openPlan.target_version?.version_number}
            </h3>
            <PlanStatusBadge status={openPlan.status} />
            <span style={{ fontSize: "0.85rem", color: T.muted }} data-testid="plan-counts">
              {openPlan.actionable_items} change
              {openPlan.actionable_items === 1 ? "" : "s"} · {openPlan.accepted_items} accepted ·{" "}
              {openPlan.rejected_items} rejected
              {openPlan.blocked_items > 0 ? ` · ${openPlan.blocked_items} blocked` : ""}
            </span>
          </div>
          {openPlan.is_stale && (
            <p data-testid="plan-stale" style={{ ...alertStyle, ...warnStyle }}>
              This dossier changed after the plan was generated, so the plan no longer describes
              it. Regenerate before applying.
            </p>
          )}
          <UpgradeDiffTable
            plan={openPlan}
            canReview={p.can_review && openPlan.status === "draft"}
            busy={busy}
            onAccept={(item) =>
              void act(
                () => dossierUpgrades.acceptItem(tenantSlug, openPlan.public_id, item),
                "That item cannot be accepted."
              )
            }
            onReject={(item) =>
              void act(
                () => dossierUpgrades.rejectItem(tenantSlug, openPlan.public_id, item),
                "That item cannot be rejected."
              )
            }
          />
          <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap", marginTop: "1rem" }}>
            {p.can_generate && (
              <button
                type="button"
                data-testid="regenerate-plan"
                disabled={busy}
                onClick={() =>
                  void act(
                    () => dossierUpgrades.regenerate(tenantSlug, openPlan.public_id),
                    "This plan can no longer be regenerated."
                  )
                }
                style={secondary}
              >
                Regenerate
              </button>
            )}
            {p.can_review && openPlan.status === "draft" && (
              <button
                type="button"
                data-testid="mark-ready"
                disabled={busy}
                onClick={() =>
                  void act(
                    () => dossierUpgrades.markReady(tenantSlug, openPlan.public_id),
                    "Review every change first — each one must be accepted or rejected."
                  )
                }
                style={busy ? disabledPrimary : primary}
              >
                Mark reviewed
              </button>
            )}
            {p.can_apply && openPlan.status === "ready" && !dossierTerminal && (
              <>
                {!confirming ? (
                  <button
                    type="button"
                    data-testid="apply-plan"
                    disabled={busy}
                    onClick={() => setConfirming(true)}
                    style={busy ? disabledPrimary : primary}
                  >
                    Apply accepted changes
                  </button>
                ) : (
                  <span
                    data-testid="apply-confirm"
                    style={{
                      display: "inline-flex",
                      gap: "0.5rem",
                      alignItems: "center",
                      flexWrap: "wrap",
                    }}
                  >
                    <span style={{ fontSize: "0.88rem", color: T.text }}>
                      Apply {openPlan.accepted_items} accepted change
                      {openPlan.accepted_items === 1 ? "" : "s"} to this dossier?
                    </span>
                    <button
                      type="button"
                      data-testid="apply-confirm-yes"
                      disabled={busy}
                      onClick={() => {
                        setConfirming(false);
                        void (async () => {
                          setBusy(true);
                          try {
                            const result = await dossierUpgrades.apply(
                              tenantSlug,
                              openPlan.public_id
                            );
                            setApplied(
                              `Applied: ${result.sections_added} added, ` +
                                `${result.sections_updated} updated, ` +
                                `${result.sections_retired} retired.`
                            );
                            await load();
                          } catch (err: unknown) {
                            await load();
                            // Prefer the server's reason: it names the section
                            // and why, which is what the user needs to decide
                            // between regenerating and clearing the work. It
                            // carries a section_code and a reason code only --
                            // no titles, notes or field values.
                            if (err instanceof ApiError && err.status === 409)
                              setError(
                                err.message ||
                                  "The plan could not be applied — it may be stale, hold blocked items, or describe work that has since changed."
                              );
                            else setError("The plan could not be applied.");
                          } finally {
                            setBusy(false);
                          }
                        })();
                      }}
                      style={primary}
                    >
                      Yes, apply
                    </button>
                    <button
                      type="button"
                      data-testid="apply-confirm-no"
                      onClick={() => setConfirming(false)}
                      style={secondary}
                    >
                      Cancel
                    </button>
                  </span>
                )}
              </>
            )}
            {p.can_cancel && (
              <button
                type="button"
                data-testid="cancel-plan"
                disabled={busy}
                onClick={() =>
                  void act(
                    () => dossierUpgrades.cancel(tenantSlug, openPlan.public_id),
                    "This plan is already closed."
                  )
                }
                style={secondary}
              >
                Discard plan
              </button>
            )}
          </div>
        </div>
      )}

      {/* History ----------------------------------------------------------- */}
      {list.results.some((r) => r.status === "applied") && (
        <section style={{ marginTop: "1.75rem" }}>
          <h3 style={{ margin: "0 0 0.5rem", fontSize: "1rem", color: T.ink }}>
            Upgrade history
          </h3>
          <ul data-testid="upgrade-history" style={{ margin: 0, paddingLeft: "1.1rem" }}>
            {list.results
              .filter((r) => r.status === "applied")
              .map((r) => (
                <li
                  key={r.public_id}
                  style={{ fontSize: "0.88rem", color: T.text, marginBottom: "0.25rem" }}
                >
                  Version {r.source_version?.version_number} →{" "}
                  {r.target_version?.version_number}
                  {r.applied_at ? ` on ${new Date(r.applied_at).toLocaleDateString()}` : ""}
                </li>
              ))}
          </ul>
        </section>
      )}
    </section>
  );
}

/**
 * The change list.
 *
 * One row per field, so accepting a title change never silently accepts a
 * reparent alongside it. Values are short scalars -- "Required: yes → no" --
 * rather than raw JSON, because a reviewer has to be able to read the whole
 * list.
 */

function UpgradeDiffTable({
  plan,
  canReview,
  busy,
  onAccept,
  onReject,
}: {
  plan: UpgradePlanDetail;
  canReview: boolean;
  busy: boolean;
  onAccept: (itemPublicId: string) => void;
  onReject: (itemPublicId: string) => void;
}) {
  const actionable = plan.items.filter((i) => i.change_type !== "no_change");
  if (actionable.length === 0) {
    return (
      <p data-testid="no-differences" style={emptyStyle}>
        This dossier already matches that blueprint version. There is nothing to apply.
      </p>
    );
  }
  return (
    <div style={{ overflowX: "auto" }}>
      <table
        data-testid="upgrade-diff"
        style={{ width: "100%", borderCollapse: "separate", borderSpacing: 0 }}
      >
        <caption style={hidden}>Proposed changes from the newer blueprint version</caption>
        <thead>
          <tr style={{ textAlign: "left", borderBottom: `1px solid ${T.line}` }}>
            <th style={head}>Change</th>
            <th style={head}>Section</th>
            <th style={head}>Field</th>
            <th style={head}>From</th>
            <th style={head}>To</th>
            <th style={head}>Decision</th>
          </tr>
        </thead>
        <tbody>
          {actionable.map((item) => (
            <tr
              key={item.public_id}
              data-testid="upgrade-row"
              data-change-type={item.change_type}
              data-item-status={item.status}
              style={{ borderBottom: `1px solid ${T.line}` }}
            >
              <td style={cell}>
                <ChangeTypeBadge changeType={item.change_type} />
              </td>
              <td style={{ ...cell, fontWeight: 600 }}>{item.section_code || "—"}</td>
              <td style={{ ...cell, color: T.muted }}>{item.field_name || "—"}</td>
              <td style={cell}>{item.before_value || "—"}</td>
              <td style={cell}>{item.after_value || "—"}</td>
              <td style={cell}>
                <span
                  style={{ display: "inline-flex", gap: "0.4rem", alignItems: "center", flexWrap: "wrap" }}
                >
                  <ItemStatusBadge status={item.status} />
                  {item.status === "blocked" && (
                    <BlockingReason reason={item.blocking_reason} />
                  )}
                  {canReview && item.status !== "blocked" && (
                    <>
                      <button
                        type="button"
                        data-testid="accept-item"
                        aria-label={`Accept ${item.change_type} for ${item.section_code}`}
                        disabled={busy}
                        onClick={() => onAccept(item.public_id)}
                        style={miniPrimary}
                      >
                        Accept
                      </button>
                      <button
                        type="button"
                        data-testid="reject-item"
                        aria-label={`Reject ${item.change_type} for ${item.section_code}`}
                        disabled={busy}
                        onClick={() => onReject(item.public_id)}
                        style={miniSecondary}
                      >
                        Reject
                      </button>
                    </>
                  )}
                </span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

const hidden: React.CSSProperties = { position: "absolute", left: -9999 };

const field: React.CSSProperties = {
  padding: "0.45rem 0.6rem",
  border: `1px solid ${T.line}`,
  borderRadius: 6,
  background: "#fff",
  color: T.text,
  fontSize: "0.88rem",
};

const head: React.CSSProperties = {
  padding: "0.5rem",
  fontSize: "0.72rem",
  fontWeight: 700,
  letterSpacing: "0.05em",
  textTransform: "uppercase",
  color: T.muted,
};

const cell: React.CSSProperties = {
  padding: "0.6rem 0.5rem",
  fontSize: "0.9rem",
  color: T.text,
  verticalAlign: "middle",
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

const miniPrimary: React.CSSProperties = {
  padding: "0.15rem 0.5rem",
  border: `1px solid ${T.navy}`,
  borderRadius: 6,
  background: T.blue,
  color: "#fff",
  fontSize: "0.78rem",
  fontWeight: 600,
  cursor: "pointer",
};

const miniSecondary: React.CSSProperties = {
  padding: "0.15rem 0.5rem",
  border: `1px solid ${T.line}`,
  borderRadius: 6,
  background: "#fff",
  color: T.blue,
  fontSize: "0.78rem",
  fontWeight: 600,
  cursor: "pointer",
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

const warnStyle: React.CSSProperties = {
  border: "1px solid #e8d5a8",
  background: "#fdf6e6",
  color: "#8a5a10",
};

const successStyle: React.CSSProperties = {
  border: `1px solid ${T.line}`,
  background: T.soft,
  color: T.text,
};

const emptyStyle: React.CSSProperties = {
  margin: 0,
  padding: "1.25rem 1rem",
  border: `1px solid ${T.line}`,
  borderRadius: 8,
  background: T.panel,
  color: T.muted,
  fontSize: "0.9rem",
};
