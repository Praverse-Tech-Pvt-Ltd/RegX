"use client";

import { Suspense, useEffect, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { documents, type Document, type DocumentType, ApiError } from "@/lib/api";
import Link from "next/link";

const ALLOWED_TYPES: DocumentType[] = ["pdf", "docx", "xlsx", "pptx"];
const MIME_FOR_TYPE: Record<DocumentType, string> = {
  pdf: "application/pdf",
  docx: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  xlsx: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  pptx: "application/vnd.openxmlformats-officedocument.presentationml.presentation",
};

function scanBadge(scan: string) {
  const colours: Record<string, string> = {
    clean: "#166534",
    quarantined: "#991b1b",
    infected: "#991b1b",
    scan_failed: "#92400e",
    scanner_unavailable: "#92400e",
    pending: "#374151",
  };
  return (
    <span
      style={{
        fontSize: 11,
        fontWeight: 600,
        padding: "2px 6px",
        borderRadius: 4,
        background: colours[scan] ?? "#374151",
        color: "#fff",
        textTransform: "uppercase",
        letterSpacing: "0.05em",
      }}
    >
      {scan.replace("_", " ")}
    </span>
  );
}

function processingLabel(status: string) {
  const map: Record<string, string> = {
    pending: "queued",
    processing: "processing…",
    complete: "ready",
    failed: "failed",
    skipped: "skipped",
  };
  return map[status] ?? status;
}

function DocumentsPageInner() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const tenantSlug = searchParams.get("tenant") ?? "";

  const [docs, setDocs] = useState<Document[]>([]);
  const [count, setCount] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Upload dialog state
  const [showUpload, setShowUpload] = useState(false);
  const [uploadTitle, setUploadTitle] = useState("");
  const [uploadType, setUploadType] = useState<DocumentType>("pdf");
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  function load(p = 1) {
    if (!tenantSlug) return;
    setLoading(true);
    documents
      .list(tenantSlug, { page: p })
      .then((resp) => {
        setDocs(resp.results);
        setCount(resp.count);
      })
      .catch((err: unknown) => {
        if (err instanceof ApiError && err.status === 403) {
          router.push("/signin");
        } else {
          setError("Failed to load documents.");
        }
      })
      .finally(() => setLoading(false));
  }

  useEffect(() => {
    if (!tenantSlug) {
      router.push("/tenants");
      return;
    }
    load(page);
  }, [tenantSlug, page]); // eslint-disable-line react-hooks/exhaustive-deps

  async function handleUpload(e: React.FormEvent) {
    e.preventDefault();
    if (!uploadFile || !uploadTitle.trim()) return;
    setUploading(true);
    setUploadError(null);
    try {
      const doc = await documents.create(tenantSlug, uploadTitle.trim(), uploadType, uploadFile);
      setShowUpload(false);
      setUploadTitle("");
      setUploadFile(null);
      setUploadType("pdf");
      router.push(`/documents/${doc.public_id}?tenant=${tenantSlug}`);
    } catch (err) {
      setUploadError(err instanceof ApiError ? err.message : "Upload failed.");
    } finally {
      setUploading(false);
    }
  }

  if (!tenantSlug) return null;

  const totalPages = Math.ceil(count / 25);

  return (
    <main style={{ maxWidth: 900, margin: "2rem auto", padding: "0 1rem" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "1.5rem" }}>
        <h1 style={{ margin: 0 }}>Documents</h1>
        <button
          onClick={() => setShowUpload(true)}
          style={{
            background: "#1d4ed8",
            color: "#fff",
            border: "none",
            borderRadius: 6,
            padding: "8px 18px",
            cursor: "pointer",
            fontWeight: 600,
          }}
        >
          Upload document
        </button>
      </div>

      {loading && <p>Loading…</p>}
      {error && <p role="alert" style={{ color: "#b91c1c" }}>{error}</p>}

      {!loading && docs.length === 0 && (
        <p style={{ color: "#6b7280" }}>No documents yet. Upload one to get started.</p>
      )}

      {docs.length > 0 && (
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 14 }}>
          <thead>
            <tr style={{ borderBottom: "2px solid #e5e7eb", textAlign: "left" }}>
              <th style={{ padding: "8px 12px" }}>Title</th>
              <th style={{ padding: "8px 12px" }}>Type</th>
              <th style={{ padding: "8px 12px" }}>Status</th>
              <th style={{ padding: "8px 12px" }}>Scan</th>
              <th style={{ padding: "8px 12px" }}>Processing</th>
              <th style={{ padding: "8px 12px" }}>Uploaded</th>
            </tr>
          </thead>
          <tbody>
            {docs.map((doc) => (
              <tr
                key={doc.public_id}
                style={{ borderBottom: "1px solid #f3f4f6" }}
              >
                <td style={{ padding: "10px 12px" }}>
                  <Link
                    href={`/documents/${doc.public_id}?tenant=${tenantSlug}`}
                    style={{ color: "#1d4ed8", textDecoration: "none", fontWeight: 500 }}
                  >
                    {doc.title}
                  </Link>
                </td>
                <td style={{ padding: "10px 12px", textTransform: "uppercase", fontSize: 12, color: "#6b7280" }}>
                  {doc.document_type}
                </td>
                <td style={{ padding: "10px 12px" }}>
                  <span style={{
                    fontSize: 11,
                    padding: "2px 6px",
                    borderRadius: 4,
                    background: doc.status === "archived" ? "#f3f4f6" : "#dcfce7",
                    color: doc.status === "archived" ? "#374151" : "#166534",
                    fontWeight: 600,
                  }}>
                    {doc.status}
                  </span>
                </td>
                <td style={{ padding: "10px 12px" }}>
                  {doc.current_version ? scanBadge(doc.current_version.scan_status) : "—"}
                </td>
                <td style={{ padding: "10px 12px", color: "#6b7280" }}>
                  {doc.current_version ? processingLabel(doc.current_version.processing_status) : "—"}
                </td>
                <td style={{ padding: "10px 12px", color: "#6b7280", fontSize: 12 }}>
                  {doc.current_version
                    ? new Date(doc.current_version.uploaded_at).toLocaleDateString()
                    : "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {totalPages > 1 && (
        <div style={{ display: "flex", gap: 8, marginTop: "1rem", alignItems: "center" }}>
          <button
            disabled={page <= 1}
            onClick={() => setPage(page - 1)}
            style={{ padding: "4px 12px", cursor: page > 1 ? "pointer" : "not-allowed" }}
          >
            Prev
          </button>
          <span style={{ fontSize: 13, color: "#6b7280" }}>
            Page {page} of {totalPages}
          </span>
          <button
            disabled={page >= totalPages}
            onClick={() => setPage(page + 1)}
            style={{ padding: "4px 12px", cursor: page < totalPages ? "pointer" : "not-allowed" }}
          >
            Next
          </button>
        </div>
      )}

      {showUpload && (
        <div
          role="dialog"
          aria-modal="true"
          aria-labelledby="upload-dialog-title"
          style={{
            position: "fixed",
            inset: 0,
            background: "rgba(0,0,0,0.5)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            zIndex: 1000,
          }}
          onClick={(e) => { if (e.target === e.currentTarget) setShowUpload(false); }}
        >
          <div
            style={{
              background: "#fff",
              borderRadius: 10,
              padding: "2rem",
              width: 480,
              maxWidth: "90vw",
              boxShadow: "0 20px 60px rgba(0,0,0,0.2)",
            }}
          >
            <h2 id="upload-dialog-title" style={{ marginTop: 0 }}>Upload document</h2>
            <form onSubmit={handleUpload}>
              <label style={{ display: "block", marginBottom: "0.5rem", fontWeight: 500 }}>
                Title
                <input
                  type="text"
                  value={uploadTitle}
                  onChange={(e) => setUploadTitle(e.target.value)}
                  required
                  style={{
                    display: "block",
                    width: "100%",
                    marginTop: 4,
                    padding: "8px 10px",
                    border: "1px solid #d1d5db",
                    borderRadius: 6,
                    fontSize: 14,
                    boxSizing: "border-box",
                  }}
                />
              </label>

              <label style={{ display: "block", marginBottom: "0.5rem", fontWeight: 500 }}>
                Document type
                <select
                  value={uploadType}
                  onChange={(e) => setUploadType(e.target.value as DocumentType)}
                  style={{
                    display: "block",
                    width: "100%",
                    marginTop: 4,
                    padding: "8px 10px",
                    border: "1px solid #d1d5db",
                    borderRadius: 6,
                    fontSize: 14,
                  }}
                >
                  {ALLOWED_TYPES.map((t) => (
                    <option key={t} value={t}>{t.toUpperCase()}</option>
                  ))}
                </select>
              </label>

              <label style={{ display: "block", marginBottom: "1rem", fontWeight: 500 }}>
                File
                <input
                  ref={fileInputRef}
                  type="file"
                  accept={ALLOWED_TYPES.map((t) => MIME_FOR_TYPE[t]).join(",")}
                  required
                  onChange={(e) => setUploadFile(e.target.files?.[0] ?? null)}
                  style={{ display: "block", marginTop: 4, fontSize: 14 }}
                />
              </label>

              {uploadError && (
                <p role="alert" style={{ color: "#b91c1c", marginBottom: "0.75rem", fontSize: 13 }}>
                  {uploadError}
                </p>
              )}

              <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
                <button
                  type="button"
                  onClick={() => setShowUpload(false)}
                  style={{ padding: "8px 16px", borderRadius: 6, border: "1px solid #d1d5db", cursor: "pointer" }}
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={uploading || !uploadFile || !uploadTitle.trim()}
                  style={{
                    padding: "8px 18px",
                    borderRadius: 6,
                    border: "none",
                    background: uploading ? "#93c5fd" : "#1d4ed8",
                    color: "#fff",
                    fontWeight: 600,
                    cursor: uploading ? "not-allowed" : "pointer",
                  }}
                >
                  {uploading ? "Uploading…" : "Upload"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </main>
  );
}

export default function DocumentsPage() {
  return (
    <Suspense>
      <DocumentsPageInner />
    </Suspense>
  );
}
