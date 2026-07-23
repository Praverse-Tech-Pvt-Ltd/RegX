/**
 * API client for REGX backend.
 * Auth tokens are NEVER stored in localStorage or sessionStorage.
 * Authentication uses secure HttpOnly session cookies set by Django.
 */

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
