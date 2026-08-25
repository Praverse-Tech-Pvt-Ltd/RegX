"use client";

import { useEffect, useState } from "react";
import { dossierBlueprints, type BlueprintProvenance } from "@/lib/api";

/**
 * Where this dossier came from, if anywhere.
 *
 * Renders nothing for a dossier built by hand — an empty "not from a blueprint"
 * line is noise, and most dossiers will not have one.
 *
 * **The name is not always shown.** A blueprint name is tenant-authored free
 * text, and holding `submission_dossiers.view` does not entitle a caller to
 * read the blueprint library. When the API withholds it the provenance is still
 * shown — version number and all — with an explicit note, rather than a blank
 * where a name should be. Retaining the fact while withholding the label is the
 * point: the reader learns the dossier is controlled without learning what the
 * control is called.
 */
export function BlueprintProvenanceLine({
  tenantSlug,
  dossierPublicId,
}: {
  tenantSlug: string;
  dossierPublicId: string;
}) {
  const [provenance, setProvenance] = useState<BlueprintProvenance | null>(null);

  useEffect(() => {
    let cancelled = false;
    // Wrapped in Promise.resolve and a try/catch because this line is
    // supplementary: a dossier that predates blueprints, a caller who cannot
    // read the endpoint, or a client that hands back something unexpected must
    // all end in "no line", never in a dossier workspace that fails to render.
    try {
      Promise.resolve(dossierBlueprints.provenanceForDossier(tenantSlug, dossierPublicId))
        .then((p) => {
          if (!cancelled) setProvenance(p ?? null);
        })
        .catch(() => undefined);
    } catch {
      // Nothing to show.
    }
    return () => {
      cancelled = true;
    };
  }, [tenantSlug, dossierPublicId]);

  if (!provenance?.instantiated_from_blueprint) return null;

  return (
    <span
      data-testid="blueprint-provenance"
      data-restricted={provenance.restricted ? "true" : "false"}
      style={{ fontSize: "0.8rem", color: "#66768b" }}
    >
      {provenance.restricted ? (
        <>
          · Created from a controlled blueprint, version {provenance.version_number}
        </>
      ) : (
        <>
          · Created from <strong style={{ fontWeight: 600 }}>{provenance.blueprint_name}</strong>,
          version {provenance.version_number}
        </>
      )}
    </span>
  );
}
