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

export interface ChecklistDefinition {
  public_id: string;
  code: string;
  title: string;
  description: string;
  scope_type: "platform_master" | "tenant";
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

export const iigChecklists = {
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
      data: { code: string; title: string; description?: string; scope_type: string }
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
      data: { checklist_version_public_id: string; formulation_version_public_id: string }
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
       * The response collection for one execution.
       *
       * The endpoint is paginated (PageNumberPagination), so the payload is
       * `{count, next, previous, results}` — not a bare array. This helper had
       * no caller until the 4D-3 editing UI, so the earlier array typing was
       * never exercised; calling `.map` on the envelope threw at runtime.
       */
      list: (tenantSlug: string, executionPublicId: string) =>
        apiRequest<PaginatedResponse<ChecklistResponseDTO>>(
          `/api/regx/v1/iig-checklists/executions/${executionPublicId}/responses/`,
          { headers: { "X-Tenant-Slug": tenantSlug } }
        ).then((page) => page.results.map(toChecklistResponse)),

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
      update: (
        tenantSlug: string,
        executionPublicId: string,
        responsePublicId: string,
        data: {
          expected_version: number;
          raw_value?: unknown;
          is_not_applicable?: boolean;
          not_applicable_reason?: string | null;
          override_reason?: string;
        }
      ) =>
        apiRequest<ChecklistResponseDTO>(
          `/api/regx/v1/iig-checklists/executions/${executionPublicId}/responses/${responsePublicId}/`,
          { method: "PATCH", headers: { "X-Tenant-Slug": tenantSlug }, body: data }
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
