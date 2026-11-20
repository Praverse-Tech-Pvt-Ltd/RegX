"use client";

import { Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams, useParams } from "next/navigation";
import Link from "next/link";
import { formulations, type FormulationVersion, type FormulationComponent, type DosingRegimen, ApiError, isSignedOut, loadError } from "@/lib/api";
import { ProvenanceLabel } from "@/components/ProvenanceLabel";
import { QuantityMeaningSelect } from "@/components/QuantityMeaningSelect";
import { FormulationReviewPanel } from "@/components/FormulationReviewPanel";

/** The units a component may use (iid_assessment/amount_limits.py COMPONENT_UNITS). */
const COMPONENT_UNITS = [
  { value: "mg", label: "mg" },
  { value: "g", label: "g" },
  { value: "kg", label: "kg" },
  { value: "µg", label: "µg" },
  { value: "mL", label: "mL" },
  { value: "L", label: "L" },
  { value: "percent", label: "% (choose w/w, w/v or v/v below)" },
];

/** A meaning's numerator unit ("mg", "ml") -> the matching option value. */
function toUnitOption(unit: string): string {
  const hit = COMPONENT_UNITS.find((u) => u.value.toLowerCase() === unit.toLowerCase());
  return hit ? hit.value : unit;
}
import { PercentValue } from "@/components/PercentValue";

function VersionDetailInner() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const params = useParams<{ publicId: string; versionPublicId: string }>();
  const tenantSlug = searchParams.get("tenant") ?? "";
  const productPublicId = params.publicId;
  const versionPublicId = params.versionPublicId;

  const [version, setVersion] = useState<FormulationVersion | null>(null);
  const [components, setComponents] = useState<FormulationComponent[]>([]);
  const [regimens, setRegimens] = useState<DosingRegimen[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [showComponentForm, setShowComponentForm] = useState(false);
  const [componentType, setComponentType] = useState<"active" | "inactive">("inactive");
  const [componentName, setComponentName] = useState("");
  const [componentQty, setComponentQty] = useState("");
  const [componentUnit, setComponentUnit] = useState("mg");
  const [componentMeaning, setComponentMeaning] = useState("");
  const [componentSubmitting, setComponentSubmitting] = useState(false);
  const [componentError, setComponentError] = useState<string | null>(null);

  const [showRegimenForm, setShowRegimenForm] = useState(false);
  const [unitsPerAdmin, setUnitsPerAdmin] = useState("1");
  const [adminPerDay, setAdminPerDay] = useState("");
  const [maxRegimenUnits, setMaxRegimenUnits] = useState("");
  const [regimenSubmitting, setRegimenSubmitting] = useState(false);
  const [regimenError, setRegimenError] = useState<string | null>(null);

  function load() {
    if (!tenantSlug) return;
    setLoading(true);
    Promise.all([
      formulations.versions.get(tenantSlug, versionPublicId),
      formulations.components.list(tenantSlug, versionPublicId),
      formulations.dosingRegimens.list(tenantSlug, versionPublicId),
    ])
      .then(([v, c, r]) => {
        setVersion(v);
        setComponents(c);
        setRegimens(r);
      })
      .catch((err: unknown) => {
        if (err instanceof ApiError && err.status === 404) setError("Formulation version not found.");
        else if (isSignedOut(err))
          router.push(`/signin?next=${encodeURIComponent(window.location.pathname + window.location.search)}`);
        else setError(loadError(err, "Failed to load formulation version."));
      })
      .finally(() => setLoading(false));
  }

  useEffect(() => {
    if (!tenantSlug) {
      router.push("/tenants");
      return;
    }
    load();
  }, [tenantSlug, versionPublicId]); // eslint-disable-line react-hooks/exhaustive-deps

  async function handleAddComponent(e: React.FormEvent) {
    e.preventDefault();
    setComponentSubmitting(true);
    setComponentError(null);
    try {
      const c = await formulations.components.create(tenantSlug, versionPublicId, {
        component_type: componentType,
        ingredient_name: componentName,
        quantity_per_dosage_unit: componentQty,
        quantity_unit: componentUnit,
        ...(componentMeaning ? { quantity_expression_public_id: componentMeaning } : {}),
      });
      setComponents((prev) => [...prev, c]);
      setShowComponentForm(false);
      setComponentName("");
      setComponentQty("");
      setComponentMeaning("");
    } catch (err) {
      setComponentError(
        err instanceof ApiError
          ? err.message
          : "Could not add component -- check the quantity is a positive value."
      );
    } finally {
      setComponentSubmitting(false);
    }
  }

  async function handleAddRegimen(e: React.FormEvent) {
    e.preventDefault();
    setRegimenSubmitting(true);
    setRegimenError(null);
    try {
      const r = await formulations.dosingRegimens.create(tenantSlug, versionPublicId, {
        units_per_administration: unitsPerAdmin,
        administrations_per_day: adminPerDay,
        maximum_units_per_day: maxRegimenUnits,
      });
      setRegimens((prev) => [...prev, r]);
      setShowRegimenForm(false);
    } catch (err) {
      setRegimenError(
        err instanceof ApiError
          ? err.message
          : "Could not save dosing regimen -- maximum units/day must be greater than zero."
      );
    } finally {
      setRegimenSubmitting(false);
    }
  }

  if (!tenantSlug) return null;
  if (loading) return <main style={{ maxWidth: 900, margin: "2rem auto" }}>Loading…</main>;
  if (error || !version) {
    return (
      <main style={{ maxWidth: 900, margin: "2rem auto", padding: "0 1rem" }}>
        <p role="alert" style={{ color: "#c0392b" }}>
          {error ?? "Formulation version not found."}
        </p>
      </main>
    );
  }

  const isDraft = version.status === "draft";

  return (
    <main style={{ maxWidth: 900, margin: "2rem auto", padding: "0 1rem" }}>
      <div style={{ marginBottom: "0.5rem" }}>
        <Link
          href={`/formulations/${productPublicId}?tenant=${tenantSlug}`}
          style={{ color: "#045e8f", fontSize: 13, textDecoration: "none" }}
        >
          ← Product detail
        </Link>
      </div>
      <h1 style={{ margin: "0 0 0.25rem" }}>Formulation Version {version.version_number}</h1>
      <p style={{ color: "#66768b", fontSize: 13, marginTop: 0 }}>
        {version.total_dosage_unit_weight} {version.total_dosage_unit_weight_unit} total dosage-unit
        weight <ProvenanceLabel kind="USER_INPUT" />
      </p>
      {version.maximum_dosage_units_per_day && (
        <p style={{ color: "#66768b", fontSize: 13, marginTop: 0 }}>
          Maximum {version.maximum_dosage_units_per_day} dosage units/day <ProvenanceLabel kind="USER_INPUT" />
        </p>
      )}

      <FormulationReviewPanel tenantSlug={tenantSlug} version={version} onChanged={setVersion} />

      {/* Components */}
      <section style={{ marginTop: "1.5rem", border: "1px solid #dce7f4", borderRadius: 8, padding: "1rem" }}>
        <h2 style={{ fontSize: 16, margin: "0 0 0.5rem" }}>Formulation components</h2>
        {components.length > 0 ? (
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13, marginBottom: 8 }}>
            <thead>
              <tr style={{ borderBottom: "1px solid #dce7f4", textAlign: "left" }}>
                <th style={{ padding: "6px 8px" }} scope="col">
                  Ingredient <ProvenanceLabel kind="USER_INPUT" />
                </th>
                <th style={{ padding: "6px 8px" }} scope="col">
                  Type
                </th>
                <th style={{ padding: "6px 8px" }} scope="col">
                  Quantity per unit
                </th>
                <th style={{ padding: "6px 8px" }} scope="col">
                  % w/w <ProvenanceLabel kind="CALCULATED" />
                </th>
              </tr>
            </thead>
            <tbody>
              {components.map((c) => (
                <tr key={c.public_id} style={{ borderBottom: "1px solid #f4f8fe" }}>
                  <td style={{ padding: "6px 8px" }}>{c.ingredient_name}</td>
                  <td style={{ padding: "6px 8px", color: "#66768b" }}>{c.component_type}</td>
                  <td style={{ padding: "6px 8px" }}>
                    {c.quantity_per_dosage_unit}{" "}
                    {c.quantity_expression_public_id ? c.quantity_meaning : c.quantity_unit}
                    {c.unit_recognised === false && (
                      <span data-testid="unit-not-recognised" style={{ display: "block", color: "#8f2c20", fontSize: 12 }}>
                        unit not recognised – cannot be compared
                      </span>
                    )}
                  </td>
                  <td style={{ padding: "6px 8px" }}>
                    {c.percentage_w_w_snapshot != null ? (
                      <PercentValue value={c.percentage_w_w_snapshot} />
                    ) : (
                      "not yet calculated"
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <p style={{ color: "#66768b", fontSize: 13 }}>No components added yet.</p>
        )}
        {/* Components change only while the version is a draft (server and database agree). */}
        {isDraft ? (
          <button onClick={() => setShowComponentForm((s) => !s)} style={smallButtonStyle}>
            {showComponentForm ? "Cancel" : "Add component"}
          </button>
        ) : (
          <p style={{ color: "#66768b", fontSize: 13, margin: 0 }} data-testid="frozen-note">
            Components can be changed only while the version is a draft.
          </p>
        )}
        {isDraft && showComponentForm && (
          <form onSubmit={handleAddComponent} style={{ marginTop: 12 }}>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr 1fr", gap: 8, marginBottom: 8 }}>
              <label style={{ fontSize: 13 }}>
                Type
                <select
                  value={componentType}
                  onChange={(e) => setComponentType(e.target.value as "active" | "inactive")}
                  style={inputStyle}
                >
                  <option value="inactive">Inactive</option>
                  <option value="active">Active</option>
                </select>
              </label>
              <label style={{ fontSize: 13 }}>
                Ingredient name
                <input value={componentName} onChange={(e) => setComponentName(e.target.value)} required style={inputStyle} />
              </label>
              <label style={{ fontSize: 13 }}>
                Quantity per dosage unit
                <input value={componentQty} onChange={(e) => setComponentQty(e.target.value)} required style={inputStyle} />
              </label>
              <label style={{ fontSize: 13 }}>
                Unit
                {/* QA-02: only units REGX can convert or read (the server refuses others). */}
                <select
                  value={componentUnit}
                  onChange={(e) => setComponentUnit(e.target.value)}
                  required
                  style={inputStyle}
                  aria-label="Unit"
                  data-testid="component-unit"
                >
                  {COMPONENT_UNITS.map((u) => (
                    <option key={u.value} value={u.value}>
                      {u.label}
                    </option>
                  ))}
                </select>
              </label>
            </div>
            <div style={{ marginBottom: 8, maxWidth: 360 }}>
              <QuantityMeaningSelect
                tenantSlug={tenantSlug}
                label="What the quantity means"
                value={componentMeaning}
                onChange={(id, meaning) => {
                  setComponentMeaning(id);
                  if (meaning?.family === "percentage") setComponentUnit("percent");
                  else if (meaning?.numerator_unit) setComponentUnit(toUnitOption(meaning.numerator_unit));
                }}
              />
            </div>
            {componentError && (
              <p role="alert" style={{ color: "#c0392b", fontSize: 13, marginBottom: 8 }}>
                {componentError}
              </p>
            )}
            <button type="submit" disabled={componentSubmitting} style={smallButtonStyle}>
              {componentSubmitting ? "Adding…" : "Add"}
            </button>
          </form>
        )}
      </section>

      {/* Dosing regimen */}
      <section style={{ marginTop: "1.5rem", border: "1px solid #dce7f4", borderRadius: 8, padding: "1rem" }}>
        <h2 style={{ fontSize: 16, margin: "0 0 0.5rem" }}>Dosing regimen</h2>
        {regimens.length > 0 ? (
          <ul style={{ paddingLeft: 18, fontSize: 14 }}>
            {regimens.map((r) => (
              <li key={r.public_id}>
                {r.units_per_administration} unit(s) × {r.administrations_per_day}/day, max{" "}
                {r.maximum_units_per_day}/day <ProvenanceLabel kind="USER_INPUT" />
              </li>
            ))}
          </ul>
        ) : (
          <p style={{ color: "#66768b", fontSize: 13 }}>No dosing regimen recorded yet.</p>
        )}
        {isDraft && (
          <button onClick={() => setShowRegimenForm((s) => !s)} style={smallButtonStyle}>
            {showRegimenForm ? "Cancel" : "Add dosing regimen"}
          </button>
        )}
        {isDraft && showRegimenForm && (
          <form onSubmit={handleAddRegimen} style={{ marginTop: 12 }}>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 8, marginBottom: 8 }}>
              <label style={{ fontSize: 13 }}>
                Units per administration
                <input value={unitsPerAdmin} onChange={(e) => setUnitsPerAdmin(e.target.value)} required style={inputStyle} />
              </label>
              <label style={{ fontSize: 13 }}>
                Administrations per day
                <input value={adminPerDay} onChange={(e) => setAdminPerDay(e.target.value)} required style={inputStyle} />
              </label>
              <label style={{ fontSize: 13 }}>
                Maximum units per day
                <input type="number" min={1} max={1000} step="any" value={maxRegimenUnits} onChange={(e) => setMaxRegimenUnits(e.target.value)} required style={inputStyle} />
              </label>
            </div>
            {regimenError && (
              <p role="alert" style={{ color: "#c0392b", fontSize: 13, marginBottom: 8 }}>
                {regimenError}
              </p>
            )}
            <button type="submit" disabled={regimenSubmitting} style={smallButtonStyle}>
              {regimenSubmitting ? "Saving…" : "Save"}
            </button>
          </form>
        )}
      </section>

      <div style={{ marginTop: "1.5rem" }}>
        <Link
          href={`/iid-assessments/preview?tenant=${tenantSlug}&versionId=${version.public_id}`}
          style={{ ...smallButtonStyle, textDecoration: "none", display: "inline-block" }}
        >
          Run IID assessment preview →
        </Link>{" "}
        <Link
          href={`/iig-checklists/executions/new?tenant=${tenantSlug}&formulationVersion=${version.public_id}`}
          style={{ ...smallButtonStyle, textDecoration: "none", display: "inline-block" }}
        >
          Run IIG checklist on this version →
        </Link>
      </div>
    </main>
  );
}

const inputStyle: React.CSSProperties = {
  display: "block",
  width: "100%",
  marginTop: 4,
  padding: "6px 8px",
  border: "1px solid #dce7f4",
  borderRadius: 4,
  boxSizing: "border-box",
};

const smallButtonStyle: React.CSSProperties = {
  background: "#045e8f",
  color: "#fff",
  border: "none",
  borderRadius: 6,
  padding: "6px 14px",
  cursor: "pointer",
  fontWeight: 600,
  fontSize: 13,
};

export default function VersionDetailPage() {
  return (
    <Suspense>
      <VersionDetailInner />
    </Suspense>
  );
}
