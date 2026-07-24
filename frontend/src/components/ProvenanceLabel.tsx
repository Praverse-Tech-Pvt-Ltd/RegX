/**
 * Every displayed value in the FDA/formulation/IID screens must be
 * visually labeled with where it came from. Never let a viewer confuse a
 * user-entered figure with an FDA-sourced precedent or a system-calculated
 * result -- that ambiguity is exactly what leads to treating precedent
 * data as a recommendation.
 */
export type Provenance = "FDA_SOURCE" | "USER_INPUT" | "CALCULATED" | "REVIEWER_CONFIRMED";

const LABELS: Record<Provenance, string> = {
  FDA_SOURCE: "FDA SOURCE",
  USER_INPUT: "USER INPUT",
  CALCULATED: "CALCULATED",
  REVIEWER_CONFIRMED: "REVIEWER CONFIRMED",
};

const COLOURS: Record<Provenance, string> = {
  FDA_SOURCE: "#1d4ed8",
  USER_INPUT: "#374151",
  CALCULATED: "#7c3aed",
  REVIEWER_CONFIRMED: "#0f766e",
};

export function ProvenanceLabel({ kind }: { kind: Provenance }) {
  return (
    <span
      data-testid="provenance-label"
      data-provenance={kind}
      style={{
        display: "inline-block",
        fontSize: 10,
        fontWeight: 700,
        padding: "1px 6px",
        borderRadius: 3,
        background: COLOURS[kind],
        color: "#fff",
        textTransform: "uppercase",
        letterSpacing: "0.04em",
        marginLeft: 6,
      }}
    >
      {LABELS[kind]}
    </span>
  );
}
