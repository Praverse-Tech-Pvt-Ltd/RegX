"use client";

import { Suspense, useEffect, useRef, useState } from "react";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import {
  documents,
  type Document,
  type DocumentVersion,
  type ProcessingStatus,
  type ScanStatus,
  ApiError,
} from "@/lib/api";

function scanLabel(s: ScanStatus) {
  const map: Record<ScanStatus, string> = {
    pending: "Scan pending",
    clean: "Clean",
    infected: "Infected",
    scan_failed: "Scan failed",
    scanner_unavailable: "Scanner unavailable",
    quarantined: "Quarantined",
  };
  return map[s] ?? s;
}

function scanColour(s: ScanStatus) {
  if (s === "clean") return "#166534";
  if (s === "quarantined" || s === "infected") return "#991b1b";
  if (s === "scan_failed" || s === "scanner_unavailable") return "#92400e";
  return "#374151";
}

function processingLabel(s: ProcessingStatus) {
  const map: Record<ProcessingStatus, string> = {
    pending: "Queued",
    processing: "Processing…",
    complete: "Complete",
    failed: "Failed",
    skipped: "Skipped",
  };
  return map[s] ?? s;
}

function processingColour(s: ProcessingStatus) {
  if (s === "complete") return "#166534";
  if (s === "failed") return "#991b1b";
  if (s === "processing") return "#1d4ed8";
  return "#374151";
}

function fmt(bytes: number) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

function VersionRow({
  v,
  isCurrent,
  tenantSlug,
  docId,
}: {
  v: DocumentVersion;
  isCurrent: boolean;
  tenantSlug: string;
  docId: string;
}) {
  const [status, setStatus] = useState<{ scan_status: ScanStatus; processing_status: ProcessingStatus } | null>(null);
  const [showLocators, setShowLocators] = useState(false);
  const [locators, setLocators] = useState<{ public_id: string; locator_type: string; display_label: string; ordering: number }[]>([]);
  const [loadingLocators, setLoadingLocators] = useState(false);
  const [locatorError, setLocatorError] = useState<string | null>(null);

  useEffect(() => {
    if (v.processing_status !== "complete") {
      const id = setInterval(() => {
        documents.versionStatus(tenantSlug, docId, v.public_id).then(setStatus).catch(() => {});
      }, 5000);
      return () => clearInterval(id);
    }
  }, [tenantSlug, docId, v.public_id, v.processing_status]);

  const effectiveScan = status?.scan_status ?? v.scan_status;
  const effectiveProcessing = status?.processing_status ?? v.processing_status;

  function loadLocators() {
    if (locators.length > 0) { setShowLocators(!showLocators); return; }
    setLoadingLocators(true);
    setLocatorError(null);
    documents
      .locators(tenantSlug, docId, v.public_id)
      .then((resp) => { setLocators(resp.results); setShowLocators(true); })
      .catch((err) => setLocatorError(err instanceof ApiError ? err.message : "Failed to load."))
      .finally(() => setLoadingLocators(false));
  }

  return (
    <div
      style={{
        border: `1px solid ${isCurrent ? "#bfdbfe" : "#e5e7eb"}`,
        borderRadius: 8,
        padding: "1rem",
        marginBottom: "0.75rem",
        background: isCurrent ? "#eff6ff" : "#fff",
      }}
    >
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
        <div>
          <span style={{ fontWeight: 600 }}>Version {v.version_number}</span>
          {isCurrent && (
            <span style={{ marginLeft: 8, fontSize: 11, padding: "1px 6px", background: "#1d4ed8", color: "#fff", borderRadius: 4 }}>
              current
            </span>
          )}
          <div style={{ fontSize: 13, color: "#6b7280", marginTop: 4 }}>
            {v.original_filename} &bull; {fmt(v.size_bytes)} &bull;{" "}
            {new Date(v.uploaded_at).toLocaleString()}
          </div>
        </div>
        <div style={{ display: "flex", gap: 8, flexShrink: 0 }}>
          <span
            style={{
              fontSize: 11,
              padding: "2px 7px",
              borderRadius: 4,
              background: scanColour(effectiveScan),
              color: "#fff",
              fontWeight: 600,
            }}
          >
            {scanLabel(effectiveScan)}
          </span>
          <span
            style={{
              fontSize: 11,
              padding: "2px 7px",
              borderRadius: 4,
              background: processingColour(effectiveProcessing),
              color: "#fff",
              fontWeight: 600,
            }}
          >
            {processingLabel(effectiveProcessing)}
          </span>
        </div>
      </div>

      {effectiveProcessing === "complete" && effectiveScan !== "quarantined" && (
        <div style={{ marginTop: "0.75rem" }}>
          <button
            onClick={loadLocators}
            style={{
              fontSize: 12,
              padding: "4px 10px",
              borderRadius: 4,
              border: "1px solid #d1d5db",
              cursor: "pointer",
              background: "#f9fafb",
            }}
          >
            {loadingLocators ? "Loading…" : showLocators ? "Hide structure" : "Show structure"}
          </button>
          {locatorError && <span style={{ color: "#b91c1c", fontSize: 12, marginLeft: 8 }}>{locatorError}</span>}
          {showLocators && locators.length > 0 && (
            <ul style={{ marginTop: "0.5rem", paddingLeft: "1.25rem", fontSize: 13, color: "#374151" }}>
              {locators.slice(0, 20).map((loc) => (
                <li key={loc.public_id} style={{ marginBottom: 2 }}>
                  <span style={{ color: "#6b7280", fontStyle: "italic", textTransform: "capitalize" }}>{loc.locator_type}</span>
                  {" "}{loc.display_label}
                </li>
              ))}
              {locators.length > 20 && (
                <li style={{ color: "#6b7280" }}>…and {locators.length - 20} more</li>
              )}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}

function DocumentDetailPageInner() {
  const { publicId } = useParams<{ publicId: string }>();
  const searchParams = useSearchParams();
  const tenantSlug = searchParams.get("tenant") ?? "";
  const router = useRouter();

  const [doc, setDoc] = useState<Document | null>(null);
  const [versions, setVersions] = useState<DocumentVersion[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [archiving, setArchiving] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  // New version upload
  const [uploadingVersion, setUploadingVersion] = useState(false);
  const [versionFile, setVersionFile] = useState<File | null>(null);
  const [versionError, setVersionError] = useState<string | null>(null);
  const versionInputRef = useRef<HTMLInputElement>(null);

  async function load() {
    if (!tenantSlug) return;
    try {
      const [docData, verData] = await Promise.all([
        documents.get(tenantSlug, publicId),
        documents.versions(tenantSlug, publicId),
      ]);
      setDoc(docData);
      setVersions(verData.results);
    } catch (err) {
      if (err instanceof ApiError && err.status === 403) {
        router.push(`/signin?next=${encodeURIComponent(window.location.pathname + window.location.search)}`);
      } else {
        setError("Failed to load document.");
      }
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    if (!tenantSlug) { router.push("/tenants"); return; }
    load();
  }, [tenantSlug, publicId]); // eslint-disable-line react-hooks/exhaustive-deps

  async function handleArchive() {
    if (!doc) return;
    setArchiving(true);
    setActionError(null);
    try {
      const updated = await documents.archive(tenantSlug, publicId);
      setDoc(updated);
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : "Action failed.");
    } finally {
      setArchiving(false);
    }
  }

  async function handleRestore() {
    if (!doc) return;
    setArchiving(true);
    setActionError(null);
    try {
      const updated = await documents.restore(tenantSlug, publicId);
      setDoc(updated);
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : "Action failed.");
    } finally {
      setArchiving(false);
    }
  }

  async function handleUploadVersion(e: React.FormEvent) {
    e.preventDefault();
    if (!versionFile) return;
    setUploadingVersion(true);
    setVersionError(null);
    try {
      const newVersion = await documents.uploadVersion(tenantSlug, publicId, versionFile);
      setVersions((prev) => [newVersion, ...prev]);
      setVersionFile(null);
      if (versionInputRef.current) versionInputRef.current.value = "";
      await load();
    } catch (err) {
      setVersionError(err instanceof ApiError ? err.message : "Upload failed.");
    } finally {
      setUploadingVersion(false);
    }
  }

  if (loading) return <main style={{ maxWidth: 900, margin: "2rem auto", padding: "0 1rem" }}><p>Loading…</p></main>;
  if (error) return <main style={{ maxWidth: 900, margin: "2rem auto", padding: "0 1rem" }}><p role="alert" style={{ color: "#b91c1c" }}>{error}</p></main>;
  if (!doc) return null;

  return (
    <main style={{ maxWidth: 900, margin: "2rem auto", padding: "0 1rem" }}>
      <div style={{ marginBottom: "0.5rem" }}>
        <Link
          href={`/documents?tenant=${tenantSlug}`}
          style={{ color: "#1d4ed8", fontSize: 13, textDecoration: "none" }}
        >
          ← All documents
        </Link>
      </div>

      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: "1.5rem" }}>
        <div>
          <h1 style={{ margin: "0 0 4px" }}>{doc.title}</h1>
          <span style={{ fontSize: 12, color: "#6b7280", textTransform: "uppercase" }}>
            {doc.document_type}
          </span>
          {" "}
          <span
            style={{
              fontSize: 11,
              padding: "2px 6px",
              borderRadius: 4,
              background: doc.status === "archived" ? "#f3f4f6" : "#dcfce7",
              color: doc.status === "archived" ? "#374151" : "#166534",
              fontWeight: 600,
            }}
          >
            {doc.status}
          </span>
        </div>

        <div style={{ display: "flex", gap: 8 }}>
          {doc.status === "active" ? (
            <button
              onClick={handleArchive}
              disabled={archiving}
              style={{
                padding: "7px 14px",
                borderRadius: 6,
                border: "1px solid #d1d5db",
                cursor: archiving ? "not-allowed" : "pointer",
                fontSize: 13,
              }}
            >
              {archiving ? "Archiving…" : "Archive"}
            </button>
          ) : (
            <button
              onClick={handleRestore}
              disabled={archiving}
              style={{
                padding: "7px 14px",
                borderRadius: 6,
                border: "1px solid #d1d5db",
                cursor: archiving ? "not-allowed" : "pointer",
                fontSize: 13,
              }}
            >
              {archiving ? "Restoring…" : "Restore"}
            </button>
          )}
        </div>
      </div>

      {actionError && <p role="alert" style={{ color: "#b91c1c", fontSize: 13 }}>{actionError}</p>}

      {doc.status === "active" && (
        <section style={{ marginBottom: "2rem" }}>
          <h2 style={{ fontSize: 16, marginBottom: "0.75rem" }}>Upload new version</h2>
          <form onSubmit={handleUploadVersion} style={{ display: "flex", gap: 8, alignItems: "center" }}>
            <input
              ref={versionInputRef}
              type="file"
              aria-label="New version file"
              accept=".pdf,.docx,.xlsx,.pptx"
              onChange={(e) => setVersionFile(e.target.files?.[0] ?? null)}
              style={{ fontSize: 13 }}
            />
            <button
              type="submit"
              disabled={uploadingVersion || !versionFile}
              style={{
                padding: "6px 14px",
                borderRadius: 6,
                border: "none",
                background: uploadingVersion || !versionFile ? "#93c5fd" : "#1d4ed8",
                color: "#fff",
                fontWeight: 600,
                cursor: uploadingVersion || !versionFile ? "not-allowed" : "pointer",
                fontSize: 13,
              }}
            >
              {uploadingVersion ? "Uploading…" : "Upload"}
            </button>
          </form>
          {versionError && <p role="alert" style={{ color: "#b91c1c", fontSize: 13, marginTop: 4 }}>{versionError}</p>}
        </section>
      )}

      <section>
        <h2 style={{ fontSize: 16, marginBottom: "0.75rem" }}>
          Versions ({versions.length})
        </h2>
        {versions.length === 0 && <p style={{ color: "#6b7280" }}>No versions found.</p>}
        {versions.map((v) => (
          <VersionRow
            key={v.public_id}
            v={v}
            isCurrent={doc.current_version?.public_id === v.public_id}
            tenantSlug={tenantSlug}
            docId={publicId}
          />
        ))}
      </section>
    </main>
  );
}

export default function DocumentDetailPage() {
  return (
    <Suspense>
      <DocumentDetailPageInner />
    </Suspense>
  );
}
