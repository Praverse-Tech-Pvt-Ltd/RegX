// Synthetic, non-confidential fixtures for frontend unit/component tests.
import type {
  AssessmentPreview,
  Document,
  DocumentLocator,
  DocumentVersion,
  FdaDataSourceRelease,
  FormulationComponent,
  FormulationVersion,
  MatchCandidate,
  MigrationBatch,
  OrangeBookProduct,
  PaginatedResponse,
  ProcessingStatus,
  ProductDevelopmentRecord,
  RegulatoryTemplate,
  ScanStatus,
} from "@/lib/api";

export function makeVersion(
  overrides: Partial<DocumentVersion> = {},
): DocumentVersion {
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

export function makeLocator(
  overrides: Partial<DocumentLocator> = {},
): DocumentLocator {
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

export function makeTemplate(
  overrides: Partial<RegulatoryTemplate> = {},
): RegulatoryTemplate {
  return {
    public_id: "tpl-public-0001",
    canonical_code: "ANDA-SOLID-ORAL",
    title: "ANDA — Solid Oral Dosage",
    category: "Formulation",
    regulatory_pathway: "",
    dosage_form_applicability: "",
    description: "",
    lifecycle_status: "imported",
    current_approved_version: null,
    created_at: "2026-07-20T09:59:00Z",
    updated_at: "2026-07-20T09:59:00Z",
    ...overrides,
  };
}

export function makeFdaRelease(
  overrides: Partial<FdaDataSourceRelease> = {},
): FdaDataSourceRelease {
  return {
    public_id: "fda-release-public-0001",
    dataset_type: "fda_iid",
    source_name: "Synthetic FDA IID",
    official_source_reference: "synthetic://fda-iid",
    schema_version: "",
    publication_date: "2026-01-01",
    retrieved_at: "2026-01-02T00:00:00Z",
    imported_at: "2026-01-02T00:05:00Z",
    imported_by_email: "importer@example.com",
    record_count_expected: 2,
    record_count_extracted: 2,
    record_count_imported: 2,
    record_count_failed: 0,
    status: "registered",
    approved_by_email: null,
    approved_at: null,
    activated_by_email: null,
    activated_at: null,
    superseded_by_release: null,
    correlation_id: "corr-fda-0001",
    created_at: "2026-01-02T00:00:00Z",
    ...overrides,
  };
}

export function makeOrangeBookProduct(
  overrides: Partial<OrangeBookProduct> = {},
): OrangeBookProduct {
  return {
    public_id: "ob-product-public-0001",
    release: "fda-release-public-0001",
    application_number: "099999",
    application_type: "A",
    product_number: "001",
    trade_name: "Synthacet",
    active_ingredient_raw: "SYNTHETIC-ACETAMINOPHEN",
    dosage_form_raw: "TABLET",
    route_raw: "ORAL",
    dosage_form_normalized: "Tablet",
    route_normalized: "Oral",
    strength_raw: "500MG",
    strength_amount: "500",
    strength_parse_status: "parsed",
    rld_flag: true,
    reference_standard_flag: true,
    te_code: "AB",
    approval_date: null,
    approval_date_text: "Jan 1, 2000",
    discontinued: false,
    ...overrides,
  };
}

export function makeProduct(
  overrides: Partial<ProductDevelopmentRecord> = {},
): ProductDevelopmentRecord {
  return {
    public_id: "product-public-0001",
    product_code: "PROD-1",
    proposed_product_name: "Synthetic Tablet",
    active_ingredient: "Synthetic Starch",
    is_combination_product: false,
    release_type: "immediate",
    route: "",
    dosage_form: "",
    proposed_strength_amount: null,
    proposed_strength_unit: "",
    regulatory_market_context: "",
    selected_ob_application_number: "",
    selected_ob_product_number: "",
    selected_ob_product_public_id: null,
    selected_ob_release_public_id: null,
    selection_timestamp: null,
    selecting_user_email: null,
    selection_justification: "",
    status: "draft",
    created_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

export function makeFormulationVersion(
  overrides: Partial<FormulationVersion> = {},
): FormulationVersion {
  return {
    public_id: "version-public-0001",
    product: "product-public-0001",
    version_number: 1,
    status: "draft",
    total_dosage_unit_weight: "500.000000",
    total_dosage_unit_weight_unit: "milligram",
    batch_size: null,
    batch_size_unit: "",
    overage_percentage: null,
    maximum_dosage_units_per_day: "4.0000",
    dosing_basis: "",
    rationale: "",
    created_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

export function makeFormulationComponent(
  overrides: Partial<FormulationComponent> = {},
): FormulationComponent {
  return {
    public_id: "component-public-0001",
    component_type: "inactive",
    ingredient_name: "Synthetic Starch",
    resolved_ingredient_public_id: null,
    resolved_unii: "",
    function: "",
    grade: "",
    quantity_per_dosage_unit: "30.000000",
    quantity_unit: "milligram",
    percentage_w_w_snapshot: "6.000000",
    quantity_per_batch: null,
    batch_quantity_unit: "",
    overage_amount: null,
    justification: "",
    specification_reference: "",
    evidence_document_reference: null,
    display_order: 0,
    ...overrides,
  };
}

export function makeMatchCandidate(overrides: Partial<MatchCandidate> = {}): MatchCandidate {
  return {
    precedent_record_public_id: "precedent-public-0001",
    ingredient_name: "Synthetic Starch",
    route: "Oral",
    dosage_form: "Tablet",
    potency_amount: "50.000000",
    potency_unit: "milligram",
    maximum_daily_exposure: "200.000000",
    mde_unit: "milligram",
    calculability_status: "calculable",
    ...overrides,
  };
}

export function makeAssessmentPreview(
  overrides: Partial<AssessmentPreview> = {},
): AssessmentPreview {
  return {
    match_status: "EXACT_MATCH",
    candidates: [makeMatchCandidate()],
    selected_record: makeMatchCandidate(),
    calculations: {
      unit_conversion: { status: "OK", ok: true },
      percentage_w_w: { status: "OK", value: "6", unit: "percent_w_w" },
      daily_exposure: { status: "OK", value: "120" },
      percentage_of_iid_potency: { status: "OK", value: "60", unit: "percent_of_potency" },
      difference_from_iid_potency: { status: "OK", value: "20" },
      percentage_of_iid_mde: { status: "OK", value: "60", unit: "percent_of_mde" },
      difference_from_iid_mde: { status: "OK", value: "80" },
    },
    decision_status: "PASS_WITH_IID_PRECEDENT",
    decision_note:
      "Within selected FDA IID precedent. This is not an automatic safety determination or regulatory approval.",
    escalation_required: false,
    ...overrides,
  };
}

export function makeMigrationBatch(
  overrides: Partial<MigrationBatch> = {},
): MigrationBatch {
  return {
    public_id: "batch-public-0001",
    source_package: "pkg-public-0001",
    status: "completed",
    started_by_email: "doer@example.com",
    started_at: "2026-07-20T09:00:00Z",
    completed_at: "2026-07-20T09:01:00Z",
    counts: { imported: 2, excluded: 0, requires_review: 0, failed: 0 },
    correlation_id: "corr-0001",
    ...overrides,
  };
}
