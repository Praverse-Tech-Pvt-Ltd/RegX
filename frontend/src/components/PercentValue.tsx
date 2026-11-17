import { formatPercentValue } from "@/lib/percent";

/**
 * A calculated percentage shown at 3 decimals, with the exact value as a
 * tooltip (title) and as screen-reader text. Display only: the value itself,
 * and every calculation and stored value, are unchanged.
 */
export function PercentValue({ value }: { value: unknown }) {
  const { display, exact, rounded } = formatPercentValue(value);
  return (
    <span data-testid="percent-value" data-exact={exact} title={`Exact value: ${exact}`}>
      {display}
      {rounded && <span style={SR_ONLY}> (exact value {exact})</span>}
    </span>
  );
}

const SR_ONLY: React.CSSProperties = {
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
