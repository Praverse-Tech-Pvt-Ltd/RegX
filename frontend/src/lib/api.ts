/**
 * API client for REGX backend.
 * Auth tokens are NEVER stored in localStorage or sessionStorage.
 * Authentication uses secure HttpOnly session cookies set by Django.
 */

import {
  toChecklistExecution,
  toChecklistResponse,
  type ChecklistExecutionDTO,
  type ChecklistResponseDTO,
} from "./api/execution-mappers";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

async function getCsrfToken(): Promise<string> {
  const resp = await fetch(`${API_BASE}/api/regx/v1/auth/csrf/`, {
    credentials: "include",
  });
  const data = (await resp.json()) as { csrfToken: string };
  return data.csrfToken;
}

interface RequestOptions {
  method?: string;
  body?: unknown;
  headers?: Record<string, string>;
}

export async function apiRequest<T>(
  path: string,
  { method = "GET", body, headers = {} }: RequestOptions = {}
): Promise<T> {
  const isWrite = ["POST", "PUT", "PATCH", "DELETE"].includes(method.toUpperCase());
  const requestHeaders: Record<string, string> = {
    "Content-Type": "application/json",
    ...headers,
  };

  if (isWrite) {
    const csrfToken = await getCsrfToken();
    requestHeaders["X-CSRFToken"] = csrfToken;
  }

  const resp = await fetch(`${API_BASE}${path}`, {
    method,
    credentials: "include",  // cookies carry the session — no token in JS storage
    headers: requestHeaders,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });

  if (!resp.ok) {
    const error = (await resp.json().catch(() => ({ detail: "Request failed" }))) as {
      detail?: string;
    };
    throw new ApiError(resp.status, error.detail ?? "Request failed");
  }

  if (resp.status === 204) return undefined as T;
  return resp.json() as Promise<T>;
}

/**
 * Reduce a paginator `next`/`previous` link to a path `apiRequest` can take.
 *
 * DRF builds those links as absolute URLs from the incoming request, so they
 * cannot be passed to `apiRequest` (which prefixes API_BASE) as-is. Keeping the
 * query string matters: it carries the page cursor. A value that is already a
 * path, or one that will not parse, is returned unchanged rather than throwing —
 * a malformed link should not take down a page load.
 */
export function toApiPath(link: string): string {
  try {
    const url = new URL(link, API_BASE);
    return `${url.pathname}${url.search}`;
  } catch {
    return link;
  }
}

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    message: string
  ) {
    super(message);
    this.name = "ApiError";
  }
}

// ---------------------------------------------------------------------------
// Typed endpoint wrappers
// ---------------------------------------------------------------------------

export interface UserProfile {
  id: string;
  email: string;
  full_name: string;
  is_active: boolean;
  mfa_required: boolean;
  created_at: string;
}

export interface Tenant {
  id: string;
  name: string;
  slug: string;
  status: string;
  created_at: string;
}

export const auth = {
  register: (email: string, password: string, full_name?: string) =>
    apiRequest<UserProfile>("/api/regx/v1/auth/register/", {
      method: "POST",
      body: { email, password, full_name },
    }),

  login: (email: string, password: string) =>
    apiRequest<UserProfile>("/api/regx/v1/auth/login/", {
      method: "POST",
      body: { email, password },
    }),

  logout: () =>
    apiRequest<void>("/api/regx/v1/auth/logout/", { method: "POST" }),

  me: () => apiRequest<UserProfile>("/api/regx/v1/auth/me/"),
};

export const tenants = {
  list: () => apiRequest<Tenant[]>("/api/regx/v1/tenants/"),

  create: (name: string, slug: string) =>
    apiRequest<Tenant>("/api/regx/v1/tenants/", {
      method: "POST",
      body: { name, slug },
    }),
};

// ---------------------------------------------------------------------------
// Document platform types
// ---------------------------------------------------------------------------

export type DocumentType = "pdf" | "docx" | "xlsx" | "pptx";
export type DocumentStatus = "active" | "archived";
export type ScanStatus =
  | "pending"
  | "clean"
  | "infected"
  | "scan_failed"
  | "scanner_unavailable"
  | "quarantined";
export type ProcessingStatus = "pending" | "processing" | "complete" | "failed" | "skipped";

export interface DocumentVersion {
  public_id: string;
  version_number: number;
  original_filename: string;
  extension: string;
  declared_mime_type: string;
  detected_mime_type: string;
  size_bytes: number;
  scan_status: ScanStatus;
  processing_status: ProcessingStatus;
  failure_code: string | null;
  uploaded_by: string;
  uploaded_at: string;
  processing_started_at: string | null;
  processing_finished_at: string | null;
}

export interface Document {
  public_id: string;
  title: string;
  document_type: DocumentType;
  status: DocumentStatus;
  current_version: DocumentVersion | null;
  created_by: string;
  created_at: string;
  archived_at: string | null;
}

export interface DocumentLocator {
  public_id: string;
  locator_type: string;
  locator_id: string;
  display_label: string;
  extracted_text: string;
  ordering: number;
}

export interface PaginatedResponse<T> {
  count: number;
  next: string | null;
  previous: string | null;
  results: T[];
}

// Multipart upload requires a raw fetch (not JSON)
async function documentUploadRequest<T>(
  path: string,
  formData: FormData,
  tenantSlug: string
): Promise<T> {
  const csrfResp = await fetch(`${API_BASE}/api/regx/v1/auth/csrf/`, {
    credentials: "include",
  });
  const { csrfToken } = (await csrfResp.json()) as { csrfToken: string };

  const resp = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    credentials: "include",
    headers: {
      "X-CSRFToken": csrfToken,
      "X-Tenant-Slug": tenantSlug,
    },
    body: formData,
  });

  if (!resp.ok) {
    const error = (await resp.json().catch(() => ({ detail: "Upload failed" }))) as {
      detail?: string;
    };
    throw new ApiError(resp.status, error.detail ?? "Upload failed");
  }
  return resp.json() as Promise<T>;
}

export const documents = {
  list: (tenantSlug: string, params?: { status?: string; document_type?: string; page?: number }) => {
    const qs = new URLSearchParams();
    if (params?.status) qs.set("status", params.status);
    if (params?.document_type) qs.set("document_type", params.document_type);
    if (params?.page) qs.set("page", String(params.page));
    const query = qs.toString() ? `?${qs}` : "";
    return apiRequest<PaginatedResponse<Document>>(
      `/api/regx/v1/documents/${query}`,
      { headers: { "X-Tenant-Slug": tenantSlug } }
    );
  },

  get: (tenantSlug: string, publicId: string) =>
    apiRequest<Document>(`/api/regx/v1/documents/${publicId}/`, {
      headers: { "X-Tenant-Slug": tenantSlug },
    }),

  create: (tenantSlug: string, title: string, documentType: DocumentType, file: File) => {
    const fd = new FormData();
    fd.append("title", title);
    fd.append("document_type", documentType);
    fd.append("file", file);
    return documentUploadRequest<Document>(
      "/api/regx/v1/documents/",
      fd,
      tenantSlug
    );
  },

  archive: (tenantSlug: string, publicId: string) =>
    apiRequest<Document>(`/api/regx/v1/documents/${publicId}/archive/`, {
      method: "POST",
      headers: { "X-Tenant-Slug": tenantSlug },
    }),

  restore: (tenantSlug: string, publicId: string) =>
    apiRequest<Document>(`/api/regx/v1/documents/${publicId}/restore/`, {
      method: "POST",
      headers: { "X-Tenant-Slug": tenantSlug },
    }),

  versions: (tenantSlug: string, publicId: string) =>
    apiRequest<PaginatedResponse<DocumentVersion>>(
      `/api/regx/v1/documents/${publicId}/versions/`,
      { headers: { "X-Tenant-Slug": tenantSlug } }
    ),

  uploadVersion: (tenantSlug: string, publicId: string, file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    return documentUploadRequest<DocumentVersion>(
      `/api/regx/v1/documents/${publicId}/versions/`,
      fd,
      tenantSlug
    );
  },

  versionStatus: (tenantSlug: string, publicId: string, versionPublicId: string) =>
    apiRequest<{ scan_status: ScanStatus; processing_status: ProcessingStatus }>(
      `/api/regx/v1/documents/${publicId}/versions/${versionPublicId}/status/`,
      { headers: { "X-Tenant-Slug": tenantSlug } }
    ),

  locators: (tenantSlug: string, publicId: string, versionPublicId: string) =>
    apiRequest<PaginatedResponse<DocumentLocator>>(
      `/api/regx/v1/documents/${publicId}/versions/${versionPublicId}/locators/`,
      { headers: { "X-Tenant-Slug": tenantSlug } }
    ),
};

// ---------------------------------------------------------------------------
// Template registry / migration governance types
// ---------------------------------------------------------------------------

export type TemplateLifecycleStatus =
  | "draft"
  | "imported"
  | "under_review"
  | "returned"
  | "approved"
  | "active"
  | "superseded"
  | "retired"
  | "rejected";

export type MigrationBatchStatus =
  | "registered"
  | "extracting"
  | "validating"
  | "classifying"
  | "normalizing"
  | "duplicate_detection"
  | "importing"
  | "completed"
  | "failed";

export interface RegulatoryTemplate {
  public_id: string;
  canonical_code: string;
  title: string;
  category: string;
  regulatory_pathway: string;
  dosage_form_applicability: string;
  description: string;
  lifecycle_status: TemplateLifecycleStatus;
  current_approved_version: string | null;
  created_at: string;
  updated_at: string;
}

export interface TemplateVersion {
  public_id: string;
  template: string;
  version_number: number;
  status: TemplateLifecycleStatus;
  effective_date: string | null;
  superseded_date: string | null;
  approved_at: string | null;
}

export interface TemplateSection {
  public_id: string;
  canonical_section_code: string;
  normalized_title: string;
  display_order: number;
  parent_section: string | null;
}

export interface TemplateItemOption {
  public_id: string;
  code: string;
  normalized_label: string;
  order: number;
}

export interface TemplateItem {
  public_id: string;
  template_section: string;
  canonical_item_code: string;
  normalized_text: string;
  guidance_text: string;
  response_type: string;
  required: boolean;
  display_order: number;
  options: TemplateItemOption[];
}

export interface TemplateSourcePackage {
  public_id: string;
  source_name: string;
  source_type: string;
  source_checksum: string;
  source_version: string;
  source_date: string | null;
  approval_state: "pending" | "approved" | "rejected";
  imported_by_email: string | null;
  imported_at: string;
}

export interface MigrationBatch {
  public_id: string;
  source_package: string;
  status: MigrationBatchStatus;
  started_by_email: string | null;
  started_at: string;
  completed_at: string | null;
  counts: Record<string, number>;
  correlation_id: string;
}

export interface MigrationRecordResult {
  public_id: string;
  source_record_identifier: string;
  target_public_identifier: string | null;
  result: "imported" | "skipped" | "excluded" | "duplicate" | "failed" | "requires_review";
  reason_code: string;
  safe_detail: string;
}

export interface NormalizationMappingRow {
  public_id: string;
  source_record_identifier: string;
  field_name: string;
  raw_value: string;
  normalized_value: string;
  normalization_rule: string;
  reviewer_email: string | null;
  reason: string;
  created_at: string;
}

export interface TemplateDuplicateCandidate {
  public_id: string;
  match_type: string;
  similarity_evidence: Record<string, unknown>;
  resolution: "pending" | "same" | "distinct" | "superseded" | "merge_approved";
  reviewer_email: string | null;
  reason: string;
  suspected_match_item: string;
  created_at: string;
}

export interface ReconciliationReport {
  batch: { correlation_id: string; public_id: string; status: string };
  source_package: { public_id: string; source_name: string; source_checksum: string };
  counts: Record<string, number>;
  records: MigrationRecordResult[];
  unmatched_records: { source_record_identifier: string; migration_disposition: string }[];
  normalization_mappings: NormalizationMappingRow[];
  duplicate_candidates: TemplateDuplicateCandidate[];
  approvals: {
    template_version: string;
    reviewer: string | null;
    decision: string;
    approval_sequence: number;
    role_at_time: string;
  }[];
}

export const templates = {
  list: (tenantSlug: string, params?: { status?: string; page?: number }) => {
    const qs = new URLSearchParams();
    if (params?.status) qs.set("status", params.status);
    if (params?.page) qs.set("page", String(params.page));
    const query = qs.toString() ? `?${qs}` : "";
    return apiRequest<PaginatedResponse<RegulatoryTemplate>>(`/api/regx/v1/templates/${query}`, {
      headers: { "X-Tenant-Slug": tenantSlug },
    });
  },

  get: (tenantSlug: string, publicId: string) =>
    apiRequest<RegulatoryTemplate>(`/api/regx/v1/templates/${publicId}/`, {
      headers: { "X-Tenant-Slug": tenantSlug },
    }),

  versions: (tenantSlug: string, publicId: string) =>
    apiRequest<PaginatedResponse<TemplateVersion>>(`/api/regx/v1/templates/${publicId}/versions/`, {
      headers: { "X-Tenant-Slug": tenantSlug },
    }),

  sections: (tenantSlug: string, publicId: string, versionPublicId: string) =>
    apiRequest<PaginatedResponse<TemplateSection>>(
      `/api/regx/v1/templates/${publicId}/versions/${versionPublicId}/sections/`,
      { headers: { "X-Tenant-Slug": tenantSlug } }
    ),

  items: (tenantSlug: string, publicId: string, versionPublicId: string) =>
    apiRequest<PaginatedResponse<TemplateItem>>(
      `/api/regx/v1/templates/${publicId}/versions/${versionPublicId}/items/`,
      { headers: { "X-Tenant-Slug": tenantSlug } }
    ),

  submitReview: (tenantSlug: string, publicId: string, versionPublicId: string) =>
    apiRequest<TemplateVersion>(
      `/api/regx/v1/templates/${publicId}/versions/${versionPublicId}/submit-review/`,
      { method: "POST", headers: { "X-Tenant-Slug": tenantSlug }, body: {} }
    ),

  approve: (tenantSlug: string, publicId: string, versionPublicId: string, comments?: string) =>
    apiRequest<TemplateVersion>(
      `/api/regx/v1/templates/${publicId}/versions/${versionPublicId}/approve/`,
      { method: "POST", headers: { "X-Tenant-Slug": tenantSlug }, body: { comments: comments ?? "" } }
    ),

  returnForCorrection: (tenantSlug: string, publicId: string, versionPublicId: string, comments?: string) =>
    apiRequest<TemplateVersion>(
      `/api/regx/v1/templates/${publicId}/versions/${versionPublicId}/return/`,
      { method: "POST", headers: { "X-Tenant-Slug": tenantSlug }, body: { comments: comments ?? "" } }
    ),

  reject: (tenantSlug: string, publicId: string, versionPublicId: string, comments?: string) =>
    apiRequest<TemplateVersion>(
      `/api/regx/v1/templates/${publicId}/versions/${versionPublicId}/reject/`,
      { method: "POST", headers: { "X-Tenant-Slug": tenantSlug }, body: { comments: comments ?? "" } }
    ),

  activate: (tenantSlug: string, publicId: string, versionPublicId: string) =>
    apiRequest<TemplateVersion>(
      `/api/regx/v1/templates/${publicId}/versions/${versionPublicId}/activate/`,
      { method: "POST", headers: { "X-Tenant-Slug": tenantSlug }, body: {} }
    ),

  supersede: (tenantSlug: string, publicId: string, versionPublicId: string, comments?: string) =>
    apiRequest<TemplateVersion>(
      `/api/regx/v1/templates/${publicId}/versions/${versionPublicId}/supersede/`,
      { method: "POST", headers: { "X-Tenant-Slug": tenantSlug }, body: { comments: comments ?? "" } }
    ),

  retire: (tenantSlug: string, publicId: string, versionPublicId: string, comments?: string) =>
    apiRequest<TemplateVersion>(
      `/api/regx/v1/templates/${publicId}/versions/${versionPublicId}/retire/`,
      { method: "POST", headers: { "X-Tenant-Slug": tenantSlug }, body: { comments: comments ?? "" } }
    ),
};

export const templateSources = {
  list: (tenantSlug: string) =>
    apiRequest<PaginatedResponse<TemplateSourcePackage>>("/api/regx/v1/template-sources/", {
      headers: { "X-Tenant-Slug": tenantSlug },
    }),

  register: (
    tenantSlug: string,
    data: {
      source_name: string;
      source_type: string;
      source_path_or_reference: string;
      payload: Record<string, unknown>;
      source_version?: string;
    }
  ) =>
    apiRequest<TemplateSourcePackage>("/api/regx/v1/template-sources/", {
      method: "POST",
      headers: { "X-Tenant-Slug": tenantSlug },
      body: data,
    }),
};

export const migrationBatches = {
  list: (tenantSlug: string) =>
    apiRequest<PaginatedResponse<MigrationBatch>>("/api/regx/v1/migration-batches/", {
      headers: { "X-Tenant-Slug": tenantSlug },
    }),

  get: (tenantSlug: string, publicId: string) =>
    apiRequest<MigrationBatch>(`/api/regx/v1/migration-batches/${publicId}/`, {
      headers: { "X-Tenant-Slug": tenantSlug },
    }),

  create: (tenantSlug: string, sourcePackage: string, records: Record<string, unknown>[]) =>
    apiRequest<MigrationBatch>("/api/regx/v1/migration-batches/", {
      method: "POST",
      headers: { "X-Tenant-Slug": tenantSlug },
      body: { source_package: sourcePackage, records },
    }),

  results: (tenantSlug: string, publicId: string) =>
    apiRequest<PaginatedResponse<MigrationRecordResult>>(
      `/api/regx/v1/migration-batches/${publicId}/results/`,
      { headers: { "X-Tenant-Slug": tenantSlug } }
    ),

  reconciliation: (tenantSlug: string, publicId: string) =>
    apiRequest<ReconciliationReport>(
      `/api/regx/v1/migration-batches/${publicId}/reconciliation.json`,
      { headers: { "X-Tenant-Slug": tenantSlug } }
    ),

  review: (
    tenantSlug: string,
    publicId: string,
    duplicateResolutions: { public_id: string; resolution: string; reason?: string }[]
  ) =>
    apiRequest<{ resolved: string[] }>(`/api/regx/v1/migration-batches/${publicId}/review/`, {
      method: "POST",
      headers: { "X-Tenant-Slug": tenantSlug },
      body: { duplicate_resolutions: duplicateResolutions },
    }),
};

// ---------------------------------------------------------------------------
// FDA data governance
// ---------------------------------------------------------------------------

export type FdaReleaseStatus =
  | "registered"
  | "staged"
  | "validated"
  | "under_review"
  | "approved"
  | "active"
  | "superseded"
  | "rejected";

export interface FdaDataSourceRelease {
  public_id: string;
  dataset_type: string;
  source_name: string;
  official_source_reference: string;
  schema_version: string;
  publication_date: string | null;
  retrieved_at: string | null;
  imported_at: string | null;
  imported_by_email: string | null;
  record_count_expected: number;
  record_count_extracted: number;
  record_count_imported: number;
  record_count_failed: number;
  status: FdaReleaseStatus;
  approved_by_email: string | null;
  approved_at: string | null;
  activated_by_email: string | null;
  activated_at: string | null;
  superseded_by_release: string | null;
  correlation_id: string;
  created_at: string;
  // Raw-only fields, present only for holders of fda_data.view_raw.
  original_filename?: string;
  media_type?: string;
  source_checksum_sha256?: string;
  notes?: string;
}

export interface OrangeBookProduct {
  public_id: string;
  release: string;
  application_number: string;
  application_type: string;
  product_number: string;
  trade_name: string;
  active_ingredient_raw: string;
  dosage_form_raw: string;
  route_raw: string;
  dosage_form_normalized: string | null;
  route_normalized: string | null;
  strength_raw: string;
  strength_amount: string | null;
  strength_parse_status: string;
  rld_flag: boolean;
  reference_standard_flag: boolean;
  te_code: string;
  approval_date: string | null;
  approval_date_text: string;
  discontinued: boolean;
}

export type MappingType = "route" | "dosage_form" | "unit" | "substance";
export type MappingDecisionStatus =
  | "proposed"
  | "reviewed"
  | "under_review"
  | "approved"
  | "rejected"
  | "returned";

export interface TerminologyMapping {
  public_id: string;
  mapping_type: MappingType;
  source_dataset: string;
  source_raw_value: string;
  proposed_controlled_value: string | null;
  status: MappingDecisionStatus;
  is_current: boolean;
  reviewer_email: string | null;
  reason: string;
  affected_record_count: number;
  created_at: string;
  // Substance/UNII synonym mappings only; null for the other three types.
  proposed_unii?: string | null;
  proposed_cas_number?: string | null;
  mapping_method?: string | null;
  release_public_id?: string | null;
}

export interface AffectedRecord {
  record_public_id: string;
  dataset_type: string;
  release_public_id: string | null;
  source_row_locator?: string | null;
  raw_value: string;
  normalized_value: string | null;
  mapping_status: string | null;
  calculability_status?: string | null;
  blocked: boolean;
  reason_code: string;
}

export interface FdaImportRowResultItem {
  public_id: string;
  row_locator: string;
  target_public_identifier: string | null;
  result: "imported" | "duplicate" | "failed" | "review_required";
  reason_code: string;
  safe_detail: string;
}

export interface FdaReconciliationReport {
  release: { public_id: string; dataset_type: string; status: string };
  counts: {
    expected: number;
    extracted: number;
    imported: number;
    failed: number;
  };
  results: FdaImportRowResultItem[];
}

export const fdaData = {
  releases: {
    list: (tenantSlug: string, params?: { dataset_type?: string; page?: number }) => {
      const qs = new URLSearchParams();
      if (params?.dataset_type) qs.set("dataset_type", params.dataset_type);
      if (params?.page) qs.set("page", String(params.page));
      const query = qs.toString() ? `?${qs}` : "";
      return apiRequest<PaginatedResponse<FdaDataSourceRelease>>(
        `/api/regx/v1/fda-data/releases/${query}`,
        { headers: { "X-Tenant-Slug": tenantSlug } }
      );
    },

    get: (tenantSlug: string, publicId: string) =>
      apiRequest<FdaDataSourceRelease>(`/api/regx/v1/fda-data/releases/${publicId}/`, {
        headers: { "X-Tenant-Slug": tenantSlug },
      }),

    register: (
      tenantSlug: string,
      data: {
        dataset_type: string;
        source_name: string;
        official_source_reference: string;
        rows: Record<string, unknown>[];
        schema_version?: string;
      }
    ) =>
      apiRequest<FdaDataSourceRelease>("/api/regx/v1/fda-data/releases/", {
        method: "POST",
        headers: { "X-Tenant-Slug": tenantSlug },
        body: data,
      }),

    submitReview: (tenantSlug: string, publicId: string) =>
      apiRequest<FdaDataSourceRelease>(
        `/api/regx/v1/fda-data/releases/${publicId}/submit-review/`,
        { method: "POST", headers: { "X-Tenant-Slug": tenantSlug }, body: {} }
      ),

    approve: (tenantSlug: string, publicId: string, notes?: string) =>
      apiRequest<FdaDataSourceRelease>(`/api/regx/v1/fda-data/releases/${publicId}/approve/`, {
        method: "POST",
        headers: { "X-Tenant-Slug": tenantSlug },
        body: { notes: notes ?? "" },
      }),

    activate: (tenantSlug: string, publicId: string) =>
      apiRequest<FdaDataSourceRelease>(`/api/regx/v1/fda-data/releases/${publicId}/activate/`, {
        method: "POST",
        headers: { "X-Tenant-Slug": tenantSlug },
        body: {},
      }),

    reconciliationJson: (tenantSlug: string, publicId: string) =>
      apiRequest<FdaReconciliationReport>(
        `/api/regx/v1/fda-data/releases/${publicId}/reconciliation.json`,
        { headers: { "X-Tenant-Slug": tenantSlug } }
      ),

    reconciliationCsvUrl: (publicId: string) =>
      `/api/regx/v1/fda-data/releases/${publicId}/reconciliation.csv`,
  },

  orangeBook: {
    search: (
      tenantSlug: string,
      params?: {
        active_ingredient?: string;
        route?: string;
        dosage_form?: string;
        strength?: string;
        application_type?: string;
        rld?: boolean;
        reference_standard?: boolean;
        discontinued?: boolean;
        page?: number;
      }
    ) => {
      const qs = new URLSearchParams();
      if (params?.active_ingredient) qs.set("active_ingredient", params.active_ingredient);
      if (params?.route) qs.set("route", params.route);
      if (params?.dosage_form) qs.set("dosage_form", params.dosage_form);
      if (params?.strength) qs.set("strength", params.strength);
      if (params?.application_type) qs.set("application_type", params.application_type);
      if (params?.rld !== undefined) qs.set("rld", String(params.rld));
      if (params?.reference_standard !== undefined)
        qs.set("reference_standard", String(params.reference_standard));
      if (params?.discontinued !== undefined) qs.set("discontinued", String(params.discontinued));
      if (params?.page) qs.set("page", String(params.page));
      const query = qs.toString() ? `?${qs}` : "";
      return apiRequest<PaginatedResponse<OrangeBookProduct>>(
        `/api/regx/v1/fda-data/orange-book/products/${query}`,
        { headers: { "X-Tenant-Slug": tenantSlug } }
      );
    },

    get: (tenantSlug: string, publicId: string) =>
      apiRequest<OrangeBookProduct>(`/api/regx/v1/fda-data/orange-book/products/${publicId}/`, {
        headers: { "X-Tenant-Slug": tenantSlug },
      }),
  },

  mappings: {
    list: (
      tenantSlug: string,
      params?: {
        type?: string;
        status?: string;
        release?: string;
        raw_value?: string;
        reviewer?: string;
        page?: number;
      }
    ) => {
      const qs = new URLSearchParams();
      if (params?.type) qs.set("type", params.type);
      if (params?.status) qs.set("status", params.status);
      if (params?.release) qs.set("release", params.release);
      if (params?.raw_value) qs.set("raw_value", params.raw_value);
      if (params?.reviewer) qs.set("reviewer", params.reviewer);
      if (params?.page) qs.set("page", String(params.page));
      const query = qs.toString() ? `?${qs}` : "";
      return apiRequest<PaginatedResponse<TerminologyMapping>>(
        `/api/regx/v1/fda-data/mappings/${query}`,
        { headers: { "X-Tenant-Slug": tenantSlug } }
      );
    },

    get: (tenantSlug: string, publicId: string) =>
      apiRequest<TerminologyMapping>(`/api/regx/v1/fda-data/mappings/${publicId}/`, {
        headers: { "X-Tenant-Slug": tenantSlug },
      }),

    affectedRecords: (tenantSlug: string, publicId: string, page?: number) => {
      const qs = new URLSearchParams();
      if (page) qs.set("page", String(page));
      const query = qs.toString() ? `?${qs}` : "";
      return apiRequest<PaginatedResponse<AffectedRecord>>(
        `/api/regx/v1/fda-data/mappings/${publicId}/affected-records/${query}`,
        { headers: { "X-Tenant-Slug": tenantSlug } }
      );
    },

    submitReview: (tenantSlug: string, publicId: string, reason?: string) =>
      apiRequest<TerminologyMapping>(
        `/api/regx/v1/fda-data/mappings/${publicId}/submit-review/`,
        { method: "POST", headers: { "X-Tenant-Slug": tenantSlug }, body: { reason: reason ?? "" } }
      ),

    approve: (tenantSlug: string, publicId: string, reason?: string) =>
      apiRequest<TerminologyMapping>(`/api/regx/v1/fda-data/mappings/${publicId}/approve/`, {
        method: "POST",
        headers: { "X-Tenant-Slug": tenantSlug },
        body: { reason: reason ?? "" },
      }),

    reject: (tenantSlug: string, publicId: string, reason?: string) =>
      apiRequest<TerminologyMapping>(`/api/regx/v1/fda-data/mappings/${publicId}/reject/`, {
        method: "POST",
        headers: { "X-Tenant-Slug": tenantSlug },
        body: { reason: reason ?? "" },
      }),

    return: (tenantSlug: string, publicId: string, reason?: string) =>
      apiRequest<TerminologyMapping>(`/api/regx/v1/fda-data/mappings/${publicId}/return/`, {
        method: "POST",
        headers: { "X-Tenant-Slug": tenantSlug },
        body: { reason: reason ?? "" },
      }),

    proposeSubstance: (
      tenantSlug: string,
      data: {
        release_public_id?: string;
        raw_ingredient_name: string;
        normalized_ingredient_name: string;
        raw_unii?: string;
        raw_cas_number?: string;
        source_row_locator?: string;
        proposed_ingredient_public_id?: string;
        proposed_unii?: string;
        proposed_cas_number?: string;
        mapping_method: string;
        reason?: string;
      }
    ) =>
      apiRequest<TerminologyMapping>("/api/regx/v1/fda-data/mappings/substances/proposals/", {
        method: "POST",
        headers: { "X-Tenant-Slug": tenantSlug },
        body: data,
      }),
  },
};

// ---------------------------------------------------------------------------
// Formulations
// ---------------------------------------------------------------------------

export interface ProductDevelopmentRecord {
  public_id: string;
  product_code: string;
  proposed_product_name: string;
  active_ingredient: string;
  is_combination_product: boolean;
  release_type: string;
  route: string;
  dosage_form: string;
  proposed_strength_amount: string | null;
  proposed_strength_unit: string;
  regulatory_market_context: string;
  selected_ob_application_number: string;
  selected_ob_product_number: string;
  selected_ob_product_public_id: string | null;
  selected_ob_release_public_id: string | null;
  selection_timestamp: string | null;
  selecting_user_email: string | null;
  selection_justification: string;
  status: string;
  created_at: string;
}

export interface FormulationVersion {
  public_id: string;
  product: string;
  version_number: number;
  status: string;
  total_dosage_unit_weight: string;
  total_dosage_unit_weight_unit: string;
  batch_size: string | null;
  batch_size_unit: string;
  overage_percentage: string | null;
  maximum_dosage_units_per_day: string | null;
  dosing_basis: string;
  rationale: string;
  created_at: string;
}

export interface FormulationComponent {
  public_id: string;
  component_type: "active" | "inactive";
  ingredient_name: string;
  resolved_ingredient_public_id: string | null;
  resolved_unii: string;
  function: string;
  grade: string;
  quantity_per_dosage_unit: string;
  quantity_unit: string;
  percentage_w_w_snapshot: string | null;
  quantity_per_batch: string | null;
  batch_quantity_unit: string;
  overage_amount: string | null;
  justification: string;
  specification_reference: string;
  evidence_document_reference: string | null;
  display_order: number;
}

export interface DosingRegimen {
  public_id: string;
  units_per_administration: string;
  administrations_per_day: string;
  maximum_units_per_day: string;
  patient_population: string;
  basis: string;
  source_justification: string;
}

export const formulations = {
  products: {
    list: (tenantSlug: string, params?: { page?: number }) => {
      const qs = new URLSearchParams();
      if (params?.page) qs.set("page", String(params.page));
      const query = qs.toString() ? `?${qs}` : "";
      return apiRequest<PaginatedResponse<ProductDevelopmentRecord>>(
        `/api/regx/v1/formulations/products/${query}`,
        { headers: { "X-Tenant-Slug": tenantSlug } }
      );
    },

    get: (tenantSlug: string, publicId: string) =>
      apiRequest<ProductDevelopmentRecord>(`/api/regx/v1/formulations/products/${publicId}/`, {
        headers: { "X-Tenant-Slug": tenantSlug },
      }),

    create: (
      tenantSlug: string,
      data: {
        product_code: string;
        proposed_product_name: string;
        active_ingredient: string;
        is_combination_product?: boolean;
        release_type?: string;
        route?: string;
        dosage_form?: string;
        regulatory_market_context?: string;
      }
    ) =>
      apiRequest<ProductDevelopmentRecord>("/api/regx/v1/formulations/products/", {
        method: "POST",
        headers: { "X-Tenant-Slug": tenantSlug },
        body: data,
      }),

    selectReference: (
      tenantSlug: string,
      publicId: string,
      data: {
        application_number: string;
        product_number: string;
        product_public_id: string;
        release_public_id: string;
        justification?: string;
      }
    ) =>
      apiRequest<ProductDevelopmentRecord>(
        `/api/regx/v1/formulations/products/${publicId}/select-reference/`,
        { method: "POST", headers: { "X-Tenant-Slug": tenantSlug }, body: data }
      ),
  },

  versions: {
    create: (
      tenantSlug: string,
      productPublicId: string,
      data: {
        total_dosage_unit_weight: string;
        total_dosage_unit_weight_unit: string;
        batch_size?: string;
        batch_size_unit?: string;
        overage_percentage?: string;
        maximum_dosage_units_per_day?: string;
        dosing_basis?: string;
        rationale?: string;
      }
    ) =>
      apiRequest<FormulationVersion>(
        `/api/regx/v1/formulations/products/${productPublicId}/versions/`,
        { method: "POST", headers: { "X-Tenant-Slug": tenantSlug }, body: data }
      ),

    get: (tenantSlug: string, publicId: string) =>
      apiRequest<FormulationVersion>(`/api/regx/v1/formulations/versions/${publicId}/`, {
        headers: { "X-Tenant-Slug": tenantSlug },
      }),

    list: (tenantSlug: string, productPublicId: string) =>
      apiRequest<PaginatedResponse<FormulationVersion>>(
        `/api/regx/v1/formulations/products/${productPublicId}/versions/`,
        { headers: { "X-Tenant-Slug": tenantSlug } }
      ),
  },

  components: {
    create: (
      tenantSlug: string,
      versionPublicId: string,
      data: {
        component_type: "active" | "inactive";
        ingredient_name: string;
        quantity_per_dosage_unit: string;
        quantity_unit: string;
        function?: string;
        justification?: string;
      }
    ) =>
      apiRequest<FormulationComponent>(
        `/api/regx/v1/formulations/versions/${versionPublicId}/components/`,
        { method: "POST", headers: { "X-Tenant-Slug": tenantSlug }, body: data }
      ),

    list: (tenantSlug: string, versionPublicId: string) =>
      apiRequest<FormulationComponent[]>(
        `/api/regx/v1/formulations/versions/${versionPublicId}/components/`,
        { headers: { "X-Tenant-Slug": tenantSlug } }
      ),
  },

  dosingRegimens: {
    create: (
      tenantSlug: string,
      versionPublicId: string,
      data: {
        units_per_administration: string;
        administrations_per_day: string;
        maximum_units_per_day: string;
        patient_population?: string;
        basis?: string;
        source_justification?: string;
      }
    ) =>
      apiRequest<DosingRegimen>(
        `/api/regx/v1/formulations/versions/${versionPublicId}/dosing-regimens/`,
        { method: "POST", headers: { "X-Tenant-Slug": tenantSlug }, body: data }
      ),

    list: (tenantSlug: string, versionPublicId: string) =>
      apiRequest<DosingRegimen[]>(
        `/api/regx/v1/formulations/versions/${versionPublicId}/dosing-regimens/`,
        { headers: { "X-Tenant-Slug": tenantSlug } }
      ),
  },
};

// ---------------------------------------------------------------------------
// IID assessment
// ---------------------------------------------------------------------------

export type MatchStatus =
  | "EXACT_MATCH"
  | "MULTIPLE_EXACT_MATCHES"
  | "INGREDIENT_AMBIGUOUS"
  | "ROUTE_MISMATCH"
  | "DOSAGE_FORM_MISMATCH"
  | "NO_MATCHING_IID_PRECEDENT"
  | "POTENCY_UNAVAILABLE"
  | "MDE_UNAVAILABLE"
  | "UNIT_MISMATCH"
  | "NOT_COMPARABLE"
  | "REVIEW_REQUIRED";

export type PrecedentDecisionStatus =
  | "PASS_WITH_IID_PRECEDENT"
  | "REVIEW_REQUIRED"
  | "EXCEEDS_IID_PRECEDENT"
  | "NO_MATCH"
  | "NOT_COMPARABLE";

export interface MatchCandidate {
  precedent_record_public_id: string;
  ingredient_name: string;
  route: string;
  dosage_form: string;
  potency_amount: string | null;
  potency_unit: string | null;
  maximum_daily_exposure: string | null;
  mde_unit: string | null;
  calculability_status: string;
}

export interface AssessmentPreview {
  match_status: MatchStatus;
  candidates: MatchCandidate[];
  selected_record: MatchCandidate | null;
  calculations: Record<string, Record<string, unknown>>;
  decision_status: PrecedentDecisionStatus;
  decision_note: string;
  escalation_required: boolean;
  // Set only when identity was resolved through a raw substance/UNII/CAS
  // lookup rather than an already-known ingredient_public_id.
  substance_mapping_public_id?: string | null;
  substance_resolution_status?: string | null;
}

export interface PreviewRequest {
  // Supply exactly one identity path: an already-resolved ingredient, or a
  // raw substance identity resolved via the governed synonym-mapping
  // service (approved mappings only -- proposed/rejected mappings never
  // produce a confirmed match).
  ingredient_public_id?: string;
  substance_name?: string;
  substance_unii?: string;
  substance_cas?: string;
  route_code: string;
  dosage_form_code: string;
  active_release_public_id: string;
  proposed_quantity_per_unit: string;
  proposed_quantity_unit: string;
  total_dosage_unit_weight: string;
  total_dosage_unit_weight_unit: string;
  maximum_dosage_units_per_day?: string;
  density_g_per_ml?: string;
  selected_precedent_record_public_id?: string;
}

export const iidAssessments = {
  preview: (tenantSlug: string, data: PreviewRequest) =>
    apiRequest<AssessmentPreview>("/api/regx/v1/iid-assessments/preview/", {
      method: "POST",
      headers: { "X-Tenant-Slug": tenantSlug },
      body: data,
    }),

  snapshot: (
    tenantSlug: string,
    data: PreviewRequest & {
      formulation_component_public_id: string;
      formulation_version_public_id: string;
    }
  ) =>
    apiRequest<{ public_id: string } & AssessmentPreview>("/api/regx/v1/iid-assessments/snapshot/", {
      method: "POST",
      headers: { "X-Tenant-Slug": tenantSlug },
      body: data,
    }),

  get: (tenantSlug: string, publicId: string) =>
    apiRequest<AssessmentSnapshotDetail>(`/api/regx/v1/iid-assessments/${publicId}/`, {
      headers: { "X-Tenant-Slug": tenantSlug },
    }),
};

export interface AssessmentSnapshotDetail {
  public_id: string;
  formulation_component_public_id: string;
  formulation_version_public_id: string;
  iid_release_public_id: string | null;
  iid_precedent_record_public_id: string | null;
  iid_substance_mapping_public_id: string | null;
  iid_ingredient_name: string;
  iid_route: string;
  iid_dosage_form: string;
  iid_potency_amount: string | null;
  iid_potency_unit: string;
  iid_mde: string | null;
  iid_mde_unit: string;
  proposed_quantity_per_unit: string | null;
  proposed_quantity_unit: string;
  proposed_daily_exposure: string | null;
  calculation_results: Record<string, Record<string, unknown>>;
  match_status: MatchStatus;
  decision_status: PrecedentDecisionStatus;
  decision_note: string;
  reviewer_confirmed_match: boolean;
  override_applied: boolean;
  override_justification: string;
  final_conclusion: string;
  created_at: string;
}

export type ChecklistVersionStatus =
  | "draft"
  | "under_review"
  | "returned"
  | "approved"
  | "active"
  | "superseded"
  | "rejected"
  | "retired";

/** OQ-8: what one execution of this checklist is about. Distinct from
 *  `scope_type`, which is about who owns the content. An empty string means the
 *  definition is not yet classified and no execution may be created against it. */
export type ChecklistExecutionScope = "formulation_component" | "formulation_version" | "";

export interface ChecklistDefinition {
  public_id: string;
  code: string;
  title: string;
  description: string;
  scope_type: "platform_master" | "tenant";
  // Optional as well as unioned: a server predating OQ-8 omits the key.
  execution_scope?: ChecklistExecutionScope;
  tenant_public_id: string | null;
  created_at: string;
}

export interface ChecklistVersion {
  public_id: string;
  definition_public_id: string;
  scope_type: "platform_master" | "tenant";
  version_number: number;
  status: ChecklistVersionStatus;
  effective_date: string | null;
  expiry_date: string | null;
  regulatory_basis: string;
  change_summary: string;
  cloned_from_version_public_id: string | null;
  return_reason: string;
  submitted_by_email: string | null;
  reviewed_by_email: string | null;
  approved_by_email: string | null;
  activated_by_email: string | null;
  returned_at: string | null;
  rejected_at: string | null;
  retired_at: string | null;
  sections?: ChecklistSection[];
  created_at: string;
}

export interface ChecklistSection {
  public_id: string;
  code: string;
  title: string;
  description: string;
  display_order: number;
  criticality: string;
  questions?: ChecklistQuestion[];
}

export interface ChecklistQuestion {
  public_id: string;
  code: string;
  question_text: string;
  display_order: number;
  answer_type: string;
  data_source_classification: string;
  criticality: string;
  required: boolean;
  /**
   * Set when an applicability rule governs this question (M4D3-APP-008).
   * Its `is_not_applicable` / `not_applicable_reason` are then server-owned and
   * the governed update service rejects a client-supplied value for either
   * (M4D3-APP-009, 403 `applicability_server_controlled`). Already served by the
   * existing question representation — declared here, not newly exposed.
   */
  applicability_rule_public_id?: string | null;
  /**
   * `5A-DEC-002` — the governed select vocabulary, resolved server-side.
   *
   * `null` when the question declares no closed option list. The label is
   * approved content: it is displayed as given and is never derived from the
   * value here, because prettifying a code in the client would put unapproved
   * wording in front of a reviewer.
   */
  options?: ChecklistQuestionOption[] | null;
}

/** One governed select option: a stable machine value and its approved label. */
export interface ChecklistQuestionOption {
  value: string;
  label: string;
}

// 4D-2 Execution types — re-exported from the centralised mapper module.
// UI models are camelCase; DTO types mirror the Django snake_case API response.
export type {
  ChecklistExecution,
  ChecklistResponse,
  ChecklistExecutionDTO,
  ChecklistResponseDTO,
  CalculationOutcomeSummary,
  CalculationOutcomeSummaryDTO,
  CalculationStatus,
} from "./api/execution-mappers";

/**
 * `4D4-DEC-012` — tenant-scoped capability flags for the current caller.
 *
 * Named capabilities only: never raw permission codenames, roles or any other
 * authorization internals. The client learns what it may do, not how
 * permissions are modelled.
 */
export interface ChecklistCapabilities {
  can_override_response: boolean;
  /**
   * `4D4-DEC-012` extension — derived server-side from `PERM_REVIEW_EXECUTION`,
   * the same predicate `enter_reviewer_conclusion()` enforces with, so the flag
   * can never disagree with the service that owns it. Advisory only.
   */
  can_enter_reviewer_conclusion: boolean;
}

export const iigChecklists = {
  /**
   * Advisory UI metadata **only**. The backend remains authoritative — a client
   * that ignores these flags still receives the same governed refusal, so this
   * must never be treated as a security boundary.
   */
  capabilities: (tenantSlug: string) =>
    apiRequest<ChecklistCapabilities>("/api/regx/v1/iig-checklists/capabilities/", {
      headers: { "X-Tenant-Slug": tenantSlug },
    }),

  definitions: {
    list: (tenantSlug: string, params?: { page?: number }) => {
      const qs = new URLSearchParams();
      if (params?.page) qs.set("page", String(params.page));
      const query = qs.toString() ? `?${qs}` : "";
      return apiRequest<PaginatedResponse<ChecklistDefinition>>(
        `/api/regx/v1/iig-checklists/definitions/${query}`,
        { headers: { "X-Tenant-Slug": tenantSlug } }
      );
    },

    get: (tenantSlug: string, publicId: string) =>
      apiRequest<ChecklistDefinition>(`/api/regx/v1/iig-checklists/definitions/${publicId}/`, {
        headers: { "X-Tenant-Slug": tenantSlug },
      }),

    create: (
      tenantSlug: string,
      data: {
        code: string;
        title: string;
        description?: string;
        scope_type: string;
        // OQ-8: required for the definition to be executable at all. Omitting it
        // creates an unclassified definition, which the server refuses to run.
        execution_scope?: ChecklistExecutionScope;
      }
    ) =>
      apiRequest<ChecklistDefinition>("/api/regx/v1/iig-checklists/definitions/", {
        method: "POST",
        headers: { "X-Tenant-Slug": tenantSlug },
        body: data,
      }),

    remove: (tenantSlug: string, publicId: string) =>
      apiRequest<void>(`/api/regx/v1/iig-checklists/definitions/${publicId}/`, {
        method: "DELETE",
        headers: { "X-Tenant-Slug": tenantSlug },
      }),

    clone: (
      tenantSlug: string,
      publicId: string,
      data: {
        source_version_public_id: string;
        target_scope_type: string;
        target_tenant_public_id?: string;
        new_code: string;
        new_title: string;
        reason?: string;
      }
    ) =>
      apiRequest<
        ChecklistDefinition & {
          current_version: Pick<
            ChecklistVersion,
            "public_id" | "version_number" | "status" | "cloned_from_version_public_id"
          >;
        }
      >(`/api/regx/v1/iig-checklists/definitions/${publicId}/clone/`, {
        method: "POST",
        headers: { "X-Tenant-Slug": tenantSlug },
        body: data,
      }),
  },

  versions: {
    listForDefinition: (tenantSlug: string, definitionPublicId: string) =>
      apiRequest<PaginatedResponse<ChecklistVersion>>(
        `/api/regx/v1/iig-checklists/definitions/${definitionPublicId}/versions/`,
        { headers: { "X-Tenant-Slug": tenantSlug } }
      ),

    create: (tenantSlug: string, definitionPublicId: string) =>
      apiRequest<ChecklistVersion>(
        `/api/regx/v1/iig-checklists/definitions/${definitionPublicId}/versions/`,
        { method: "POST", headers: { "X-Tenant-Slug": tenantSlug } }
      ),

    get: (tenantSlug: string, publicId: string) =>
      apiRequest<ChecklistVersion>(`/api/regx/v1/iig-checklists/versions/${publicId}/`, {
        headers: { "X-Tenant-Slug": tenantSlug },
      }),

    submitReview: (tenantSlug: string, publicId: string, reason?: string) =>
      apiRequest<ChecklistVersion>(
        `/api/regx/v1/iig-checklists/versions/${publicId}/submit-review/`,
        { method: "POST", headers: { "X-Tenant-Slug": tenantSlug }, body: { reason } }
      ),

    approve: (tenantSlug: string, publicId: string, reason?: string) =>
      apiRequest<ChecklistVersion>(`/api/regx/v1/iig-checklists/versions/${publicId}/approve/`, {
        method: "POST",
        headers: { "X-Tenant-Slug": tenantSlug },
        body: { reason },
      }),

    return: (tenantSlug: string, publicId: string, reason: string) =>
      apiRequest<ChecklistVersion>(`/api/regx/v1/iig-checklists/versions/${publicId}/return/`, {
        method: "POST",
        headers: { "X-Tenant-Slug": tenantSlug },
        body: { reason },
      }),

    reject: (tenantSlug: string, publicId: string, reason?: string) =>
      apiRequest<ChecklistVersion>(`/api/regx/v1/iig-checklists/versions/${publicId}/reject/`, {
        method: "POST",
        headers: { "X-Tenant-Slug": tenantSlug },
        body: { reason },
      }),

    activate: (tenantSlug: string, publicId: string, reason?: string) =>
      apiRequest<ChecklistVersion>(`/api/regx/v1/iig-checklists/versions/${publicId}/activate/`, {
        method: "POST",
        headers: { "X-Tenant-Slug": tenantSlug },
        body: { reason },
      }),

    supersede: (tenantSlug: string, publicId: string, reason?: string) =>
      apiRequest<ChecklistVersion>(`/api/regx/v1/iig-checklists/versions/${publicId}/supersede/`, {
        method: "POST",
        headers: { "X-Tenant-Slug": tenantSlug },
        body: { reason },
      }),

    retire: (tenantSlug: string, publicId: string, reason?: string) =>
      apiRequest<ChecklistVersion>(`/api/regx/v1/iig-checklists/versions/${publicId}/retire/`, {
        method: "POST",
        headers: { "X-Tenant-Slug": tenantSlug },
        body: { reason },
      }),
  },

  // 4D-2 Execution API
  // Django returns snake_case JSON; toChecklistExecution/toChecklistResponse
  // map each DTO to the camelCase UI model at the single boundary here.
  executions: {
    list: (tenantSlug: string, params?: { page?: number }) => {
      const qs = new URLSearchParams();
      if (params?.page) qs.set("page", String(params.page));
      const query = qs.toString() ? `?${qs}` : "";
      return apiRequest<PaginatedResponse<ChecklistExecutionDTO>>(
        `/api/regx/v1/iig-checklists/executions/${query}`,
        { headers: { "X-Tenant-Slug": tenantSlug } }
      ).then((page) => ({ ...page, results: page.results.map(toChecklistExecution) }));
    },

    create: (
      tenantSlug: string,
      data: {
        checklist_version_public_id: string;
        formulation_version_public_id: string;
        // OQ-8: required by the server whenever the checklist content reads
        // execution-level iid.* values.
        subject_component_public_id?: string;
      }
    ) =>
      apiRequest<ChecklistExecutionDTO>("/api/regx/v1/iig-checklists/executions/", {
        method: "POST",
        headers: { "X-Tenant-Slug": tenantSlug },
        body: data,
      }).then(toChecklistExecution),

    get: (tenantSlug: string, publicId: string) =>
      apiRequest<ChecklistExecutionDTO>(`/api/regx/v1/iig-checklists/executions/${publicId}/`, {
        headers: { "X-Tenant-Slug": tenantSlug },
      }).then(toChecklistExecution),

    submitReview: (tenantSlug: string, publicId: string) =>
      apiRequest<ChecklistExecutionDTO>(
        `/api/regx/v1/iig-checklists/executions/${publicId}/submit-review/`,
        { method: "POST", headers: { "X-Tenant-Slug": tenantSlug }, body: {} }
      ).then(toChecklistExecution),

    approve: (tenantSlug: string, publicId: string, reviewerConclusionNote: string) =>
      apiRequest<ChecklistExecutionDTO>(
        `/api/regx/v1/iig-checklists/executions/${publicId}/approve/`,
        {
          method: "POST",
          headers: { "X-Tenant-Slug": tenantSlug },
          body: { reviewer_conclusion_note: reviewerConclusionNote },
        }
      ).then(toChecklistExecution),

    return: (tenantSlug: string, publicId: string, returnReason: string) =>
      apiRequest<ChecklistExecutionDTO>(
        `/api/regx/v1/iig-checklists/executions/${publicId}/return/`,
        {
          method: "POST",
          headers: { "X-Tenant-Slug": tenantSlug },
          body: { return_reason: returnReason },
        }
      ).then(toChecklistExecution),

    reject: (tenantSlug: string, publicId: string) =>
      apiRequest<ChecklistExecutionDTO>(
        `/api/regx/v1/iig-checklists/executions/${publicId}/reject/`,
        { method: "POST", headers: { "X-Tenant-Slug": tenantSlug }, body: {} }
      ).then(toChecklistExecution),

    cancel: (tenantSlug: string, publicId: string) =>
      apiRequest<ChecklistExecutionDTO>(
        `/api/regx/v1/iig-checklists/executions/${publicId}/cancel/`,
        { method: "POST", headers: { "X-Tenant-Slug": tenantSlug }, body: {} }
      ).then(toChecklistExecution),

    supersede: (tenantSlug: string, publicId: string) =>
      apiRequest<ChecklistExecutionDTO>(
        `/api/regx/v1/iig-checklists/executions/${publicId}/supersede/`,
        { method: "POST", headers: { "X-Tenant-Slug": tenantSlug }, body: {} }
      ).then(toChecklistExecution),

    responses: {
      /**
       * The complete response collection for one execution.
       *
       * The endpoint is paginated (PageNumberPagination, page_size 25), so the
       * payload is `{count, next, previous, results}` — not a bare array. This
       * helper had no caller until the 4D-3 editing UI, so the earlier array
       * typing was never exercised; calling `.map` on the envelope threw.
       *
       * Every page is followed, because nothing bounds an execution to one
       * page: `create_execution()` creates one response per question and no
       * enforced maximum question count exists. Returning only the first page
       * would silently hide responses — and, worse for 4D-3, could omit a
       * recalculated dependent, so the cascade would look like it had not run.
       *
       * Termination is driven by `next === null` rather than a page ceiling, so
       * there is no arbitrary limit. `next` is an absolute URL, so it is reduced
       * to a path for `apiRequest`, which preserves the tenant header on each
       * request. A repeated path aborts the walk rather than looping forever.
       */
      list: async (tenantSlug: string, executionPublicId: string) => {
        const headers = { "X-Tenant-Slug": tenantSlug };
        let path: string | null =
          `/api/regx/v1/iig-checklists/executions/${executionPublicId}/responses/`;
        const seen = new Set<string>();
        const dtos: ChecklistResponseDTO[] = [];

        while (path !== null) {
          if (seen.has(path)) break; // defensive: a server that never advances
          seen.add(path);
          const page: PaginatedResponse<ChecklistResponseDTO> = await apiRequest<
            PaginatedResponse<ChecklistResponseDTO>
          >(path, { headers });
          // Server order is authoritative (created_at) and is preserved by
          // appending each page in the order received.
          dtos.push(...page.results);
          path = page.next === null ? null : toApiPath(page.next);
        }

        return dtos.map(toChecklistResponse);
      },

      /**
       * Update one governed response.
       *
       * ``expected_version`` is mandatory (M4D3-VER-002): the backend rejects a
       * payload without it with ``expected_version_required``, and optimistic
       * concurrency is not opt-in. It must be the ``version`` of the response
       * currently loaded from the server — never defaulted, never synthesised,
       * and never remembered across a refetch.
       *
       * A ``409`` with ``stale_version`` means the row moved underneath us; the
       * caller must refetch authoritative state rather than retry blindly.
       */
      /**
       * `override_reason` is deliberately absent from this payload. It was
       * accepted and silently discarded before Milestone 4D-4 — the ordinary
       * update path never wrote it. `4D4-DEC-007` gives overrides their own
       * governed action, and the backend now rejects the field here with
       * `unknown_field`, so sending it would fail the request outright rather
       * than be ignored. Use the override action instead.
       */
      update: (
        tenantSlug: string,
        executionPublicId: string,
        responsePublicId: string,
        data: {
          expected_version: number;
          raw_value?: unknown;
          is_not_applicable?: boolean;
          not_applicable_reason?: string | null;
        }
      ) =>
        apiRequest<ChecklistResponseDTO>(
          `/api/regx/v1/iig-checklists/executions/${executionPublicId}/responses/${responsePublicId}/`,
          { method: "PATCH", headers: { "X-Tenant-Slug": tenantSlug }, body: data }
        ).then(toChecklistResponse),

      /**
       * `4D4-DEC-007` — the dedicated governed override action.
       *
       * Separate from `update` by design: §12 requires enforcement at the
       * transition boundary, and `system_derived_value` / `override_reason`
       * stay off the ordinary PATCH entirely (§AC.5).
       *
       * Only an `FDA_DERIVED_DEFAULT` response may be overridden, only while
       * the execution is editable, and only by a caller holding
       * `iig_checklist.override_execution` (Reviewer or VP). All three are
       * enforced server-side — this client cannot make them true.
       *
       * `expected_version` is mandatory and must be the loaded response's
       * `version`. There is no clear-override operation: §AC.4 defers it.
       */
      override: (
        tenantSlug: string,
        executionPublicId: string,
        responsePublicId: string,
        data: {
          expected_version: number;
          raw_value: unknown;
          override_reason: string;
        }
      ) =>
        apiRequest<ChecklistResponseDTO>(
          `/api/regx/v1/iig-checklists/executions/${executionPublicId}/responses/${responsePublicId}/override/`,
          { method: "POST", headers: { "X-Tenant-Slug": tenantSlug }, body: data }
        ).then(toChecklistResponse),

      /**
       * The dedicated governed **per-response** reviewer-conclusion action.
       *
       * Deliberately not `executions.approve()`. Those are two different
       * concepts: `approve()` carries the execution-level
       * `reviewer_conclusion_note` that closes the whole review, whereas this
       * writes the governed answer of one `REVIEWER_CONCLUSION` response.
       * Reaching for `approve()` here would both skip the per-response audit
       * and history trail and end the review as a side effect of answering a
       * question.
       *
       * Nor is it the ordinary response PATCH: `response_validation.py` refuses
       * a `reviewer_conclusion` raw_value on that path outright.
       *
       * The accepted client fields are exactly these three — the serializer
       * rejects anything else with `unknown_field`, so reviewer identity,
       * timestamps, `confirmed_by` / `confirmed_at`, history and
       * `data_source_type_snapshot` are never sent. All of that provenance is
       * server-derived from the authenticated actor.
       *
       * `expected_version` must be the loaded response's `version` as a JSON
       * **integer** (`4D4-DEC-013`): the backend applies the shared strict
       * validator, so `"1"`, `1.0` and `"1.0"` are refused with a governed 400
       * `invalid_expected_version` rather than silently coerced to 1.
       *
       * `correction_reason` is required by the service only when amending an
       * existing conclusion, so it is optional here and omitted on first entry.
       *
       * Governed refusals a caller must handle: 400
       * `invalid_expected_version` / `reviewer_conclusion_empty` /
       * `reviewer_conclusion_too_long` /
       * `reviewer_conclusion_correction_reason_required`, 403, and 409
       * `reviewer_conclusion_stale_version` / `reviewer_conclusion_invalid_state`
       * — a 409 means refetch authoritative state, never retry blindly.
       */
      reviewerConclusion: (
        tenantSlug: string,
        executionPublicId: string,
        responsePublicId: string,
        data: {
          raw_value: { value: string };
          expected_version: number;
          correction_reason?: string;
        }
      ) =>
        apiRequest<ChecklistResponseDTO>(
          `/api/regx/v1/iig-checklists/executions/${executionPublicId}/responses/${responsePublicId}/reviewer-conclusion/`,
          { method: "POST", headers: { "X-Tenant-Slug": tenantSlug }, body: data }
        ).then(toChecklistResponse),
    },
  },
};

export const mfa = {
  setup: () => apiRequest<{ totp_uri: string; recovery_codes: string[] }>("/api/regx/v1/mfa/setup/", { method: "POST" }),

  verify: (code: string) =>
    apiRequest<{ detail: string }>("/api/regx/v1/mfa/verify/", {
      method: "POST",
      body: { code },
    }),

  useRecovery: (recovery_code: string) =>
    apiRequest<{ detail: string }>("/api/regx/v1/mfa/recovery/", {
      method: "POST",
      body: { recovery_code },
    }),
};

// ---------------------------------------------------------------------------
// Workflows — generic regulatory workflow engine (Milestone 6)
//
// State is never sent as a field. It changes only through the action endpoints
// below; the API rejects a PATCH carrying `state`.
// ---------------------------------------------------------------------------

export interface WorkflowUserRef {
  public_id: string;
  email: string;
  full_name: string;
}

export type WorkflowState =
  | "draft"
  | "submitted"
  | "in_review"
  | "approved"
  | "rejected"
  | "cancelled";

export type WorkflowAction =
  | "submit"
  | "begin_review"
  | "approve"
  | "reject"
  | "cancel"
  | "return_to_draft";

export interface WorkflowItem {
  public_id: string;
  title: string;
  description: string;
  state: WorkflowState;
  created_by: WorkflowUserRef | null;
  assigned_to: WorkflowUserRef | null;
  assigned_at: string | null;
  due_at: string | null;
  is_overdue: boolean;
  is_terminal: boolean;
  /** Backend-computed: structurally legal AND permitted for this caller. */
  available_actions: WorkflowAction[];
  created_at: string;
  updated_at: string;
}

export interface WorkflowTransitionRecord {
  public_id: string;
  action: string;
  from_state: WorkflowState;
  to_state: WorkflowState;
  actor: WorkflowUserRef | null;
  reason: string;
  created_at: string;
}

/** Actions the backend requires a non-blank reason for. Mirrored here only to
 *  prompt the user before the round trip -- the backend is authoritative and
 *  rejects a blank reason regardless of what the UI does. */
export const WORKFLOW_REASON_REQUIRED: WorkflowAction[] = ["reject", "cancel"];

const workflowActionPath: Record<WorkflowAction, string> = {
  submit: "submit",
  begin_review: "begin-review",
  approve: "approve",
  reject: "reject",
  cancel: "cancel",
  return_to_draft: "return-to-draft",
};

export const workflows = {
  list: (tenantSlug: string, params?: { page?: number; state?: WorkflowState }) => {
    const qs = new URLSearchParams();
    if (params?.page) qs.set("page", String(params.page));
    if (params?.state) qs.set("state", params.state);
    const query = qs.toString() ? `?${qs}` : "";
    return apiRequest<PaginatedResponse<WorkflowItem>>(`/api/regx/v1/workflows/${query}`, {
      headers: { "X-Tenant-Slug": tenantSlug },
    });
  },

  get: (tenantSlug: string, publicId: string) =>
    apiRequest<WorkflowItem>(`/api/regx/v1/workflows/${publicId}/`, {
      headers: { "X-Tenant-Slug": tenantSlug },
    }),

  create: (
    tenantSlug: string,
    data: { title: string; description?: string; due_at?: string | null }
  ) =>
    apiRequest<WorkflowItem>("/api/regx/v1/workflows/", {
      method: "POST",
      headers: { "X-Tenant-Slug": tenantSlug },
      body: data,
    }),

  updateDraft: (
    tenantSlug: string,
    publicId: string,
    data: { title?: string; description?: string; due_at?: string | null }
  ) =>
    apiRequest<WorkflowItem>(`/api/regx/v1/workflows/${publicId}/`, {
      method: "PATCH",
      headers: { "X-Tenant-Slug": tenantSlug },
      body: data,
    }),

  transition: (
    tenantSlug: string,
    publicId: string,
    action: WorkflowAction,
    reason?: string
  ) =>
    apiRequest<WorkflowItem>(
      `/api/regx/v1/workflows/${publicId}/${workflowActionPath[action]}/`,
      {
        method: "POST",
        headers: { "X-Tenant-Slug": tenantSlug },
        body: { reason: reason ?? "" },
      }
    ),

  assign: (tenantSlug: string, publicId: string, assignedTo: string | null) =>
    apiRequest<WorkflowItem>(`/api/regx/v1/workflows/${publicId}/assign/`, {
      method: "POST",
      headers: { "X-Tenant-Slug": tenantSlug },
      body: { assigned_to: assignedTo },
    }),

  history: (tenantSlug: string, publicId: string) =>
    apiRequest<WorkflowTransitionRecord[]>(`/api/regx/v1/workflows/${publicId}/history/`, {
      headers: { "X-Tenant-Slug": tenantSlug },
    }),
};


// ---------------------------------------------------------------------------
// Workflow evidence (Milestone 7)
//
// Evidence references an exact DocumentVersion, never a Document. Uploading a
// newer version cannot change what an existing link means.
//
// `document` is present only when the caller holds `documents.view`. Workflow
// permission and document permission are separate gates, so a caller may see
// that evidence exists without seeing document detail.
// ---------------------------------------------------------------------------

export interface WorkflowEvidenceDocument {
  title: string;
  document_type: string;
  version_number: number;
  original_filename: string;
  size_bytes: number;
  sha256_checksum: string;
  scan_status: string;
  uploaded_at: string;
}

export interface WorkflowEvidenceLink {
  public_id: string;
  label: string;
  linked_by: WorkflowUserRef | null;
  linked_at: string;
  document_version_public_id: string;
  document_public_id: string;
  /** Absent when the caller lacks `documents.view` in this tenant. */
  document?: WorkflowEvidenceDocument;
}

export const workflowEvidence = {
  list: (tenantSlug: string, workflowPublicId: string) =>
    apiRequest<WorkflowEvidenceLink[]>(
      `/api/regx/v1/workflows/${workflowPublicId}/evidence/`,
      { headers: { "X-Tenant-Slug": tenantSlug } }
    ),

  link: (
    tenantSlug: string,
    workflowPublicId: string,
    data: { document_version_public_id: string; label?: string }
  ) =>
    apiRequest<WorkflowEvidenceLink>(
      `/api/regx/v1/workflows/${workflowPublicId}/evidence/`,
      { method: "POST", headers: { "X-Tenant-Slug": tenantSlug }, body: data }
    ),

  unlink: (tenantSlug: string, workflowPublicId: string, evidencePublicId: string) =>
    apiRequest<WorkflowEvidenceLink>(
      `/api/regx/v1/workflows/${workflowPublicId}/evidence/${evidencePublicId}/`,
      { method: "DELETE", headers: { "X-Tenant-Slug": tenantSlug } }
    ),
};

// ---------------------------------------------------------------------------
// Regulatory cases (Milestone 8)
//
// A case composes work that other modules own. `restricted` on a link row means
// the caller holds the case permission but not that module's own view
// permission, so the server sent identity without detail -- see the backend's
// projection.py. The optional detail objects are absent in that case, which is
// why every one of them is optional here rather than nullable.
// ---------------------------------------------------------------------------
export type CaseStatus = "open" | "on_hold" | "completed" | "cancelled";

export interface RegulatoryCase {
  public_id: string;
  case_number: string;
  title: string;
  product_name: string;
  product_code: string;
  market: string;
  authority: string;
  submission_type: string;
  status: CaseStatus;
  owner: { public_id: string; full_name: string } | null;
  target_date: string | null;
  description: string;
  created_by: { public_id: string; full_name: string } | null;
  created_at: string;
  updated_at: string;
  is_terminal: boolean;
}

export interface CasePermissions {
  can_edit: boolean;
  can_manage_links: boolean;
  can_complete: boolean;
  can_cancel: boolean;
  can_create: boolean;
}

interface BaseCaseLink {
  public_id: string;
  label: string;
  linked_at: string;
  linked_by: { full_name: string } | null;
  restricted?: true;
}

export interface CaseWorkflowLink extends BaseCaseLink {
  workflow_public_id: string;
  workflow?: {
    title: string;
    state: string;
    is_terminal: boolean;
    due_at: string | null;
    is_overdue: boolean;
  };
}

export interface CaseDocumentLink extends BaseCaseLink {
  document_public_id: string;
  document?: {
    title: string;
    document_type: string;
    status: string;
    current_version_number: number | null;
    scan_status: string | null;
  };
}

export interface CaseChecklistLink extends BaseCaseLink {
  execution_public_id: string;
  checklist?: { status: string; checklist_version_public_id: string };
}

export interface CaseSummary {
  // Link counts are case-level: the caller already sees one row per link.
  documents: number;
  workflows: number;
  checklists: number;
  // Workflow STATE is not. These are null unless the caller independently
  // holds `workflows.view`, so the summary cannot disclose what the rows
  // withhold.
  workflows_open: number | null;
  workflows_completed: number | null;
  evidence_links: number | null;
}

export interface CaseDetail {
  case: RegulatoryCase;
  workflows: CaseWorkflowLink[];
  documents: CaseDocumentLink[];
  checklists: CaseChecklistLink[];
  summary: CaseSummary;
  permissions: CasePermissions;
}

export interface CaseListResponse {
  results: RegulatoryCase[];
  permissions: CasePermissions;
}

const CASES = "/api/regx/v1/regulatory-cases";

export const regulatoryCases = {
  list: (tenantSlug: string, params?: { status?: string; search?: string }) => {
    const q = new URLSearchParams();
    if (params?.status) q.set("status", params.status);
    if (params?.search) q.set("search", params.search);
    const suffix = q.toString() ? `?${q.toString()}` : "";
    return apiRequest<CaseListResponse>(`${CASES}/${suffix}`, {
      headers: { "X-Tenant-Slug": tenantSlug },
    });
  },

  create: (
    tenantSlug: string,
    data: {
      title: string;
      product_name: string;
      market: string;
      submission_type: string;
      product_code?: string;
      authority?: string;
      target_date?: string | null;
      description?: string;
    }
  ) =>
    apiRequest<RegulatoryCase>(`${CASES}/`, {
      method: "POST",
      headers: { "X-Tenant-Slug": tenantSlug },
      body: data,
    }),

  get: (tenantSlug: string, publicId: string) =>
    apiRequest<CaseDetail>(`${CASES}/${publicId}/`, {
      headers: { "X-Tenant-Slug": tenantSlug },
    }),

  update: (tenantSlug: string, publicId: string, data: Record<string, unknown>) =>
    apiRequest<RegulatoryCase>(`${CASES}/${publicId}/`, {
      method: "PATCH",
      headers: { "X-Tenant-Slug": tenantSlug },
      body: data,
    }),

  complete: (tenantSlug: string, publicId: string, reason?: string) =>
    apiRequest<RegulatoryCase>(`${CASES}/${publicId}/complete/`, {
      method: "POST",
      headers: { "X-Tenant-Slug": tenantSlug },
      body: { reason: reason ?? "" },
    }),

  cancel: (tenantSlug: string, publicId: string, reason?: string) =>
    apiRequest<RegulatoryCase>(`${CASES}/${publicId}/cancel/`, {
      method: "POST",
      headers: { "X-Tenant-Slug": tenantSlug },
      body: { reason: reason ?? "" },
    }),

  // The kind is part of the path, matching the backend: a document permission
  // can never be aimed at a workflow by changing a body field.
  linkTarget: (
    tenantSlug: string,
    publicId: string,
    kind: "workflows" | "documents" | "checklists",
    targetPublicId: string,
    label?: string
  ) =>
    apiRequest<CaseWorkflowLink | CaseDocumentLink | CaseChecklistLink>(
      `${CASES}/${publicId}/${kind}/`,
      {
        method: "POST",
        headers: { "X-Tenant-Slug": tenantSlug },
        body: { target_public_id: targetPublicId, label: label ?? "" },
      }
    ),

  unlinkTarget: (
    tenantSlug: string,
    publicId: string,
    kind: "workflows" | "documents" | "checklists",
    linkPublicId: string
  ) =>
    apiRequest<void>(`${CASES}/${publicId}/${kind}/${linkPublicId}/`, {
      method: "DELETE",
      headers: { "X-Tenant-Slug": tenantSlug },
    }),
};


// ---------------------------------------------------------------------------
// Submission dossiers (Milestone 9)
//
// `readiness` is DERIVED by the backend and has no setter here on purpose: the
// one authoritative calculation lives server-side, and a client that recomputed
// it would drift. `restricted` on a link row means the caller holds the dossier
// permission but not that module's own view permission.
//
// Module counts are `number | null`, never defaulting to 0: null means withheld,
// and rendering 0 would assert something false about resources the caller
// cannot see.
// ---------------------------------------------------------------------------
export type DossierStatus = "open" | "on_hold" | "completed" | "cancelled";
export type SectionStatus =
  | "not_started"
  | "in_progress"
  | "blocked"
  | "complete"
  | "not_applicable";
export type Readiness = "not_ready" | "partially_ready" | "ready" | "not_applicable";
export type BlockerSeverity = "low" | "medium" | "high";

export interface SubmissionDossier {
  public_id: string;
  regulatory_case_public_id: string;
  title: string;
  description: string;
  status: DossierStatus;
  owner: { public_id: string; full_name: string } | null;
  target_date: string | null;
  created_by: { public_id: string; full_name: string } | null;
  created_at: string;
  updated_at: string;
  is_terminal: boolean;
}

export interface DossierSection {
  public_id: string;
  parent_public_id: string | null;
  section_code: string;
  title: string;
  description: string;
  notes: string;
  sequence: number;
  required: boolean;
  status: SectionStatus;
  readiness: Readiness;
  readiness_reason: string;
  owner: { public_id: string; full_name: string } | null;
  due_date: string | null;
  is_retired: boolean;
  created_at: string;
  updated_at: string;
}

export interface DossierBlocker {
  public_id: string;
  section_public_id: string;
  title: string;
  description: string;
  severity: BlockerSeverity;
  status: "open" | "resolved";
  created_by: { public_id: string; full_name: string } | null;
  created_at: string;
  resolved_by: { public_id: string; full_name: string } | null;
  resolved_at: string | null;
}

export interface DossierPermissions {
  can_create: boolean;
  can_edit: boolean;
  can_manage_sections: boolean;
  can_manage_links: boolean;
  can_manage_blockers: boolean;
  can_complete: boolean;
  can_cancel: boolean;
}

export interface DossierSummary {
  total_sections: number;
  required_sections: number;
  ready: number;
  partially_ready: number;
  not_ready: number;
  not_applicable: number;
  open_blockers: number;
  overall_readiness: Readiness;
  overall_reason: string;
}

export interface ModuleCounts {
  workflow_evidence_links: number | null;
}

interface BaseSectionLink {
  public_id: string;
  purpose: string;
  linked_at: string;
  linked_by: { full_name: string } | null;
  restricted?: true;
}

export interface SectionDocumentLink extends BaseSectionLink {
  document_public_id: string;
  document?: {
    title: string;
    document_type: string;
    status: string;
    current_version_number: number | null;
    scan_status: string | null;
  };
}

export interface SectionWorkflowLink extends BaseSectionLink {
  workflow_public_id: string;
  workflow?: {
    title: string;
    state: string;
    is_terminal: boolean;
    due_at: string | null;
    is_overdue: boolean;
  };
}

export interface SectionChecklistLink extends BaseSectionLink {
  execution_public_id: string;
  checklist?: { status: string; checklist_version_public_id: string };
}

export interface DossierDetail {
  dossier: SubmissionDossier;
  sections: DossierSection[];
  summary: DossierSummary;
  module_counts: ModuleCounts;
  permissions: DossierPermissions;
}

export interface SectionDetail {
  section: DossierSection;
  children: DossierSection[];
  documents: SectionDocumentLink[];
  workflows: SectionWorkflowLink[];
  checklists: SectionChecklistLink[];
  blockers: DossierBlocker[];
  module_counts: ModuleCounts;
  permissions: DossierPermissions;
}

const DOSSIER_V1 = "/api/regx/v1";

export const submissionDossiers = {
  listForCase: (tenantSlug: string, casePublicId: string) =>
    apiRequest<{ results: SubmissionDossier[]; permissions: DossierPermissions }>(
      `${DOSSIER_V1}/regulatory-cases/${casePublicId}/dossiers/`,
      { headers: { "X-Tenant-Slug": tenantSlug } }
    ),

  create: (
    tenantSlug: string,
    casePublicId: string,
    data: { title: string; description?: string; target_date?: string | null }
  ) =>
    apiRequest<SubmissionDossier>(`${DOSSIER_V1}/regulatory-cases/${casePublicId}/dossiers/`, {
      method: "POST",
      headers: { "X-Tenant-Slug": tenantSlug },
      body: data,
    }),

  get: (tenantSlug: string, publicId: string) =>
    apiRequest<DossierDetail>(`${DOSSIER_V1}/submission-dossiers/${publicId}/`, {
      headers: { "X-Tenant-Slug": tenantSlug },
    }),

  update: (tenantSlug: string, publicId: string, data: Record<string, unknown>) =>
    apiRequest<SubmissionDossier>(`${DOSSIER_V1}/submission-dossiers/${publicId}/`, {
      method: "PATCH",
      headers: { "X-Tenant-Slug": tenantSlug },
      body: data,
    }),

  complete: (tenantSlug: string, publicId: string, reason?: string) =>
    apiRequest<SubmissionDossier>(`${DOSSIER_V1}/submission-dossiers/${publicId}/complete/`, {
      method: "POST",
      headers: { "X-Tenant-Slug": tenantSlug },
      body: { reason: reason ?? "" },
    }),

  cancel: (tenantSlug: string, publicId: string, reason?: string) =>
    apiRequest<SubmissionDossier>(`${DOSSIER_V1}/submission-dossiers/${publicId}/cancel/`, {
      method: "POST",
      headers: { "X-Tenant-Slug": tenantSlug },
      body: { reason: reason ?? "" },
    }),

  createSection: (
    tenantSlug: string,
    dossierPublicId: string,
    data: {
      section_code: string;
      title: string;
      parent_public_id?: string | null;
      required?: boolean;
      due_date?: string | null;
      description?: string;
    }
  ) =>
    apiRequest<DossierSection>(
      `${DOSSIER_V1}/submission-dossiers/${dossierPublicId}/sections/`,
      { method: "POST", headers: { "X-Tenant-Slug": tenantSlug }, body: data }
    ),

  getSection: (tenantSlug: string, sectionPublicId: string) =>
    apiRequest<SectionDetail>(`${DOSSIER_V1}/dossier-sections/${sectionPublicId}/`, {
      headers: { "X-Tenant-Slug": tenantSlug },
    }),

  updateSection: (tenantSlug: string, sectionPublicId: string, data: Record<string, unknown>) =>
    apiRequest<DossierSection>(`${DOSSIER_V1}/dossier-sections/${sectionPublicId}/`, {
      method: "PATCH",
      headers: { "X-Tenant-Slug": tenantSlug },
      body: data,
    }),

  reorderSection: (tenantSlug: string, sectionPublicId: string, sequence: number) =>
    apiRequest<DossierSection>(`${DOSSIER_V1}/dossier-sections/${sectionPublicId}/reorder/`, {
      method: "POST",
      headers: { "X-Tenant-Slug": tenantSlug },
      body: { sequence },
    }),

  createBlocker: (
    tenantSlug: string,
    sectionPublicId: string,
    data: { title: string; description?: string; severity?: BlockerSeverity }
  ) =>
    apiRequest<DossierBlocker>(
      `${DOSSIER_V1}/dossier-sections/${sectionPublicId}/blockers/`,
      { method: "POST", headers: { "X-Tenant-Slug": tenantSlug }, body: data }
    ),

  resolveBlocker: (tenantSlug: string, blockerPublicId: string) =>
    apiRequest<DossierBlocker>(`${DOSSIER_V1}/section-blockers/${blockerPublicId}/resolve/`, {
      method: "POST",
      headers: { "X-Tenant-Slug": tenantSlug },
      body: {},
    }),

  // The kind is part of the path, matching the backend: a document permission
  // can never be aimed at a workflow by changing a body field.
  linkTarget: (
    tenantSlug: string,
    sectionPublicId: string,
    kind: "documents" | "workflows" | "checklists",
    targetPublicId: string,
    purpose?: string
  ) =>
    apiRequest<SectionDocumentLink | SectionWorkflowLink | SectionChecklistLink>(
      `${DOSSIER_V1}/dossier-sections/${sectionPublicId}/${kind}/`,
      {
        method: "POST",
        headers: { "X-Tenant-Slug": tenantSlug },
        body: { target_public_id: targetPublicId, purpose: purpose ?? "" },
      }
    ),

  unlinkTarget: (
    tenantSlug: string,
    sectionPublicId: string,
    kind: "documents" | "workflows" | "checklists",
    linkPublicId: string
  ) =>
    apiRequest<void>(
      `${DOSSIER_V1}/dossier-sections/${sectionPublicId}/${kind}/${linkPublicId}/`,
      { method: "DELETE", headers: { "X-Tenant-Slug": tenantSlug } }
    ),
};


// ===========================================================================
// Milestone 10 -- dossier blueprints
//
// Blueprints define structure; dossiers own execution. Instantiating a version
// produces ordinary governed dossier records that never read back to the
// blueprint, so publishing a later version cannot rewrite them.
//
// ACTIVE means "available for internal RegX dossier instantiation". It is not
// a regulatory, QA or agency approval, and there is deliberately no APPROVED
// state to reach.
// ===========================================================================
export type BlueprintVersionStatus = "draft" | "active" | "retired";

export interface BlueprintUserRef {
  public_id: string;
  full_name: string;
}

export interface DossierBlueprint {
  public_id: string;
  name: string;
  description: string;
  owner: BlueprintUserRef | null;
  created_by: BlueprintUserRef | null;
  is_archived: boolean;
  created_at: string;
  updated_at: string;
  current_version_number?: number | null;
  current_version_status?: BlueprintVersionStatus | null;
  current_version_public_id?: string | null;
  version_count?: number;
  instantiation_count?: number;
}

export interface BlueprintVersion {
  public_id: string;
  blueprint_public_id: string;
  version_number: number;
  status: BlueprintVersionStatus;
  notes: string;
  created_by: BlueprintUserRef | null;
  supersedes_public_id: string | null;
  activated_at: string | null;
  retired_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface BlueprintSection {
  public_id: string;
  parent_public_id: string | null;
  section_code: string;
  title: string;
  description: string;
  sequence: number;
  required: boolean;
  default_due_offset_days: number | null;
  is_retired: boolean;
}

export interface BlueprintPermissions {
  can_create: boolean;
  can_edit: boolean;
  can_manage_sections: boolean;
  can_create_version: boolean;
  can_activate: boolean;
  can_retire: boolean;
  can_instantiate: boolean;
  can_archive: boolean;
}

export interface BlueprintDetail extends DossierBlueprint {
  versions: BlueprintVersion[];
  permissions: BlueprintPermissions;
}

export interface BlueprintVersionDetail extends BlueprintVersion {
  blueprint: { public_id: string; name: string };
  sections: BlueprintSection[];
  section_count: number;
  instantiation_count: number;
  is_editable: boolean;
  permissions: BlueprintPermissions;
}

export interface BlueprintInstantiationResult {
  dossier_public_id: string;
  case_public_id: string;
  blueprint_public_id: string;
  version_public_id: string;
  version_number: number;
  section_count: number;
  dossier_route: string;
}

/**
 * What a dossier may say about where it came from.
 *
 * `blueprint_name` is present only when the caller independently holds
 * `dossier_blueprints.view`; otherwise `restricted` is true and the provenance
 * is still shown, without the tenant-authored name.
 */
export interface BlueprintProvenance {
  instantiated_from_blueprint: boolean;
  instantiation_public_id?: string;
  blueprint_public_id?: string;
  version_public_id?: string;
  version_number?: number;
  section_count?: number;
  instantiated_at?: string;
  blueprint_name?: string;
  restricted?: boolean;
}

export const dossierBlueprints = {
  list: (tenantSlug: string, params?: { search?: string; includeArchived?: boolean }) => {
    const query = new URLSearchParams();
    if (params?.search) query.set("search", params.search);
    if (params?.includeArchived) query.set("include_archived", "true");
    const suffix = query.toString() ? `?${query.toString()}` : "";
    return apiRequest<{ results: DossierBlueprint[]; permissions: BlueprintPermissions }>(
      `${DOSSIER_V1}/dossier-blueprints/${suffix}`,
      { headers: { "X-Tenant-Slug": tenantSlug } }
    );
  },

  create: (
    tenantSlug: string,
    data: { name: string; description?: string; owner_public_id?: string | null }
  ) =>
    apiRequest<DossierBlueprint>(`${DOSSIER_V1}/dossier-blueprints/`, {
      method: "POST",
      headers: { "X-Tenant-Slug": tenantSlug },
      body: data,
    }),

  get: (tenantSlug: string, publicId: string) =>
    apiRequest<BlueprintDetail>(`${DOSSIER_V1}/dossier-blueprints/${publicId}/`, {
      headers: { "X-Tenant-Slug": tenantSlug },
    }),

  update: (
    tenantSlug: string,
    publicId: string,
    data: { name?: string; description?: string; owner_public_id?: string | null }
  ) =>
    apiRequest<DossierBlueprint>(`${DOSSIER_V1}/dossier-blueprints/${publicId}/`, {
      method: "PATCH",
      headers: { "X-Tenant-Slug": tenantSlug },
      body: data,
    }),

  archive: (tenantSlug: string, publicId: string) =>
    apiRequest<DossierBlueprint>(`${DOSSIER_V1}/dossier-blueprints/${publicId}/archive/`, {
      method: "POST",
      headers: { "X-Tenant-Slug": tenantSlug },
      body: {},
    }),

  listVersions: (tenantSlug: string, blueprintPublicId: string) =>
    apiRequest<{ results: BlueprintVersion[]; permissions: BlueprintPermissions }>(
      `${DOSSIER_V1}/dossier-blueprints/${blueprintPublicId}/versions/`,
      { headers: { "X-Tenant-Slug": tenantSlug } }
    ),

  /**
   * Omitting `source_version_public_id` starts an empty draft; supplying it
   * clones that version's structure. There is deliberately no way to edit an
   * active version into the next revision.
   */
  createVersion: (
    tenantSlug: string,
    blueprintPublicId: string,
    data?: { source_version_public_id?: string | null; notes?: string }
  ) =>
    apiRequest<BlueprintVersion>(
      `${DOSSIER_V1}/dossier-blueprints/${blueprintPublicId}/versions/`,
      { method: "POST", headers: { "X-Tenant-Slug": tenantSlug }, body: data ?? {} }
    ),

  getVersion: (tenantSlug: string, versionPublicId: string) =>
    apiRequest<BlueprintVersionDetail>(
      `${DOSSIER_V1}/dossier-blueprint-versions/${versionPublicId}/`,
      { headers: { "X-Tenant-Slug": tenantSlug } }
    ),

  activateVersion: (tenantSlug: string, versionPublicId: string) =>
    apiRequest<BlueprintVersion>(
      `${DOSSIER_V1}/dossier-blueprint-versions/${versionPublicId}/activate/`,
      { method: "POST", headers: { "X-Tenant-Slug": tenantSlug }, body: {} }
    ),

  retireVersion: (tenantSlug: string, versionPublicId: string) =>
    apiRequest<BlueprintVersion>(
      `${DOSSIER_V1}/dossier-blueprint-versions/${versionPublicId}/retire/`,
      { method: "POST", headers: { "X-Tenant-Slug": tenantSlug }, body: {} }
    ),

  createSection: (
    tenantSlug: string,
    versionPublicId: string,
    data: {
      section_code: string;
      title: string;
      description?: string;
      parent_public_id?: string | null;
      required?: boolean;
      default_due_offset_days?: number | null;
    }
  ) =>
    apiRequest<BlueprintSection>(
      `${DOSSIER_V1}/dossier-blueprint-versions/${versionPublicId}/sections/`,
      { method: "POST", headers: { "X-Tenant-Slug": tenantSlug }, body: data }
    ),

  updateSection: (
    tenantSlug: string,
    sectionPublicId: string,
    data: {
      section_code?: string;
      title?: string;
      description?: string;
      parent_public_id?: string | null;
      required?: boolean;
      default_due_offset_days?: number | null;
    }
  ) =>
    apiRequest<BlueprintSection>(
      `${DOSSIER_V1}/dossier-blueprint-sections/${sectionPublicId}/`,
      { method: "PATCH", headers: { "X-Tenant-Slug": tenantSlug }, body: data }
    ),

  reorderSection: (tenantSlug: string, sectionPublicId: string, sequence: number) =>
    apiRequest<BlueprintSection>(
      `${DOSSIER_V1}/dossier-blueprint-sections/${sectionPublicId}/reorder/`,
      { method: "POST", headers: { "X-Tenant-Slug": tenantSlug }, body: { sequence } }
    ),

  retireSection: (tenantSlug: string, sectionPublicId: string) =>
    apiRequest<BlueprintSection>(
      `${DOSSIER_V1}/dossier-blueprint-sections/${sectionPublicId}/retire/`,
      { method: "POST", headers: { "X-Tenant-Slug": tenantSlug }, body: {} }
    ),

  /** The version comes from the path; the tenant is never sent by the client. */
  instantiate: (
    tenantSlug: string,
    versionPublicId: string,
    data: {
      regulatory_case_public_id: string;
      title: string;
      owner_public_id?: string | null;
      target_date?: string | null;
    }
  ) =>
    apiRequest<BlueprintInstantiationResult>(
      `${DOSSIER_V1}/dossier-blueprint-versions/${versionPublicId}/instantiate/`,
      { method: "POST", headers: { "X-Tenant-Slug": tenantSlug }, body: data }
    ),

  provenanceForDossier: (tenantSlug: string, dossierPublicId: string) =>
    apiRequest<BlueprintProvenance>(
      `${DOSSIER_V1}/submission-dossiers/${dossierPublicId}/blueprint-provenance/`,
      { headers: { "X-Tenant-Slug": tenantSlug } }
    ),
};
