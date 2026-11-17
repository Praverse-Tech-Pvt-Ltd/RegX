"use client";

import { Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { formulations, iigChecklists, ApiError } from "@/lib/api";

type Choice = { id: string; label: string; disabled?: boolean };

function NewExecutionPageInner() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const tenantSlug = searchParams.get("tenant") ?? "";

  // Pre-filled from a link ("Run IIG checklist" on a formulation version).
  const [checklistVersionPublicId, setChecklistVersionPublicId] = useState(searchParams.get("checklistVersion") ?? "");
  const [formulationVersionPublicId, setFormulationVersionPublicId] = useState(
    searchParams.get("formulationVersion") ?? "",
  );
  const [checklistChoices, setChecklistChoices] = useState<Choice[]>([]);
  const [formulationChoices, setFormulationChoices] = useState<Choice[]>([]);
  const [submitting, setSubmitting] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  useEffect(() => {
    if (!tenantSlug) router.push("/tenants");
  }, [tenantSlug, router]);

  // Choices a user can recognise, instead of IDs no screen shows. Found on the
  // real stack (2026-11-17): the form took only two UUIDs, so a user could not
  // start a checklist execution. Suggestions only: on failure the ID fields work.
  useEffect(() => {
    if (!tenantSlug) return;
    let cancelled = false;
    (async () => {
      const definitions = (await iigChecklists.definitions.list(tenantSlug)).results ?? [];
      const choices: Choice[] = [];
      for (const d of definitions) {
        const versions = (await iigChecklists.versions.listForDefinition(tenantSlug, d.public_id)).results ?? [];
        for (const v of versions.filter((x) => x.status === "active")) {
          choices.push({ id: v.public_id, label: `${d.code} — ${d.title} (v${v.version_number})` });
        }
      }
      if (!cancelled) setChecklistChoices(choices);
    })().catch(() => undefined);
    (async () => {
      const products = (await formulations.products.list(tenantSlug)).results ?? [];
      const choices: Choice[] = [];
      for (const p of products) {
        const versions = (await formulations.versions.list(tenantSlug, p.public_id)).results ?? [];
        for (const v of versions) {
          // The API runs a checklist only on an APPROVED formulation version, so
          // other versions are shown but cannot be chosen.
          const approved = v.status === "approved";
          choices.push({
            id: v.public_id,
            label: `${p.product_code} — ${p.proposed_product_name} (v${v.version_number}, ${approved ? "approved" : `${v.status} — not approved`})`,
            disabled: !approved,
          });
        }
      }
      if (!cancelled) setFormulationChoices(choices);
    })().catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [tenantSlug]);

  const chosenNotApproved = formulationChoices.some(
    (c) => c.disabled && c.id === formulationVersionPublicId.trim(),
  );

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!checklistVersionPublicId.trim() || !formulationVersionPublicId.trim() || chosenNotApproved) return;
    setSubmitting(true);
    setActionError(null);
    iigChecklists.executions
      .create(tenantSlug, {
        checklist_version_public_id: checklistVersionPublicId.trim(),
        formulation_version_public_id: formulationVersionPublicId.trim(),
      })
      .then((execution) => {
        router.push(`/iig-checklists/executions/${execution.publicId}?tenant=${tenantSlug}`);
      })
      .catch((err: unknown) => {
        if (err instanceof ApiError && err.status === 401) {
          router.push(`/signin?next=${encodeURIComponent(window.location.pathname + window.location.search)}`);
        } else if (err instanceof ApiError && err.status === 403) {
          setActionError("You do not have permission to create executions.");
        } else if (err instanceof ApiError && err.status === 409) {
          setActionError("An active execution already exists for this combination.");
        } else if (err instanceof ApiError) {
          setActionError(err.message || "Failed to create execution.");
        } else {
          setActionError("Failed to create execution.");
        }
      })
      .finally(() => setSubmitting(false));
  }

  return (
    <div>
      <h1>New Checklist Execution</h1>
      {actionError && <p style={{ color: "red" }}>{actionError}</p>}
      <form onSubmit={handleSubmit}>
        <div>
          <label>
            Choose an active checklist version
            <br />
            <select
              value={checklistChoices.some((c) => c.id === checklistVersionPublicId) ? checklistVersionPublicId : ""}
              onChange={(e) => setChecklistVersionPublicId(e.target.value)}
            >
              <option value="">—</option>
              {checklistChoices.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.label}
                </option>
              ))}
            </select>
          </label>
        </div>
        <div>
          <label>
            Choose a formulation version
            <br />
            <select
              value={formulationChoices.some((c) => c.id === formulationVersionPublicId) ? formulationVersionPublicId : ""}
              onChange={(e) => setFormulationVersionPublicId(e.target.value)}
            >
              <option value="">—</option>
              {formulationChoices.map((c) => (
                <option key={c.id} value={c.id} disabled={c.disabled}>
                  {c.label}
                </option>
              ))}
            </select>
          </label>
        </div>
        {chosenNotApproved && (
          <p role="alert">
            This formulation version is not approved, so a checklist cannot be run on it yet.
          </p>
        )}
        {formulationChoices.length > 0 && !formulationChoices.some((c) => !c.disabled) && (
          <p role="note">
            No formulation version is approved yet. A checklist can only be run on an approved
            formulation version.
          </p>
        )}
        <div>
          <label>
            Checklist Version Public ID
            <br />
            <input
              type="text"
              value={checklistVersionPublicId}
              onChange={(e) => setChecklistVersionPublicId(e.target.value)}
              required
              style={{ width: "36ch" }}
            />
          </label>
        </div>
        <div>
          <label>
            Formulation Version Public ID
            <br />
            <input
              type="text"
              value={formulationVersionPublicId}
              onChange={(e) => setFormulationVersionPublicId(e.target.value)}
              required
              style={{ width: "36ch" }}
            />
          </label>
        </div>
        <button type="submit" disabled={submitting || chosenNotApproved}>
          {submitting ? "Creating…" : "Create execution"}
        </button>
      </form>
    </div>
  );
}

export default function NewExecutionPage() {
  return (
    <main style={{ maxWidth: 1100, margin: "2rem auto", padding: "0 1rem" }}>
      <Suspense fallback={<p>Loading…</p>}>
        <NewExecutionPageInner />
      </Suspense>
    </main>
  );
}
