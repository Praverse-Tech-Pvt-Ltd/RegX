"use client";

import { useEffect, useState } from "react";
import { fdaData, type QuantityMeaning } from "@/lib/api";

/**
 * Chooses what a quantity means (controlled units, increment 4): per dosage
 * unit (the default, as before), per stated volume, or a percentage. Only the
 * meanings the reviewed unit list puts in force are offered; with none in
 * force, only the default is.
 */
export function QuantityMeaningSelect({
  tenantSlug,
  label,
  value,
  onChange,
}: {
  tenantSlug: string;
  label: string;
  value: string;
  onChange: (publicId: string, meaning: QuantityMeaning | null) => void;
}) {
  const [meanings, setMeanings] = useState<QuantityMeaning[]>([]);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    if (!tenantSlug) return;
    let cancelled = false;
    fdaData
      .meanings(tenantSlug)
      .then((r) => !cancelled && setMeanings(r.meanings))
      .catch(() => !cancelled && setFailed(true));
    return () => {
      cancelled = true;
    };
  }, [tenantSlug]);

  const selected = meanings.find((m) => m.public_id === value) ?? null;
  const hint = selected
    ? selected.family === "percentage"
      ? "Enter the amount with unit “percent”."
      : `Enter the amount in “${selected.numerator_unit}”.`
    : null;

  return (
    <label style={{ fontSize: 13 }}>
      {label}
      <select
        value={value}
        onChange={(e) =>
          onChange(e.target.value, meanings.find((m) => m.public_id === e.target.value) ?? null)
        }
        style={{ display: "block", width: "100%", marginTop: 4, padding: "6px 8px", border: "1px solid #dce7f4", borderRadius: 4 }}
      >
        <option value="">Per dosage unit (in the unit entered)</option>
        {meanings.map((m) => (
          <option key={m.public_id} value={m.public_id}>
            {m.label}
          </option>
        ))}
      </select>
      {hint && <span style={{ display: "block", fontSize: 12, color: "#66768b", marginTop: 2 }}>{hint}</span>}
      {failed && (
        <span style={{ display: "block", fontSize: 12, color: "#8a5a10", marginTop: 2 }}>
          Meanings could not be loaded; the amount is read per dosage unit.
        </span>
      )}
    </label>
  );
}
