/**
 * Display-only rounding for calculated percentages.
 *
 * The backend sends Decimal values as strings (for example
 * "142.8571428571428571428571429"). Shown in full they are unreadable; rounded
 * through a JS number they could drift. This rounds the decimal *string* to a
 * fixed number of places, half away from zero, with BigInt arithmetic, so no
 * binary floating point is involved. The exact string is kept for the tooltip.
 * Nothing here changes a calculation or a stored value.
 */

export const PERCENT_DISPLAY_PLACES = 3;

/** True for the calculation units that are percentages (percent_w_w, percent_of_potency, ...). */
export function isPercentUnit(unit: unknown): boolean {
  return typeof unit === "string" && unit.startsWith("percent");
}

export interface FormattedPercent {
  /** Rounded to `places`, fixed width (e.g. "14.000"). */
  display: string;
  /** The value exactly as received. */
  exact: string;
  /** False when `display` is the exact value (only trailing zeros added). */
  rounded: boolean;
}

export function formatPercentValue(value: unknown, places = PERCENT_DISPLAY_PLACES): FormattedPercent {
  const exact = String(value ?? "").trim();
  const m = /^([+-]?)(\d+)(?:\.(\d*))?$/.exec(exact);
  if (!m) return { display: exact, exact, rounded: false };
  const [, sign, intPart, fracRaw = ""] = m;
  const frac = fracRaw.padEnd(places + 1, "0");
  let scaled = BigInt(intPart + frac.slice(0, places));
  if (Number(frac[places]) >= 5) scaled += BigInt(1);
  const digits = scaled.toString().padStart(places + 1, "0");
  const whole = digits.slice(0, digits.length - places);
  const display = `${sign === "-" && scaled !== BigInt(0) ? "-" : ""}${whole}${places ? "." + digits.slice(-places) : ""}`;
  const rounded = /[1-9]/.test(fracRaw.slice(places));
  return { display, exact, rounded };
}
