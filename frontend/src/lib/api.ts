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
