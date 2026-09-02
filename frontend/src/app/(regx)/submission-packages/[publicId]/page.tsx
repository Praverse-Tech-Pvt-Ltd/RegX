"use client";

/**
 * Submission package detail: the builder, the review view and the frozen view.
 *
 * The same page in three modes, because they show the same thing at different
 * stages and splitting them would drift. What changes is which controls are
 * offered, and every one is gated on the server-supplied `permissions` block --
 * advisory only, since every endpoint re-checks.
 *
 * **Reordering is buttons, not drag and drop.** A drag handle without a
 * keyboard equivalent is unusable for anyone not using a mouse, and this is a
 * screen where ordering is part of a permanent record.
 */

import { Suspense, useCallback, useEffect, useState, type FormEvent } from "react";
import { useParams, useSearchParams } from "next/navigation";
import Link from "next/link";
import {
  ApiError,
  submissionPackages,
  type PackageIntegrity,
  type SubmissionPackageDetail,
} from "@/lib/api";
import {
  Checksum,
  FREEZE_CONFIRM_NOTE,
  FrozenMeansNote,
  PackageStatusBadge,
  ScanStatusBadge,
  T,
  Unavailable,
  issueLabel,
} from "../package-primitives";

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

const button: React.CSSProperties = {
  padding: "0.3rem 0.7rem",
  border: `1px solid ${T.line}`,
  borderRadius: "0.35rem",
  backgroundColor: "#fff",
  color: T.blue,
  cursor: "pointer",
  fontSize: "0.82rem",
};

const primary: React.CSSProperties = {
  ...button,
  backgroundColor: T.navy,
  borderColor: T.navy,
  color: "#fff",
  fontWeight: 600,
};

function PackagePage() {
  const params = useParams<{ publicId: string }>();
  const searchParams = useSearchParams();
  const publicId = params.publicId;
  const tenantSlug = searchParams.get("tenant") ?? "";

  const [pkg, setPkg] = useState<SubmissionPackageDetail | null>(null);
  const [integrity, setIntegrity] = useState<PackageIntegrity | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [confirmingFreeze, setConfirmingFreeze] = useState(false);
  const [versionId, setVersionId] = useState("");
  const [logicalPath, setLogicalPath] = useState("");

  const load = useCallback(async () => {
    try {
      const [detail, check] = await Promise.all([
        submissionPackages.get(tenantSlug, publicId),
        submissionPackages.validate(tenantSlug, publicId).catch(() => null),
      ]);
      setPkg(detail);
      setIntegrity(check);
      setError(null);
    } catch {
      setError("Could not load this package.");
    }
  }, [tenantSlug, publicId]);

  useEffect(() => {
    void load();
  }, [load]);

  async function act(fn: () => Promise<unknown>, failure: string) {
    setBusy(true);
    try {
      await fn();
      await load();
      setError(null);
    } catch (err: unknown) {
      await load();
      if (err instanceof ApiError && err.message) setError(err.message);
      else setError(failure);
    } finally {
      setBusy(false);
    }
  }

  if (error && pkg === null) {
    return (
      <main style={{ padding: "1.5rem" }}>
        <h1 style={{ color: T.ink }}>Submission package</h1>
        <p role="alert" data-testid="package-error" style={{ color: "#8c1d1d" }}>
          {error}
        </p>
      </main>
    );
  }

  if (pkg === null) {
    return (
      <main style={{ padding: "1.5rem" }}>
        <h1 style={{ color: T.ink }}>Submission package</h1>
        <p role="status" data-testid="package-loading" style={{ color: T.muted }}>
          Loading package…
        </p>
      </main>
    );
  }

  const perms = pkg.permissions ?? {
    can_view: true,
    can_create: false,
    can_edit: false,
    can_manage_entries: false,
    can_review: false,
    can_freeze: false,
    can_cancel: false,
    can_export: false,
  };
  const isDraft = pkg.status === "draft";
  const isReview = pkg.status === "in_review";
  const isFrozen = pkg.status === "frozen";

  async function addEntry(event: FormEvent) {
    event.preventDefault();
    if (!versionId.trim()) {
      setError("Choose the exact document version to include.");
      return;
    }
    await act(
      () =>
        submissionPackages.addEntry(tenantSlug, publicId, {
          document_version_public_id: versionId.trim(),
          logical_path: logicalPath.trim(),
        }),
      "That document version could not be added."
    );
    setVersionId("");
    setLogicalPath("");
  }

  return (
    <main style={{ padding: "1.5rem", maxWidth: "72rem" }}>
      <header>
        <div style={{ display: "flex", alignItems: "center", gap: "0.6rem", flexWrap: "wrap" }}>
          <h1 style={{ color: T.ink, margin: 0, fontSize: "1.4rem" }}>{pkg.name}</h1>
          <span style={{ color: T.muted, fontSize: "0.9rem" }}>
            revision {pkg.revision_number}
          </span>
          <PackageStatusBadge status={pkg.status} />
        </div>
        {pkg.case_public_id && (
          <p style={{ margin: "0.3rem 0 0", fontSize: "0.85rem" }}>
            <Link
              data-testid="package-case-link"
              href={`/regulatory-cases/${pkg.case_public_id}?tenant=${tenantSlug}`}
              style={{ color: T.blue }}
            >
              Back to the case
            </Link>
          </p>
        )}
        {isFrozen && <FrozenMeansNote />}
      </header>

      {error && (
        <p
          role="alert"
          data-testid="package-error"
          style={{
            marginTop: "0.8rem",
            padding: "0.5rem 0.7rem",
            border: "1px solid #f0c8c8",
            borderRadius: "0.35rem",
            backgroundColor: "#fdecec",
            color: "#8c1d1d",
            fontSize: "0.85rem",
          }}
        >
          {error}
        </p>
      )}

      {/* ---------------------------------------------------------------- */}
      {isFrozen && (
        <section aria-labelledby="manifest-heading" style={{ marginTop: "1.5rem" }}>
          <h2 id="manifest-heading" style={{ fontSize: "1.05rem", color: T.ink }}>
            Frozen manifest
          </h2>
          <dl
            data-testid="manifest-summary"
            style={{ display: "grid", gridTemplateColumns: "auto 1fr", gap: "0.3rem 1rem", margin: 0 }}
          >
            <dt style={{ color: T.muted, fontSize: "0.8rem" }}>Manifest SHA-256</dt>
            <dd style={{ margin: 0 }}>
              <Checksum value={pkg.manifest_checksum} testId="manifest-checksum" />
            </dd>
            <dt style={{ color: T.muted, fontSize: "0.8rem" }}>Entries</dt>
            <dd style={{ margin: 0, fontSize: "0.85rem" }}>{pkg.entry_count}</dd>
            <dt style={{ color: T.muted, fontSize: "0.8rem" }}>Frozen</dt>
            <dd style={{ margin: 0, fontSize: "0.85rem" }}>{pkg.frozen_at}</dd>
          </dl>
          <div style={{ display: "flex", gap: "0.4rem", marginTop: "0.7rem", flexWrap: "wrap" }}>
            {perms.can_export && (
              <a
                data-testid="export-zip"
                href={`${submissionPackages.exportUrl(publicId)}`}
                style={primary}
              >
                Export internal ZIP
              </a>
            )}
            {perms.can_create && (
              <button
                type="button"
                data-testid="clone-package"
                disabled={busy}
                onClick={() =>
                  act(
                    () => submissionPackages.clone(tenantSlug, publicId),
                    "This package could not be cloned."
                  )
                }
                style={button}
              >
                Clone as new draft
              </button>
            )}
          </div>
        </section>
      )}

      {/* ---------------------------------------------------------------- */}
      {integrity && !isFrozen && (
        <section aria-labelledby="integrity-heading" style={{ marginTop: "1.5rem" }}>
          <h2 id="integrity-heading" style={{ fontSize: "1.05rem", color: T.ink }}>
            Internal package integrity
          </h2>
          {integrity.valid ? (
            <p data-testid="integrity-ok" style={{ fontSize: "0.85rem", color: "#1b5e34" }}>
              No integrity issues. This checks that the package can be exported — it is
              not a regulatory or completeness assessment.
            </p>
          ) : (
            <ul data-testid="integrity-issues" style={{ paddingLeft: "1.1rem", margin: 0 }}>
              {integrity.issues.map((issue, i) => (
                <li
                  key={`${issue.code}-${issue.entry_public_id ?? i}`}
                  style={{ fontSize: "0.85rem", color: "#8a4b06" }}
                >
                  {issueLabel(issue.code)}
                </li>
              ))}
            </ul>
          )}
        </section>
      )}

      {/* ---------------------------------------------------------------- */}
      <section aria-labelledby="entries-heading" style={{ marginTop: "1.75rem" }}>
        <h2 id="entries-heading" style={{ fontSize: "1.05rem", color: T.ink }}>
          Package contents
        </h2>
        {pkg.entries.length === 0 ? (
          <p data-testid="entries-empty" style={{ color: T.muted, fontSize: "0.85rem" }}>
            Nothing has been added to this package yet.
          </p>
        ) : (
          <div
            role="region"
            aria-label="Package contents table"
            tabIndex={0}
            style={{ overflowX: "auto", border: `1px solid ${T.line}`, borderRadius: "0.5rem" }}
          >
            <table style={{ borderCollapse: "collapse", width: "100%" }}>
              <thead>
                <tr>
                  <th scope="col" style={headCell}>
                    Order
                  </th>
                  <th scope="col" style={headCell}>
                    Path
                  </th>
                  <th scope="col" style={headCell}>
                    Document
                  </th>
                  <th scope="col" style={headCell}>
                    Version
                  </th>
                  <th scope="col" style={headCell}>
                    Checksum
                  </th>
                  <th scope="col" style={headCell}>
                    State
                  </th>
                  {isDraft && perms.can_manage_entries && (
                    <th scope="col" style={headCell}>
                      Actions
                    </th>
                  )}
                </tr>
              </thead>
              <tbody data-testid="entry-rows">
                {pkg.entries.map((entry, index) => (
                  <tr key={entry.public_id}>
                    <td style={cell}>{index + 1}</td>
                    <th scope="row" style={{ ...cell, fontWeight: 500 }}>
                      {entry.logical_path ? `${entry.logical_path}/` : ""}
                      {entry.export_filename}
                    </th>
                    <td style={cell}>
                      {entry.document ? (
                        entry.document.title
                      ) : (
                        <Unavailable testId="entry-document-unavailable" />
                      )}
                    </td>
                    <td style={cell}>
                      {entry.document ? (
                        <span data-testid="entry-version">v{entry.document.version_number}</span>
                      ) : (
                        <Unavailable />
                      )}
                    </td>
                    <td style={cell}>
                      {entry.document ? (
                        <Checksum value={entry.document.checksum_sha256} testId="entry-checksum" />
                      ) : (
                        <Unavailable />
                      )}
                    </td>
                    <td style={cell}>
                      {entry.document ? (
                        <ScanStatusBadge status={entry.document.scan_status} />
                      ) : (
                        <Unavailable />
                      )}
                    </td>
                    {isDraft && perms.can_manage_entries && (
                      <td style={cell}>
                        <span style={{ display: "flex", gap: "0.3rem" }}>
                          <button
                            type="button"
                            data-testid="entry-move-up"
                            aria-label={`Move ${entry.export_filename} earlier`}
                            disabled={busy || index === 0}
                            onClick={() =>
                              act(
                                () =>
                                  submissionPackages.reorderEntry(
                                    tenantSlug,
                                    publicId,
                                    entry.public_id,
                                    Math.max(0, entry.sequence - 1)
                                  ),
                                "That entry could not be reordered."
                              )
                            }
                            style={button}
                          >
                            ↑ Earlier
                          </button>
                          <button
                            type="button"
                            data-testid="entry-remove"
                            aria-label={`Remove ${entry.export_filename}`}
                            disabled={busy}
                            onClick={() =>
                              act(
                                () =>
                                  submissionPackages.removeEntry(
                                    tenantSlug,
                                    publicId,
                                    entry.public_id
                                  ),
                                "That entry could not be removed."
                              )
                            }
                            style={button}
                          >
                            Remove
                          </button>
                        </span>
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {/* ---------------------------------------------------------------- */}
      {isDraft && perms.can_manage_entries && (
        <section aria-labelledby="add-heading" style={{ marginTop: "1.75rem" }}>
          <h2 id="add-heading" style={{ fontSize: "1.05rem", color: T.ink }}>
            Add a document version
          </h2>
          <p style={{ fontSize: "0.8rem", color: T.muted, maxWidth: "60ch", marginTop: 0 }}>
            A package holds exact versions. The version you name here is the one that will
            be exported, whatever is uploaded to that document later.
          </p>
          <form onSubmit={addEntry} style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
            <label style={{ fontSize: "0.82rem", color: T.text }}>
              Document version ID
              <br />
              <input
                data-testid="entry-version-input"
                value={versionId}
                onChange={(e) => setVersionId(e.target.value)}
                style={{ padding: "0.3rem", minWidth: "22rem" }}
              />
            </label>
            <label style={{ fontSize: "0.82rem", color: T.text }}>
              Logical path (optional)
              <br />
              <input
                data-testid="entry-path-input"
                value={logicalPath}
                onChange={(e) => setLogicalPath(e.target.value)}
                placeholder="01-cover"
                style={{ padding: "0.3rem", minWidth: "12rem" }}
              />
            </label>
            <button type="submit" data-testid="entry-add" disabled={busy} style={primary}>
              Add exact version
            </button>
          </form>
        </section>
      )}

      {/* ---------------------------------------------------------------- */}
      <section aria-labelledby="lifecycle-heading" style={{ marginTop: "1.75rem" }}>
        <h2 id="lifecycle-heading" style={{ fontSize: "1.05rem", color: T.ink }}>
          Package state
        </h2>
        <div style={{ display: "flex", gap: "0.4rem", flexWrap: "wrap" }}>
          {isDraft && perms.can_review && (
            <button
              type="button"
              data-testid="submit-for-review"
              disabled={busy}
              onClick={() =>
                act(
                  () => submissionPackages.submitForReview(tenantSlug, publicId),
                  "This package could not be submitted for review."
                )
              }
              style={primary}
            >
              Submit for review
            </button>
          )}
          {isReview && perms.can_review && (
            <button
              type="button"
              data-testid="return-to-draft"
              disabled={busy}
              onClick={() =>
                act(
                  () => submissionPackages.returnToDraft(tenantSlug, publicId),
                  "This package could not be returned to draft."
                )
              }
              style={button}
            >
              Return to draft
            </button>
          )}
          {isReview && perms.can_freeze && !confirmingFreeze && (
            <button
              type="button"
              data-testid="freeze-package"
              disabled={busy}
              onClick={() => setConfirmingFreeze(true)}
              style={primary}
            >
              Freeze package
            </button>
          )}
          {!pkg.cancelled_at && !isFrozen && perms.can_cancel && (
            <button
              type="button"
              data-testid="cancel-package"
              disabled={busy}
              onClick={() =>
                act(
                  () => submissionPackages.cancel(tenantSlug, publicId),
                  "This package could not be cancelled."
                )
              }
              style={button}
            >
              Cancel package
            </button>
          )}
        </div>

        {confirmingFreeze && (
          <div
            data-testid="freeze-confirm"
            role="group"
            aria-label="Confirm freeze"
            style={{
              marginTop: "0.7rem",
              padding: "0.7rem",
              border: `1px solid ${T.line}`,
              borderRadius: "0.4rem",
              backgroundColor: T.panel,
            }}
          >
            <p style={{ margin: "0 0 0.5rem", fontSize: "0.85rem", color: T.text, maxWidth: "62ch" }}>
              {FREEZE_CONFIRM_NOTE}
            </p>
            <span style={{ display: "flex", gap: "0.4rem" }}>
              <button
                type="button"
                data-testid="freeze-confirm-yes"
                disabled={busy}
                onClick={() => {
                  setConfirmingFreeze(false);
                  void act(
                    () => submissionPackages.freeze(tenantSlug, publicId),
                    "This package could not be frozen."
                  );
                }}
                style={primary}
              >
                Yes, freeze
              </button>
              <button
                type="button"
                data-testid="freeze-confirm-no"
                onClick={() => setConfirmingFreeze(false)}
                style={button}
              >
                Cancel
              </button>
            </span>
          </div>
        )}
      </section>
    </main>
  );
}

export default function Page() {
  return (
    <Suspense fallback={<p style={{ padding: "1.5rem" }}>Loading…</p>}>
      <PackagePage />
    </Suspense>
  );
}
