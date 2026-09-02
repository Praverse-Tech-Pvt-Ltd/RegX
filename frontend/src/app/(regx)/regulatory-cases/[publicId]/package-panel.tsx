"use client";

/**
 * The packages belonging to one regulatory case.
 *
 * **Creation is always deliberate.** Nothing here creates a package
 * automatically, and nothing syncs dossier contents into one: a package is an
 * assembly somebody decided on, which is the only way a frozen manifest means
 * anything.
 */

import { useCallback, useEffect, useState, type FormEvent } from "react";
import Link from "next/link";
import { ApiError, submissionPackages, type SubmissionPackage } from "@/lib/api";
import {
  Checksum,
  PackageStatusBadge,
  T,
} from "../../submission-packages/package-primitives";

export function PackagePanel({
  tenantSlug,
  casePublicId,
  caseTerminal,
}: {
  tenantSlug: string;
  casePublicId: string;
  caseTerminal: boolean;
}) {
  const [packages, setPackages] = useState<SubmissionPackage[] | null>(null);
  const [restricted, setRestricted] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const page = await submissionPackages.listForCase(tenantSlug, casePublicId);
      setPackages(page.results);
      setRestricted(false);
      setError(null);
    } catch (err: unknown) {
      if (err instanceof ApiError && (err.status === 403 || err.status === 404)) {
        // Not an error state: the caller may simply not hold package view.
        setPackages(null);
        setRestricted(true);
        setError(null);
        return;
      }
      setError("Could not load packages for this case.");
    }
  }, [tenantSlug, casePublicId]);

  useEffect(() => {
    void load();
  }, [load]);

  async function create(event: FormEvent) {
    event.preventDefault();
    if (!name.trim()) {
      setError("Give the package a name.");
      return;
    }
    setBusy(true);
    try {
      await submissionPackages.create(tenantSlug, casePublicId, { name: name.trim() });
      setName("");
      setCreating(false);
      await load();
      setError(null);
    } catch (err: unknown) {
      if (err instanceof ApiError && err.message) setError(err.message);
      else setError("That package could not be created.");
    } finally {
      setBusy(false);
    }
  }

  if (restricted) {
    return (
      <p data-testid="packages-restricted" style={{ color: T.muted, fontSize: "0.85rem" }}>
        You do not have permission to view submission packages.
      </p>
    );
  }

  return (
    <div>
      {error && (
        <p role="alert" data-testid="packages-error" style={{ color: "#8c1d1d", fontSize: "0.85rem" }}>
          {error}
        </p>
      )}

      {packages === null ? (
        <p role="status" data-testid="packages-loading" style={{ color: T.muted, fontSize: "0.85rem" }}>
          Loading packages…
        </p>
      ) : packages.length === 0 ? (
        <p data-testid="packages-empty" style={{ color: T.muted, fontSize: "0.85rem" }}>
          No packages have been assembled for this case yet.
        </p>
      ) : (
        <div
          role="region"
          aria-label="Case packages table"
          tabIndex={0}
          style={{ overflowX: "auto", border: `1px solid ${T.line}`, borderRadius: "0.5rem" }}
        >
          <table style={{ borderCollapse: "collapse", width: "100%" }}>
            <thead>
              <tr>
                {["Package", "Revision", "State", "Entries", "Manifest", "Frozen"].map((h) => (
                  <th
                    key={h}
                    scope="col"
                    style={{
                      padding: "0.45rem 0.6rem",
                      borderBottom: `1px solid ${T.line}`,
                      backgroundColor: T.panel,
                      color: T.ink,
                      fontSize: "0.8rem",
                      textAlign: "left",
                      whiteSpace: "nowrap",
                    }}
                  >
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody data-testid="package-rows">
              {packages.map((p) => (
                <tr key={p.public_id}>
                  <th
                    scope="row"
                    style={{
                      padding: "0.45rem 0.6rem",
                      borderBottom: `1px solid ${T.line}`,
                      fontSize: "0.85rem",
                      textAlign: "left",
                      fontWeight: 600,
                    }}
                  >
                    <Link
                      data-testid="package-link"
                      href={`/submission-packages/${p.public_id}?tenant=${tenantSlug}`}
                      style={{ color: T.blue }}
                    >
                      {p.name}
                    </Link>
                  </th>
                  <td style={{ padding: "0.45rem 0.6rem", borderBottom: `1px solid ${T.line}`, fontSize: "0.85rem" }}>
                    {p.revision_number}
                  </td>
                  <td style={{ padding: "0.45rem 0.6rem", borderBottom: `1px solid ${T.line}` }}>
                    <PackageStatusBadge status={p.status} />
                  </td>
                  <td style={{ padding: "0.45rem 0.6rem", borderBottom: `1px solid ${T.line}`, fontSize: "0.85rem" }}>
                    {p.entry_count}
                  </td>
                  <td style={{ padding: "0.45rem 0.6rem", borderBottom: `1px solid ${T.line}` }}>
                    {p.manifest_checksum ? (
                      <Checksum value={p.manifest_checksum} testId="row-manifest-checksum" />
                    ) : (
                      <span style={{ color: T.muted, fontSize: "0.8rem" }}>—</span>
                    )}
                  </td>
                  <td style={{ padding: "0.45rem 0.6rem", borderBottom: `1px solid ${T.line}`, fontSize: "0.8rem", color: T.muted }}>
                    {p.frozen_at ?? ""}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {!caseTerminal && (
        <div style={{ marginTop: "0.7rem" }}>
          {creating ? (
            <form onSubmit={create} style={{ display: "flex", gap: "0.4rem", flexWrap: "wrap" }}>
              <label style={{ fontSize: "0.82rem", color: T.text }}>
                Package name
                <br />
                <input
                  data-testid="new-package-name"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  style={{ padding: "0.3rem", minWidth: "16rem" }}
                />
              </label>
              <button
                type="submit"
                data-testid="create-package-submit"
                disabled={busy}
                style={{
                  padding: "0.3rem 0.7rem",
                  border: `1px solid ${T.navy}`,
                  borderRadius: "0.35rem",
                  backgroundColor: T.navy,
                  color: "#fff",
                  fontWeight: 600,
                  cursor: "pointer",
                  fontSize: "0.82rem",
                }}
              >
                Create package
              </button>
              <button
                type="button"
                data-testid="create-package-cancel"
                onClick={() => setCreating(false)}
                style={{
                  padding: "0.3rem 0.7rem",
                  border: `1px solid ${T.line}`,
                  borderRadius: "0.35rem",
                  backgroundColor: "#fff",
                  color: T.blue,
                  cursor: "pointer",
                  fontSize: "0.82rem",
                }}
              >
                Cancel
              </button>
            </form>
          ) : (
            <button
              type="button"
              data-testid="create-package"
              onClick={() => setCreating(true)}
              style={{
                padding: "0.3rem 0.7rem",
                border: `1px solid ${T.line}`,
                borderRadius: "0.35rem",
                backgroundColor: "#fff",
                color: T.blue,
                cursor: "pointer",
                fontSize: "0.82rem",
              }}
            >
              Create package
            </button>
          )}
        </div>
      )}
    </div>
  );
}
