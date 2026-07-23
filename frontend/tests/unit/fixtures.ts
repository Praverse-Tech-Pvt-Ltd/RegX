// Synthetic, non-confidential fixtures for frontend unit/component tests.
import type {
  Document,
  DocumentLocator,
  DocumentVersion,
  PaginatedResponse,
  ProcessingStatus,
  ScanStatus,
} from "@/lib/api";

export function makeVersion(overrides: Partial<DocumentVersion> = {}): DocumentVersion {
  return {
    public_id: "ver-public-0001",
    version_number: 1,
    original_filename: "quarterly-report.pdf",
    extension: "pdf",
    declared_mime_type: "application/pdf",
    detected_mime_type: "application/pdf",
    size_bytes: 20480,
    scan_status: "clean" as ScanStatus,
    processing_status: "complete" as ProcessingStatus,
    failure_code: null,
    uploaded_by: "Ada Lovelace",
    uploaded_at: "2026-07-20T10:00:00Z",
    processing_started_at: "2026-07-20T10:00:05Z",
    processing_finished_at: "2026-07-20T10:00:12Z",
    ...overrides,
  };
}

export function makeDocument(overrides: Partial<Document> = {}): Document {
  return {
    public_id: "doc-public-0001",
    title: "Quarterly Report",
    document_type: "pdf",
    status: "active",
    current_version: makeVersion(),
    created_by: "Ada Lovelace",
    created_at: "2026-07-20T09:59:00Z",
    archived_at: null,
    ...overrides,
  };
}

export function makeLocator(overrides: Partial<DocumentLocator> = {}): DocumentLocator {
  return {
    public_id: "loc-public-0001",
    locator_type: "page",
    locator_id: "1",
    display_label: "Page 1",
    extracted_text: "Synthetic extracted text.",
    ordering: 1,
    ...overrides,
  };
}

export function paginate<T>(results: T[]): PaginatedResponse<T> {
  return { count: results.length, next: null, previous: null, results };
}
