# Milestone 4D-1 Implementation Specification — Checklist Definition Governance

**Status: SPECIFICATION ONLY. No code in this document. Not an authorization to implement.**

**Revision note:** this is the **revised** version, produced after a
first specification-review gate on PR #8 returned **FAIL** — 1 Critical
finding (an undisclosed lifecycle deviation from the approved Milestone
4D design) and 4 Major findings (clone semantics, code normalization,
concurrent version-number allocation, and the answer-type/classification
compatibility matrix all underspecified), plus 3 Minor findings. Every
finding is closed below (marked `SR-01` through `SR-08`), with the
lifecycle deviation specifically **kept and explicitly disclosed as an
approved, intentional refinement** rather than reverted — see §6a. Full
finding-by-finding traceability is in
[MILESTONE_4D_1_SPEC_REMEDIATION.md](MILESTONE_4D_1_SPEC_REMEDIATION.md).
This document is not rewritten from scratch — it is the same
specification, corrected and completed.

This document specifies stage 4D-1 (checklist-definition governance) of
Milestone 4D's approved implementation sequence, following the
technically-complete design in
[MILESTONE_4D_DISCOVERY.md](MILESTONE_4D_DISCOVERY.md) and its
remediation traceability in
[MILESTONE_4D_DESIGN_REMEDIATION.md](MILESTONE_4D_DESIGN_REMEDIATION.md),
both merged to `regx-main`. It translates that design into exact models,
API surface, permissions, migrations, tests, and acceptance criteria —
narrowly scoped to *authoring and governing checklist content*, not
executing it against a formulation. See §17 for the explicit
implementation-authorization boundary this document does not cross.

---

## 1. Scope

**In scope for 4D-1:** `iig_checklist` app architecture; `ChecklistDefinition`;
`ChecklistVersion`; `ChecklistSection`; `ChecklistQuestion`;
`ApplicabilityRule`; ownership/scope (platform-master vs. tenant-scoped);
version lifecycle (draft → review → approve → activate →
supersede/retire); one-active-version-per-code constraint; the
applicability-rule JSON schema (validated, not runtime-resolved); the
answer-type and data-source-classification registries; permissions;
audit events; definition-governance APIs; minimal frontend
administration screens; migrations; backend/frontend tests; Docker
smoke coverage.

**Explicitly out of scope for 4D-1** (deferred to later Milestone 4D
sub-stages per the sequence in
[MILESTONE_4D_DISCOVERY.md](MILESTONE_4D_DISCOVERY.md)'s implementation
sequence): `ChecklistExecution`, `ChecklistResponse`,
`CalculationOutcome`, draft-answer generation, overrides, deviations,
reviewer conclusion, execution approval, exports, and — per the design's
own controlled-deferral decision — any real regulatory checklist
content. Only synthetic `ChecklistDefinition` content (the paracetamol/
acetaminophen worked example from the design document) is used for
testing in this stage. No production FDA data and no production client
data are introduced.

---

## 2. App boundaries

New Django app: `iig_checklist`.

**Allowed imports:** `common` (for `PublicIDModel`/`TimeStampedModel`,
matching every existing app's convention), `audit` (for `AuditEvent` via
a thin per-app `emit()` wrapper, matching `fda_data/audit_events.py`'s
exact pattern), `authorization` (for `Role`/permission wiring), `tenancy`
(for tenant-scoped definitions' FK and middleware-provided tenant
context).

**No 4D-1 runtime dependency on `formulations`, `fda_data`,
`iid_assessment`, or `documents`.** This stage stores *identifiers* only
— `calculation_binding_identifier` on `ChecklistQuestion` is a plain
`CharField` holding a string like `"percentage_of_potency"`, not a
foreign key into `iid_assessment`; the field-registry entries an
`ApplicabilityRule` may reference (`product.route`,
`iid.has_mde`, etc.) are a **declarative, versioned list stored inside
`iig_checklist` itself** (see §6), not a live import of
`formulations`/`fda_data` model introspection. This is a deliberate
choice, not an oversight: 4D-1 governs checklist *content*, which must
be authorable and reviewable even before an execution engine exists to
resolve those identifiers against real data. Binding an identifier to an
actual `iid_assessment.calculations.calculate_percentage_of_potency`
call, or an actual `formulations.FormulationComponent` field, is a
4D-2/4D-3 concern (the execution/calculation-binding stages), where the
identifier is *validated for existence* against those apps at execution
time — not here, where it is only validated for *shape* (is it a
non-empty string drawn from the declared registry).

**Forbidden dependency directions:** `fda_data`, `formulations`,
`iid_assessment`, and `documents` must never import `iig_checklist`.

**Planned import-linter contract** (added to `backend/pyproject.toml`'s
`[tool.importlinter]` section in this stage, since the contract itself is
part of governing the new app's boundary from day one — the current six
contracts were added in the same commit as the code they govern, and
4D-1 does the same):

```toml
[[tool.importlinter.contracts]]
name = "iig-checklist-content-is-not-imported-by-governed-domains"
type = "forbidden"
source_modules = ["fda_data", "formulations", "iid_assessment", "documents"]
forbidden_modules = ["iig_checklist"]
```

`iig_checklist` is added to `root_packages` alongside the existing
eleven apps.

---

## 3. Model specification

All models use `PublicIDModel` (`public_id: UUIDField`, unique,
`db_index=True`, never exposed as the internal PK) and
`TimeStampedModel` (`created_at`/`updated_at`) from `common.models`,
exactly as every existing domain app does. Internal PKs are
`BigAutoField` (Django default), never serialized.

### 3a. `ChecklistDefinition`

```python
class ChecklistScopeType(models.TextChoices):
    PLATFORM_MASTER = "platform_master", "Platform master"
    TENANT = "tenant", "Tenant"


class ChecklistDefinition(PublicIDModel, TimeStampedModel):
    code = models.CharField(max_length=100)
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    scope_type = models.CharField(max_length=20, choices=ChecklistScopeType.choices)
    tenant = models.ForeignKey(
        "tenancy.Tenant", on_delete=models.PROTECT, null=True, blank=True,
        related_name="checklist_definitions",
    )
    created_by = models.ForeignKey(
        "identity.User", on_delete=models.PROTECT, related_name="+",
    )

    class Meta:
        constraints = [
            # platform-master rows carry tenant=NULL; tenant-scoped rows
            # carry a non-null tenant -- enforced at the DB level, not
            # just in clean(), mirroring fda_data's platform/tenant split
            # rather than trusting application code alone.
            models.CheckConstraint(
                check=(
                    models.Q(scope_type="platform_master", tenant__isnull=True)
                    | models.Q(scope_type="tenant", tenant__isnull=False)
                ),
                name="checklist_definition_scope_tenant_consistency",
            ),
            models.UniqueConstraint(
                fields=["code"],
                condition=models.Q(scope_type="platform_master"),
                name="unique_platform_master_checklist_code",
            ),
            models.UniqueConstraint(
                fields=["tenant", "code"],
                condition=models.Q(scope_type="tenant"),
                name="unique_tenant_checklist_code",
            ),
        ]
```

`code` uniqueness is scope-appropriate: one global namespace for
platform-master definitions, one namespace per tenant for tenant-scoped
definitions — a platform-master `code` and a tenant's own `code` may
coincide without conflict, matching the review's requirement that
platform-master and tenant-specific definitions are distinct governance
domains (design §16 discussion, carried into this spec).

`ChecklistDefinition` itself has **no lifecycle status field** — status
lives entirely on `ChecklistVersion` (§3b/§8). A `ChecklistDefinition`
row is a stable identity (the `code` + scope) that versions attach to; it
is never itself "approved" or "active," only its versions are. This
differs slightly from the design document's original single-model sketch
(which put `status` directly on `ChecklistDefinition`) — this
specification splits definition-identity from version-lifecycle
explicitly, matching how the review's own model list names both
`ChecklistDefinition` *and* `ChecklistVersion` as distinct concepts
(§5 of the review). This is a refinement made during specification, not a
design contradiction: the discovery document's `ChecklistDefinition`
concept maps onto this specification's `ChecklistDefinition` +
`ChecklistVersion` pair together.

### 3b. `ChecklistVersion`

```python
class ChecklistVersionStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    UNDER_REVIEW = "under_review", "Under review"
    RETURNED = "returned", "Returned"
    APPROVED = "approved", "Approved"
    ACTIVE = "active", "Active"
    REJECTED = "rejected", "Rejected"
    SUPERSEDED = "superseded", "Superseded"
    RETIRED = "retired", "Retired"


class ChecklistVersion(PublicIDModel, TimeStampedModel):
    definition = models.ForeignKey(
        ChecklistDefinition, on_delete=models.PROTECT, related_name="versions",
    )
    version_number = models.PositiveIntegerField()
    status = models.CharField(
        max_length=20, choices=ChecklistVersionStatus.choices,
        default=ChecklistVersionStatus.DRAFT, db_index=True,
    )
    effective_date = models.DateField(null=True, blank=True)
    expiry_date = models.DateField(null=True, blank=True)
    regulatory_basis = models.CharField(max_length=500, blank=True)
    change_summary = models.TextField(blank=True)

    created_by = models.ForeignKey("identity.User", on_delete=models.PROTECT, related_name="+")
    submitted_by = models.ForeignKey(
        "identity.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
    )
    submitted_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(
        "identity.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.ForeignKey(
        "identity.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    activated_by = models.ForeignKey(
        "identity.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
    )
    activated_at = models.DateTimeField(null=True, blank=True)
    returned_by = models.ForeignKey(
        "identity.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
    )
    returned_at = models.DateTimeField(null=True, blank=True)
    return_reason = models.TextField(blank=True)
    rejected_by = models.ForeignKey(
        "identity.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
    )
    rejected_at = models.DateTimeField(null=True, blank=True)
    retired_by = models.ForeignKey(
        "identity.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
    )
    retired_at = models.DateTimeField(null=True, blank=True)
    superseded_by = models.ForeignKey(
        "self", on_delete=models.SET_NULL, null=True, blank=True, related_name="supersedes",
    )
    # Audit-trail readability only -- deliberately NOT a ForeignKey, so
    # retiring/deleting the source version years later can never cascade
    # into or block operations on a clone. See §8a.
    cloned_from_version_public_id = models.UUIDField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["definition", "version_number"],
                name="unique_version_number_per_definition",
            ),
            models.UniqueConstraint(
                fields=["definition"],
                condition=models.Q(status="active"),
                name="unique_active_version_per_definition",
            ),
            models.CheckConstraint(
                check=(
                    models.Q(expiry_date__isnull=True)
                    | models.Q(effective_date__isnull=True)
                    | models.Q(expiry_date__gt=models.F("effective_date"))
                ),
                name="checklist_version_expiry_after_effective",
            ),
        ]
```

`unique_active_version_per_definition` is the identical DB-level
mechanism already proven for `unique_active_release_per_dataset_type` on
`FDADataSourceRelease` (a partial unique index gated by a status
condition, not application-level checking alone) — direct precedent, not
a new pattern.

Every provenance field (`submitted_by`, `reviewed_by`, `approved_by`,
`returned_by`, `rejected_by`, `retired_by`) is distinct and set only by
its own action, applying the HR-03 lesson (Milestone 4A–4C's reviewer-
overwrite defect) from day one rather than retrofitting it — the same
practice the discovery document itself commits to for
`ChecklistExecution`.

`clean()` enforces (mirroring the exact `AssessmentSnapshot` finding from
the design-review process — this must actually be invoked, not left
unreachable, see §8 and §16's acceptance criteria):

- `effective_date` is required before `activate` succeeds.
- Once `status` is `approved`, `active`, `superseded`, or `retired`, no
  field on this row (or any `ChecklistSection`/`ChecklistQuestion`
  belonging to it) may change except the terminal-state provenance
  fields governed by the transition service itself (§8).

### 3c. `ChecklistSection`

```python
class ChecklistSection(PublicIDModel, TimeStampedModel):
    checklist_version = models.ForeignKey(
        ChecklistVersion, on_delete=models.CASCADE, related_name="sections",
    )
    code = models.CharField(max_length=100)
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    display_order = models.PositiveIntegerField()
    applicability_rule = models.ForeignKey(
        "ApplicabilityRule", on_delete=models.PROTECT, null=True, blank=True, related_name="+",
    )
    criticality = models.CharField(max_length=20, choices=Criticality.choices)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["checklist_version", "code"],
                name="unique_section_code_per_version",
            ),
            models.UniqueConstraint(
                fields=["checklist_version", "display_order"],
                name="unique_section_display_order_per_version",
            ),
        ]
```

Immutable once the parent `ChecklistVersion.status` leaves `draft`/
`returned` — enforced the same way as §3b (`clean()` walks up to the
parent version's status).

### 3d. `ChecklistQuestion`

```python
class AnswerType(models.TextChoices):
    SHORT_TEXT = "short_text", "Short text"
    LONG_NARRATIVE = "long_narrative", "Long narrative"
    INTEGER = "integer", "Integer"
    DECIMAL = "decimal", "Decimal"
    QUANTITY_WITH_UNIT = "quantity_with_unit", "Quantity with unit"
    PERCENTAGE = "percentage", "Percentage"
    DATE = "date", "Date"
    YES_NO = "yes_no", "Yes/No"
    YES_NO_NOT_APPLICABLE = "yes_no_na", "Yes/No/Not applicable"
    SINGLE_SELECT = "single_select", "Single select"
    MULTI_SELECT = "multi_select", "Multi select"
    FDA_RECORD_REFERENCE = "fda_record_reference", "FDA record reference"
    FORMULATION_COMPONENT_REFERENCE = "formulation_component_reference", "Formulation component reference"
    EVIDENCE_ATTACHMENT_REFERENCE = "attachment_reference", "Evidence attachment reference"
    CALCULATED_VALUE = "calculated_value", "Calculated value"
    CALCULATED_STATUS = "calculated_status", "Calculated status"
    REVIEWER_CONCLUSION = "reviewer_conclusion", "Reviewer conclusion"
    APPROVAL_METADATA = "approval_metadata", "Approval metadata"


class DataSourceClassification(models.TextChoices):
    FDA_DERIVED_DEFAULT = "fda_derived_default", "FDA-derived default"
    USER_REQUIRED = "user_required", "User required"
    SYSTEM_CALCULATED = "system_calculated", "System calculated"
    REVIEWER_CONFIRMED = "reviewer_confirmed", "Reviewer confirmed"
    EVIDENCE_DERIVED = "evidence_derived", "Evidence derived"


class EvidenceRequirement(models.TextChoices):
    NONE = "none", "None"
    OPTIONAL = "optional", "Optional"
    REQUIRED = "required", "Required"
    REQUIRED_IF_OVERRIDDEN = "required_if_overridden", "Required if overridden"


class Criticality(models.TextChoices):
    INFORMATIONAL = "informational", "Informational"
    LOW = "low", "Low"
    MEDIUM = "medium", "Medium"
    HIGH = "high", "High"
    CRITICAL = "critical", "Critical"


class ChecklistQuestion(PublicIDModel, TimeStampedModel):
    section = models.ForeignKey(
        ChecklistSection, on_delete=models.CASCADE, related_name="questions",
    )
    code = models.CharField(max_length=100)
    question_text = models.TextField()
    help_text = models.TextField(blank=True)
    display_order = models.PositiveIntegerField()
    answer_type = models.CharField(max_length=40, choices=AnswerType.choices)
    data_source_classification = models.CharField(
        max_length=30, choices=DataSourceClassification.choices,
    )
    applicability_rule = models.ForeignKey(
        ApplicabilityRule, on_delete=models.PROTECT, null=True, blank=True, related_name="+",
    )
    required = models.BooleanField(default=False)
    allowed_units = models.JSONField(default=list, blank=True)
    evidence_requirement = models.CharField(
        max_length=30, choices=EvidenceRequirement.choices, default=EvidenceRequirement.NONE,
    )
    calculation_binding_identifier = models.CharField(max_length=100, blank=True)
    prefill_source = models.CharField(max_length=100, blank=True)
    reviewer_confirmation_required = models.BooleanField(default=False)
    escalation_rule_identifier = models.CharField(max_length=100, blank=True)
    criticality = models.CharField(max_length=20, choices=Criticality.choices)
    regulatory_reference = models.CharField(max_length=500, blank=True)
    validation_rule = models.JSONField(default=dict, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["section", "code"], name="unique_question_code_per_section",
            ),
            models.UniqueConstraint(
                fields=["section", "display_order"],
                name="unique_question_display_order_per_section",
            ),
        ]
```

`clean()` enforces the design's own binding rules, not left to serializer
convention alone:

- `calculation_binding_identifier` may be non-blank **only** when
  `data_source_classification == SYSTEM_CALCULATED` (validated against
  the declarative calculation-identifier allow-list, at *shape*
  level only in 4D-1 — see §2's runtime-coupling note).
- `evidence_requirement` must be `required` whenever
  `data_source_classification == EVIDENCE_DERIVED` (never `none`/
  `optional` for that classification — matches the design's rule that an
  evidence-derived answer is only as trustworthy as its cited
  attachment).
- `reviewer_confirmation_required` must be `True` whenever
  `data_source_classification == REVIEWER_CONFIRMED`.
- Immutable once the parent `ChecklistVersion.status` leaves `draft`/
  `returned`, same mechanism as §3c.

### 3d-i. Answer-type × classification compatibility matrix (closes SR-05)

The three rules above were the only cross-field constraints in the first
pass of this document — insufficient, since roughly 90 `(answer_type,
data_source_classification)` combinations were left entirely undefined
(e.g. nothing blocked `answer_type=APPROVAL_METADATA` paired with
`data_source_classification=USER_REQUIRED`, which would let a tenant user
author their own "approval" field). The full **normative** matrix below
replaces the three ad hoc rules — it is the single source of truth,
implemented as one central registry
(`iig_checklist/compatibility.py:ANSWER_TYPE_CLASSIFICATION_MATRIX`, a
plain `dict[AnswerType, set[DataSourceClassification]]` of **allowed**
classifications per answer type), consulted by both the serializer and
`ChecklistQuestion.clean()` — never scattered ad hoc `if` checks
duplicated in multiple places.

| `answer_type` | `FDA_DERIVED_DEFAULT` | `USER_REQUIRED` | `SYSTEM_CALCULATED` | `REVIEWER_CONFIRMED` | `EVIDENCE_DERIVED` |
|---|---|---|---|---|---|
| `SHORT_TEXT` | ALLOWED | ALLOWED | PROHIBITED | ALLOWED | ALLOWED |
| `LONG_NARRATIVE` | PROHIBITED | ALLOWED | PROHIBITED | ALLOWED | ALLOWED |
| `INTEGER` | ALLOWED | ALLOWED | PROHIBITED | PROHIBITED | ALLOWED |
| `DECIMAL` | ALLOWED | ALLOWED | PROHIBITED | PROHIBITED | ALLOWED |
| `QUANTITY_WITH_UNIT` | ALLOWED | ALLOWED | PROHIBITED | PROHIBITED | ALLOWED |
| `PERCENTAGE` | PROHIBITED | PROHIBITED | ALLOWED | PROHIBITED | PROHIBITED |
| `DATE` | ALLOWED | ALLOWED | PROHIBITED | PROHIBITED | ALLOWED |
| `YES_NO` | ALLOWED | ALLOWED | PROHIBITED | ALLOWED | PROHIBITED |
| `YES_NO_NOT_APPLICABLE` | ALLOWED | PROHIBITED | ALLOWED | ALLOWED | PROHIBITED |
| `SINGLE_SELECT` | ALLOWED | ALLOWED | PROHIBITED | ALLOWED | PROHIBITED |
| `MULTI_SELECT` | ALLOWED | ALLOWED | PROHIBITED | ALLOWED | PROHIBITED |
| `FDA_RECORD_REFERENCE` | ALLOWED | PROHIBITED | PROHIBITED | CONDITIONALLY_ALLOWED* | PROHIBITED |
| `FORMULATION_COMPONENT_REFERENCE` | PROHIBITED | ALLOWED | PROHIBITED | CONDITIONALLY_ALLOWED* | PROHIBITED |
| `EVIDENCE_ATTACHMENT_REFERENCE` | PROHIBITED | CONDITIONALLY_ALLOWED** | PROHIBITED | PROHIBITED | ALLOWED |
| `CALCULATED_VALUE` | PROHIBITED | PROHIBITED | ALLOWED | PROHIBITED | PROHIBITED |
| `CALCULATED_STATUS` | PROHIBITED | PROHIBITED | ALLOWED | PROHIBITED | PROHIBITED |
| `REVIEWER_CONCLUSION` | PROHIBITED | PROHIBITED | PROHIBITED | ALLOWED | PROHIBITED |
| `APPROVAL_METADATA` | PROHIBITED | PROHIBITED | PROHIBITED | ALLOWED | PROHIBITED |

`*` **`FDA_RECORD_REFERENCE`/`FORMULATION_COMPONENT_REFERENCE` as
`REVIEWER_CONFIRMED`** is allowed only for the specific "reviewer
confirms a system-proposed selection" shape (e.g. confirming which of
several candidate IID precedent records applies) — `reviewer_confirmed`
here is a *confirmation of a reference*, not authorship of arbitrary
narrative, and `reviewer_confirmation_required=True` is still mandatory
per the existing rule.

`**` **`EVIDENCE_ATTACHMENT_REFERENCE` as `USER_REQUIRED`** is allowed
only when the question represents the user voluntarily supplying
supporting evidence for their own answer, not a mandatory evidence-backed
fact (that case is `EVIDENCE_DERIVED`, which forces
`evidence_requirement=required`, §3d) — for `USER_REQUIRED`,
`evidence_requirement` may be `optional`, never `required` (that
combination is itself PROHIBITED and separately checked).

**Non-negotiable floors, explicitly enforced regardless of what the
matrix table alone might permit at a glance:**
- `APPROVAL_METADATA` is **never** `USER_REQUIRED`, `FDA_DERIVED_DEFAULT`,
  `SYSTEM_CALCULATED`, or `EVIDENCE_DERIVED` — only `REVIEWER_CONFIRMED`
  (approval-adjacent metadata must always be a reviewer/approver action,
  never something a tenant user, an FDA-data sync, or a formula can
  author).
- `REVIEWER_CONCLUSION` is **only** `REVIEWER_CONFIRMED` — never
  system-generated, never user-authored as an ordinary answer.
- `CALCULATED_VALUE`/`CALCULATED_STATUS` are **only**
  `SYSTEM_CALCULATED` — never manually authored under any classification,
  matching the design's existing "a calculation is never directly
  hand-edited" rule (discovery §12).
- `FDA_DERIVED_DEFAULT` questions must always resolve through a
  controlled source binding (an actual FDA-governed lookup, per §4 of
  the discovery document) — `FDA_DERIVED_DEFAULT` is therefore never
  paired with `LONG_NARRATIVE`/`REVIEWER_CONCLUSION`/`APPROVAL_METADATA`/
  `CALCULATED_VALUE`/`CALCULATED_STATUS`/`PERCENTAGE` (all of which would
  let free narrative or an unbound value masquerade as an FDA fact
  without real source provenance).
- `USER_REQUIRED` is never `APPROVAL_METADATA`, `CALCULATED_VALUE`, or
  `CALCULATED_STATUS` (already covered above, restated for emphasis since
  this was the specific gap flagged by the review).

Any `(answer_type, data_source_classification)` pair not explicitly
`ALLOWED`/`CONDITIONALLY_ALLOWED` in the matrix above is `PROHIBITED` —
the matrix is exhaustive and closed, not "everything not forbidden is
permitted."

### 3e. `ApplicabilityRule`

```python
class ApplicabilityOutcome(models.TextChoices):
    APPLICABLE = "applicable", "Applicable"
    NOT_APPLICABLE = "not_applicable", "Not applicable"
    REVIEW_REQUIRED = "review_required", "Review required"


class ApplicabilityRuleStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    APPROVED = "approved", "Approved"


class ApplicabilityRule(PublicIDModel, TimeStampedModel):
    code = models.CharField(max_length=100)
    version = models.PositiveIntegerField(default=1)
    condition_json = models.JSONField()
    outcome_if_true = models.CharField(max_length=20, choices=ApplicabilityOutcome.choices)
    outcome_if_false = models.CharField(max_length=20, choices=ApplicabilityOutcome.choices)
    reason_code = models.CharField(max_length=100)
    explanation_template = models.CharField(max_length=500)
    allowed_field_registry_version = models.PositiveIntegerField()
    status = models.CharField(
        max_length=20, choices=ApplicabilityRuleStatus.choices,
        default=ApplicabilityRuleStatus.DRAFT,
    )
    created_by = models.ForeignKey("identity.User", on_delete=models.PROTECT, related_name="+")
    approved_by = models.ForeignKey(
        "identity.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
    )
    approved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["code", "version"], name="unique_applicability_rule_code_version",
            ),
        ]
```

**Decision: version-scoped, immutable, cloneable — not globally mutable
shared rules.** An `ApplicabilityRule` is created inside the context of
authoring a specific `ChecklistVersion` and becomes immutable the moment
that `ChecklistVersion` leaves `draft`/`returned` (same mechanism as
§3c/§3d) — it is never edited in place after that point, even if another,
unrelated `ChecklistVersion` would like the identical condition. Reuse
across versions is achieved by **controlled cloning** (copying
`condition_json`/`outcome`/`reason_code` into a new `ApplicabilityRule`
row bound to the new version, incrementing `version`), never by two
`ChecklistQuestion` rows in different `ChecklistVersion`s pointing at the
literal same `ApplicabilityRule` row. This mirrors the design document's
own reasoning for evidence attachments and `ChecklistDefinition` versions
alike: a governed artifact that could be shared *and* mutated
independently of the content that depends on it would let a rule change
silently alter the meaning of an already-approved checklist — exactly
the risk this codebase has consistently closed elsewhere. The minor
storage cost of duplicate rows across versions is accepted deliberately
in exchange for this guarantee.

`condition_json` is validated against the schema in §5 at both
`clean()`-time and at `approve`/`activate` time (defense in depth, not a
single check point) — never accepted as opaque JSON.

### 3f. Code normalization (closes SR-03)

**One authoritative normalization function**,
`iig_checklist.codes.normalize_code(raw: str) -> str`, applied to every
`code` field in this app — `ChecklistDefinition.code`,
`ChecklistSection.code`, `ChecklistQuestion.code`, and
`ApplicabilityRule.code` — before it is stored or checked for uniqueness.
This was previously unspecified, leaving collision behavior to incidental
database collation; it is fully specified here instead.

**Grammar (the normalized, *stored* form):**
```
^[A-Z0-9][A-Z0-9_-]*$
```

**Normalization algorithm, applied in this exact order:**
1. Strip leading/trailing whitespace.
2. Collapse any run of internal whitespace to a single `_`.
3. Uppercase the entire string (`str.upper()` — plain ASCII case
   folding; **no locale-dependent case transformation** of any kind, so
   behavior is identical regardless of server locale).
4. Reject the value (raise a validation error, `CODE_BLANK`) if, after
   steps 1–3, the result is empty.
5. Reject the value (`CODE_INVALID_CHARACTERS`) if the result does not
   match the grammar above — i.e. only `A`–`Z`, `0`–`9`, `_`, and `-` are
   permitted, and the first character must be alphanumeric (never a
   leading `_`/`-`). No other separator character is silently rewritten
   into `_`/`-`; an unrecognized character is a hard rejection, not a
   best-effort substitution.
6. Reject the value (`CODE_TOO_LONG`) if the result exceeds the maximum
   length for that field: **100 characters** for
   `ChecklistDefinition.code`/`ChecklistSection.code`/
   `ChecklistQuestion.code`, **100 characters** for
   `ApplicabilityRule.code` (matching the `max_length=100` already
   specified on each field in §3a/§3c/§3d/§3e).

**Worked examples** (all four inputs below normalize to the identical
stored value `IIG_ORAL`, and therefore **do** collide — this is the one
explicit rule requested, chosen over silent case-sensitive collation,
because two humans typing the "same" code in different case/spacing
should not be able to accidentally create two distinct, confusable
`code`s):
- `"iig oral"` → `"IIG_ORAL"`
- `"IIG_ORAL"` → `"IIG_ORAL"` (already normalized, unchanged)
- `" iig_oral "` → `"IIG_ORAL"`
- `"iig_oral"` → `"IIG_ORAL"`

**Where normalization is applied (defense in depth, not a single check
point):**
- **Serializer layer:** every create/update serializer for the four
  models calls `normalize_code()` on the incoming `code` field before
  passing it to the model layer, so a `400` with a specific error code
  (`CODE_BLANK`/`CODE_INVALID_CHARACTERS`/`CODE_TOO_LONG`) is returned
  before any database round-trip.
- **Model/service layer:** `clean()` on each of the four models
  re-normalizes and re-validates independently (never trusts that the
  serializer was the only caller — matching this codebase's consistent
  "service layer re-validates, never trusts the API layer alone"
  practice already established for e.g. `fda_data`'s transition
  validation happening inside the view/service, not only in the
  serializer).
- **Database layer:** the `UniqueConstraint`s specified in §3a/§3c/§3d/
  §3e are declared against the `code` **column as stored** — since the
  column only ever holds already-normalized values (steps above), the
  plain-`code`-column unique constraint is sufficient; **no reliance on
  PostgreSQL collation settings** (e.g. `citext` or a case-insensitive
  index) is used or needed, because normalization happens before storage,
  not at query time.
- **Display title is a separate field** (`title`/`question_text`, not
  `code`) and is never normalized or subject to a uniqueness
  constraint — a human-readable title may contain any casing/punctuation
  the author chooses; only the machine-facing `code` identifier is
  constrained.

**Deterministic conflict response:** a normalized-`code` collision at
create/update time returns a structured **409** (`DUPLICATE_CODE`), never
a raw `IntegrityError`/500 — the same `select`-before-`insert` pattern
used for version-number allocation (§6b) applies here: the serializer
performs an explicit existence check for the normalized code within the
appropriate scope before attempting the insert, and the `UniqueConstraint`
remains the backstop against a race between that check and the insert
(caught and converted to the same structured 409, never surfaced as a
raw database exception).

---

## 4. Enum and registry specification

The five enums above (`DataSourceClassification`, `AnswerType`,
`Criticality`, `EvidenceRequirement`, `ApplicabilityOutcome`) are the
complete, exact set — no additions or omissions from
[MILESTONE_4D_DISCOVERY.md](MILESTONE_4D_DISCOVERY.md)'s §3/§6a/§9a.

### 4a. Controlled field registry (for `ApplicabilityRule.condition_json`)

A plain Python module, `iig_checklist/field_registry.py`, not a database
table — this is a **declarative, versioned constant**, matching the
design's "allow-listed field set, never client-supplied" principle
(discovery doc §9a) at the lightest-weight level that still gives 4D-1 a
real, enforceable allow-list without any runtime coupling to
`formulations`/`fda_data` (§2):

```python
FIELD_REGISTRY_VERSION = 1

ALLOWED_FIELDS = {
    "product.route",
    "product.dosage_form",
    "product.release_type",
    "iid.match_status",
    "iid.has_mde",
    "iid.has_potency",
}
```

4D-1 validates that every `field` referenced in a `condition_json` tree
exists in `ALLOWED_FIELDS` for the `allowed_field_registry_version` the
rule declares — **schema validation only**. Whether the field actually
resolves to a real value at execution time (e.g. does `iid.has_mde`
correctly reflect a real `IIDPrecedentRecord`'s MDE presence) is a 4D-2/
4D-3 concern, when an actual execution context exists to resolve against.
This registry is expected to grow in later stages; 4D-1 ships only the
fields the paracetamol worked example needs, not a speculative complete
set.

### 4b. Field-registry version-bump behavior (closes SR-08)

Previously unspecified: what happens to existing `ApplicabilityRule` rows
when `FIELD_REGISTRY_VERSION` is bumped (e.g. a later stage adds new
`ALLOWED_FIELDS` entries and increments the constant to `2`). Specified
here in full:

- `FIELD_REGISTRY_VERSION` (and, by extension, the specific
  `allowed_field_registry_version` an `ApplicabilityRule` declares) is
  **immutable once that rule is referenced by an `approved` or `active`
  `ChecklistVersion`** — the same immutability boundary already applied
  to every other field on an approved rule (§3e).
- **A registry change is additive, versioned, and non-destructive:**
  bumping `FIELD_REGISTRY_VERSION` to `2` creates a new registry version
  (e.g. `ALLOWED_FIELDS_V2`, a superset or revision of `ALLOWED_FIELDS`)
  in code; it never mutates the meaning of version `1` retroactively.
- **Existing rules keep the registry version they were created
  against.** A rule created with `allowed_field_registry_version=1`
  remains validated against `ALLOWED_FIELDS` (v1) forever — it is never
  automatically re-validated or silently reinterpreted against a newer
  registry.
- **New or edited (still-`draft`/`returned`) rules must target the
  current, latest `FIELD_REGISTRY_VERSION`** — a rule cannot be newly
  authored declaring an old registry version once a newer one exists
  (the serializer rejects `allowed_field_registry_version` values other
  than the current constant for any rule not yet `approved`).
- **Historical validation remains possible against an old registry
  version** — the field-registry module retains every past
  `ALLOWED_FIELDS_V{n}` set (never deletes an old version's field list),
  so a historical, already-approved rule can always be re-displayed/
  re-validated against the exact registry it was authored under, for
  reproducibility (discovery §18).
- **A registry version may eventually be marked unsupported for new
  activation** (e.g. after several stages have superseded it) — an
  unsupported version's rules remain viewable, and any `ChecklistVersion`
  that already reached `active` while referencing them is unaffected,
  but a *new* `activate` attempt on a `ChecklistVersion` whose
  applicability rules declare an unsupported registry version is
  blocked with a structured 400 (`UNSUPPORTED_FIELD_REGISTRY_VERSION`) —
  activation is the one point where registry-version support is
  actively checked, not merely at rule-creation time.
- **No automatic migration of stored `condition_json` ever occurs** — a
  registry bump never rewrites, reinterprets, or mutates any existing
  rule's stored condition tree. A registry change is treated as an
  **advisory prompt for a human to review** whether existing checklist
  content should be revised in a *new* `ChecklistVersion` (never a
  trigger for the system to silently reinterpret old content) —
  consistent with this specification's broader "no automatic
  reassessment of approved governed content" principle (discovery §16).

---

## 5. Applicability-rule JSON schema

```json
{
  "operator": "all",
  "conditions": [
    {"field": "product.route", "operator": "eq", "value": "ORAL"},
    {"field": "iid.has_mde", "operator": "exists"}
  ]
}
```

**Grammar:**
- Top-level node is either a **composite** (`{"operator": "all"|"any",
  "conditions": [...]}`) or a **leaf** (`{"field": ..., "operator": ...,
  "value"?: ...}`).
- Leaf operators: `eq`, `neq`, `in`, `not_in`, `exists`, `not_exists`,
  `gt`, `gte`, `lt`, `lte`. `exists`/`not_exists` take no `value`; all
  others require one. `in`/`not_in` require `value` to be a JSON array;
  `gt`/`gte`/`lt`/`lte` require `value` to be a JSON number.
- Composite operators: `all` (AND), `any` (OR). `conditions` must be a
  non-empty JSON array of further nodes (leaf or composite).
- **No other keys are permitted at any node** — an unrecognized key is a
  validation error, not silently ignored (fails closed).

**Bounds (all enforced at validation time, rejecting the payload with a
structured 400/`ValidationError`, never silently truncating):**
- Maximum recursion depth: **5**.
- Maximum total condition-leaf count across the whole tree: **50**.
- Maximum `condition_json` serialized size: **8 KB**.
- `field` must be a member of `ALLOWED_FIELDS` (§4a) — no arbitrary key,
  no dotted-path traversal beyond the registry's literal string keys.
- `value`, when present, is type-checked against a fixed per-field type
  (string/number/boolean/array only — the field registry declares each
  field's expected type; a type mismatch is a validation error, not a
  coercion attempt).

**No `eval`, no `exec`, no stored Python, no arbitrary executable
expression of any kind** — the evaluator (implemented in a later stage
that actually executes rules; 4D-1 only validates and stores) is a fixed
dispatch table keyed by `operator` string, exactly as
[MILESTONE_4D_DISCOVERY.md](MILESTONE_4D_DISCOVERY.md) §9a specifies.

**Canonical serialization for checksums:** `condition_json` is
canonicalized before hashing (sorted object keys, no insignificant
whitespace, UTF-8) using the same `json.dumps(obj, sort_keys=True,
separators=(",", ":"))` approach already implicit in this codebase's
JSON-serialization conventions — this canonical form is what a future
export checksum (per the discovery document's export design, §17 there)
would hash, not the raw stored bytes, so semantically-identical rules
serialized differently never produce different checksums.

**Deterministic error codes** (returned in the structured 400 body, one
per distinct failure mode — never a single generic "invalid rule"
message): `MALFORMED_JSON`, `UNKNOWN_KEY`, `UNKNOWN_OPERATOR`,
`UNKNOWN_FIELD`, `TYPE_MISMATCH`, `MISSING_VALUE`,
`RECURSION_DEPTH_EXCEEDED`, `CONDITION_COUNT_EXCEEDED`,
`PAYLOAD_SIZE_EXCEEDED`, `EMPTY_CONDITIONS`.

---

## 6. Lifecycle specification

`ChecklistVersion` transition table (single authoritative table in
`iig_checklist/version_transitions.py`, structurally identical to
`fda_data/mapping_transitions.py` — the exact reuse the design document
commits to in §1a/§14):

| Action | Legal from | Resulting status |
|---|---|---|
| `submit_review` | `draft`, `returned` | `under_review` |
| `approve` | `under_review` | `approved` |
| `return` | `under_review` | `returned` |
| `reject` | `draft`, `under_review` | `rejected` |
| `activate` | `approved` | `active` |
| `supersede` | `active` | `superseded` |
| `retire` | `draft`, `approved`, `active`, `returned` | `retired` |

`REJECTED`, `SUPERSEDED`, `RETIRED` are terminal — no outgoing table
entry, matching the design's precedent (an action attempted against a
mapping/release/version in a terminal status raises a structured 400,
never succeeds).

### 6a. Approved lifecycle refinement from the Milestone 4D design (closes SR-01)

**This table is a disclosed, approved refinement of
[MILESTONE_4D_DISCOVERY.md](MILESTONE_4D_DISCOVERY.md) §1a, not an
accidental deviation.** The approved design's own §1a table for
`ChecklistDefinition` governance had 6 actions and no `RETURNED` status
(`submit_review`/`approve`/`reject → retired`/`activate`/`supersede`/
`retire`), deliberately mirroring `FDADataSourceRelease`'s leaner release-
governance pattern. A first specification-review pass on this document
correctly flagged that the table above — which adds a `return` action, a
distinct `RETURNED` status, and a distinct terminal `REJECTED` status
(rather than folding rejection into `retired`) — diverges from that
approved table without saying so. That divergence is intentional and is
now explicitly disclosed here, with the following rationale, matching
exactly how §3a already discloses the `ChecklistDefinition`/
`ChecklistVersion` split as a deliberate refinement rather than a silent
change:

- **`RETURNED` supports controlled correction and resubmission.**
  Checklist-content authoring is inherently iterative — a reviewer
  finding a fixable gap in a draft's sections/questions should be able to
  send it back for correction without terminating the version outright.
  This is the same reasoning `SubstanceSynonymMapping` already applies
  (its richer `SubstanceMappingStatus` adds `under_review`/`returned`
  specifically because ingredient-identity content review benefits from
  a correction cycle) and the same reasoning `ChecklistExecution` itself
  applies in the approved design (its own transition table, discovery
  §8, includes `return`). Applying the same pattern to
  `ChecklistVersion` content-governance is consistent with, not
  contrary to, the design's own precedent elsewhere — the design
  document's §1a simply modeled `ChecklistDefinition` on
  `FDADataSourceRelease` instead of on the richer mapping/execution
  pattern, and this specification corrects that choice for definition
  governance specifically, since checklist authoring is much closer in
  kind to iterative mapping/content review than to a one-shot data
  import.
- **`REJECTED` remains a distinct, genuinely terminal state** — separate
  from `RETIRED`, which represents a version being withdrawn from future
  use *after* having been in good standing (e.g. a `draft`, `approved`,
  or previously-`active` version taken out of service), whereas
  `REJECTED` represents a reviewer/approver's explicit determination that
  this specific version's content should never proceed at all. Collapsing
  both into `retired` (as the original design's leaner table did) loses
  this distinction; keeping them separate matches how `fda_data` mapping
  governance and `ChecklistExecution` both already keep `rejected` and
  any withdrawal/supersession state distinct.
- **Review provenance remains fully preserved** across a return/resubmit
  cycle (§6's `RETURNED` behavior note below) — this refinement does not
  weaken auditability, it strengthens it, since a resubmission cycle is
  now representable at all (the original 6-action table had no way to
  send a definition back for correction short of rejecting it outright
  and starting over).
- **Rejected versions cannot be resurrected** — `REJECTED` has no
  outgoing transition, identical in spirit to `SubstanceSynonymMapping`'s
  `REJECTED` being terminal. Correcting rejected content always means
  authoring a **new** `ChecklistVersion` (a new `version_number` under
  the same `ChecklistDefinition`, per §3b), never resubmitting or
  reopening the rejected row.
- **Returned versions may be edited and resubmitted** — per §6's
  `RETURNED` behavior note, content is mutable while `returned`, exactly
  as it is while `draft`.
- **This aligns definition governance with existing mapping and
  execution lifecycle patterns** rather than with the narrower release
  pattern the original design borrowed from — a considered choice, made
  explicit here rather than left as an unstated inconsistency.

This refinement is recorded in the traceability table (§16, row SR-01)
and in
[MILESTONE_4D_1_SPEC_REMEDIATION.md](MILESTONE_4D_1_SPEC_REMEDIATION.md)
as an approved specification correction, not merely noted in passing.

**Enforcement, identical shape to `fda_data/mapping_transitions.py` +
`_MappingActionViewBase`:**
- One shared `_ChecklistVersionActionViewBase`, no per-action bespoke
  view logic and no alternate endpoint that can mutate `status`.
- Every action: `transaction.atomic()` + `select_for_update()` on the
  `ChecklistVersion` row, re-fetch, call
  `validate_version_transition(current_status, action)` **before** any
  mutation. On `IllegalVersionTransition`, return a structured 400 with
  the row left untouched and **no audit event emitted**.
- `activate` additionally requires `effective_date` to be set (checked
  inside the same transition validation, not a separate pass) and
  performs the one-active-version supersession atomically: if another
  version of the same `definition` is currently `active`, that version
  is transitioned to `superseded` in the **same** transaction as the
  new version's `activate` — never a window where two versions of one
  definition are simultaneously active, and never a separate,
  un-atomic follow-up call.
- No generic `PATCH` on `ChecklistVersion.status` — the serializer used
  by the plain content-editing endpoints (§3b/§3c/§3d field updates while
  `draft`/`returned`) has no `status` field at all; status changes only
  through the dedicated action endpoints.
- Self-approval blocked: the actor who performed `submit_review` cannot
  perform `approve` on the same version — same check already proven in
  `_MappingActionViewBase`, reused verbatim, not reinvented.
- Doer-equivalent actors (holding only `iig_checklist.create_definition`/
  `edit_draft`/`submit_review`) cannot `approve`, `activate`, `reject`,
  or `retire` — enforced by `required_permission` on each action view,
  identical to how `TerminologyMappingApproveView` requires
  `fda_data.approve` while `TerminologyMappingSubmitReviewView` requires
  only `fda_data.review`.

**`RETURNED` behavior, specified exactly (was ambiguous in the discovery
document, resolved here as an implementation detail, not a design
change):** while `returned`, `ChecklistSection`/`ChecklistQuestion`
content **is** editable (same mutability window as `draft`). A
subsequent `submit_review` sets a **new** `submitted_at`/`submitted_by`
(overwriting only these two fields — the prior `returned_by`/
`returned_at`/`return_reason` are retained unchanged as historical
record, never cleared), so the audit trail shows the full
draft→submit→return→edit→resubmit cycle rather than losing the fact a
return ever happened.

**Concurrency (activation):** the `unique_active_version_per_definition`
constraint (§3b) is the backstop; `select_for_update()` on both the
version being activated *and* the row query for "any other active
version of this definition" inside the same transaction is the primary
mechanism, mirroring the concurrent-approval test pattern already proven
in `backend/fda_data/tests/test_mapping_lifecycle_transitions.py`'s
`TestConcurrentApproval` (real `threading.Thread` + separate `APIClient`
connections, `pytest.mark.django_db(transaction=True)`).

### 6b. Concurrent version-number allocation (closes SR-04)

**This was unspecified in the first pass of this document and is a real
class of defect this same codebase has already hit once** —
`templates_registry`'s `_get_or_create_draft_version()` originally raced
on `version_number` allocation under concurrent import, fixed in
Milestone 3's own remediation (see
`backend/templates_registry/importer.py`, and the regression test
`TestConcurrentVersionAllocation` in
`backend/templates_registry/tests/test_review_remediation.py`). The
`POST /iig-checklists/definitions/{public_id}/versions/` endpoint
(§8) must apply the identical fix from day one, not rediscover the bug:

**Authoritative version-creation service, exact algorithm:**
1. Open `transaction.atomic()`.
2. `ChecklistDefinition.objects.select_for_update().get(public_id=…)` —
   lock the **parent** definition row for the duration of the
   transaction (the same row-to-lock choice `templates_registry`'s fix
   uses: locking the parent, not the not-yet-existent child, is what
   actually serializes concurrent allocation attempts).
3. `ChecklistVersion.objects.filter(definition=definition
   ).aggregate(Max("version_number"))` inside the same transaction (only
   possible to run consistently because step 2 already holds the lock).
4. `next_number = (max_version_number or 0) + 1`.
5. Create the new `ChecklistVersion` with `version_number=next_number`,
   `status=draft`.
6. Commit — releasing the lock only once the new row exists, so a second
   concurrent request blocks at step 2 until the first fully completes,
   then computes its own `next_number` against the now-updated maximum.

**Required API/model behavior:**
- `version_number` is **never client-supplied** — the create-version
  serializer does not expose `version_number` as a writable input field
  at all (read-only in the response only); the service above is the sole
  place it is computed.
- The `unique_version_number_per_definition` constraint (§3b) remains
  the database-level backstop, but because step 2's lock genuinely
  serializes allocation, the constraint should never actually fire in
  correct operation — it exists as defense in depth, not as the primary
  mechanism, and never surfaces as a raw `IntegrityError`/500 to a
  client: if the constraint is ever violated despite the lock (e.g. a
  future code path that bypasses this service), the view catches the
  resulting `IntegrityError` and returns a structured **409**
  (`VERSION_ALLOCATION_CONFLICT`) — no code path returns a raw database
  exception.
- Two genuinely concurrent `POST .../versions/` requests against the
  same definition must produce two distinct, sequential `version_number`
  values (`1` and `2`, never both `1`) — never a silent overwrite of one
  request's row by the other.
- Audit event `iig_checklist.version.created` is emitted only after the
  transaction in steps 1–6 commits successfully — never for a request
  that lost the race and had to retry or was rejected.

### 6c. Why `ChecklistVersion` has no distinct `REVIEW_COMPLETE` state (closes SR-07)

An explicit decision, not an omission left unexplained. The discovery
document (§8a) discusses and rejects a distinct `REVIEW_COMPLETE` state
for `ChecklistExecution` on the grounds that it describes *readiness*
rather than a governance-relevant transition. The same question, asked
here for `ChecklistVersion` content-governance specifically:

- Definition governance's `UNDER_REVIEW → APPROVED` is a single reviewer/
  approver decision point: a `ChecklistVersion` is either judged ready to
  approve, or it is `return`ed/`reject`ed. There is no intermediate
  "review work is finished, but a separate approval act is still
  pending" state that this governance actually needs to represent as its
  own status — the reviewer and approver are already distinct actors via
  permissions (`PERM_REVIEW` vs. `PERM_APPROVE`) and distinct provenance
  fields (`reviewed_by`/`reviewed_at` vs. `approved_by`/`approved_at`,
  §3b), so "who reviewed" and "who approved" are already separately
  recorded without needing a state-machine node between them.
- `ChecklistExecution`'s eventual lifecycle (a later 4D stage) may have a
  materially different completeness picture — an execution's "review" can
  involve per-question confirmations, overrides, and evidence, with
  genuinely more granular sub-states of completeness than a content
  version's binary "approve or don't." That richer surface is why the
  discovery document's own reasoning for executions doesn't
  automatically transfer to definitions — the two lifecycles are allowed
  to differ in state-machine richness because they govern materially
  different kinds of content.
- Adding a `REVIEW_COMPLETE` state to `ChecklistVersion` here would
  introduce state-machine complexity (a new status, new legal-transition
  rows, new permission checks on the new transition) without a
  corresponding controlled business event it would represent — exactly
  the "complexity without governance benefit" standard this document
  already applies when explicitly rejecting `DATA_ENTRY_COMPLETE`/
  `CALCULATED` as formal states in favor of computed readiness flags
  (a pattern this specification would otherwise be inconsistent with if
  it added `REVIEW_COMPLETE` here without the same justification bar).

---

## 7. Permission model

New codenames in `iig_checklist/permissions.py`, following the exact
`fda_data/permissions.py` shape (`PERM_*` constants,
`has_iig_checklist_permission(user, tenant, codename)`,
`ROLE_PERMISSIONS` dict, one `BasePermission` subclass per codename via a
shared `_IigChecklistPermissionBase`):

```python
PERM_VIEW_DEFINITION = "iig_checklist.view_definition"
PERM_CREATE_DEFINITION = "iig_checklist.create_definition"
PERM_EDIT_DRAFT = "iig_checklist.edit_draft"
PERM_SUBMIT_REVIEW = "iig_checklist.submit_review"
PERM_REVIEW = "iig_checklist.review"
PERM_APPROVE = "iig_checklist.approve"
PERM_ACTIVATE = "iig_checklist.activate"
PERM_RETIRE = "iig_checklist.retire"
PERM_CLONE = "iig_checklist.clone"
PERM_VIEW_AUDIT = "iig_checklist.view_audit"
PERM_DELETE_DRAFT = "iig_checklist.delete_draft"  # narrow, §8b -- distinct from edit_draft

ROLE_PERMISSIONS = {
    Role.BuiltIn.DOER: [
        PERM_VIEW_DEFINITION, PERM_CREATE_DEFINITION, PERM_EDIT_DRAFT,
        PERM_SUBMIT_REVIEW, PERM_CLONE, PERM_DELETE_DRAFT,
    ],
    Role.BuiltIn.REVIEWER: [
        PERM_VIEW_DEFINITION, PERM_REVIEW, PERM_VIEW_AUDIT,
    ],
    Role.BuiltIn.VP: [
        PERM_VIEW_DEFINITION, PERM_REVIEW, PERM_APPROVE, PERM_ACTIVATE,
        PERM_RETIRE, PERM_VIEW_AUDIT,
    ],
    Role.BuiltIn.TENANT_ADMIN: [PERM_VIEW_DEFINITION],  # role assignment only, no content approval
    Role.BuiltIn.PLATFORM_SUPPORT: [],  # platform-master metadata only, see below
}
```

- `submit_review`/`return`/`reject` require `PERM_REVIEW` — a Reviewer,
  not a Doer, exactly mirroring `fda_data`'s `submit-review`/`reject`/
  `return` all requiring `fda_data.review`, never `fda_data.import` alone
  (the same floor already established for override-capable actions
  platform-wide).
- `approve`/`activate`/`retire` require `PERM_APPROVE`/`PERM_ACTIVATE`/
  `PERM_RETIRE` respectively (VP-level).
- **Platform-master definitions:** creating/editing one requires the same
  permissions as a tenant-scoped one, but scoped by `tenant is None` in
  the queryset — a user needs a *platform-level* grant (not tied to any
  single tenant's `TenantMembership`) to create a platform-master
  definition. This specification does not invent a new platform-role
  concept; it reuses whatever mechanism `fda_data`'s existing
  platform-level permission checks already use (`has_fda_data_permission`
  checks membership-derived roles without requiring a tenant filter when
  the resource itself is platform-level) — `iig_checklist`'s
  `has_iig_checklist_permission` follows the identical pattern.
- A user cannot `approve` a `ChecklistVersion` they `submitted_review`d
  themselves, regardless of role (self-approval check, §6) — this is
  enforced independently of the coarse role-permission check, exactly as
  `_MappingActionViewBase`'s existing `self_approval_forbidden` flag
  does.

---

## 8. API specification

Base path: `/api/regx/v1/iig-checklists/`, matching the existing
hyphenated path-segment convention (`fda-data/`, `migration-batches/`).

**Definitions:**
```
GET    /iig-checklists/definitions/
POST   /iig-checklists/definitions/
GET    /iig-checklists/definitions/{public_id}/
POST   /iig-checklists/definitions/{public_id}/clone/
```

**Versions:**
```
POST   /iig-checklists/definitions/{public_id}/versions/
GET    /iig-checklists/versions/{public_id}/
PATCH  /iig-checklists/versions/{public_id}/
POST   /iig-checklists/versions/{public_id}/submit-review/
POST   /iig-checklists/versions/{public_id}/approve/
POST   /iig-checklists/versions/{public_id}/return/
POST   /iig-checklists/versions/{public_id}/reject/
POST   /iig-checklists/versions/{public_id}/activate/
POST   /iig-checklists/versions/{public_id}/supersede/
POST   /iig-checklists/versions/{public_id}/retire/
```

**Sections/questions** (nested under a version, create/update/delete only
while `status` is `draft`/`returned` — enforced server-side via the same
`clean()` mechanism as §3c/§3d, not merely hidden in the frontend):
```
GET    /iig-checklists/versions/{public_id}/sections/
POST   /iig-checklists/versions/{public_id}/sections/
PATCH  /iig-checklists/sections/{public_id}/
DELETE /iig-checklists/sections/{public_id}/
POST   /iig-checklists/sections/{public_id}/questions/
PATCH  /iig-checklists/questions/{public_id}/
DELETE /iig-checklists/questions/{public_id}/
```

**Common rules across every endpoint above** (matching every existing
API in this codebase): UUID `public_id` only in every URL and response
body — no internal numeric `id`/`pk` ever serialized; a nonexistent or
inaccessible (wrong tenant, wrong scope) resource returns a generic 404,
never a distinguishing 403-vs-404 that would leak existence; list
endpoints are paginated with bounded `page_size` and only the filters
`?scope_type=`, `?status=`, `?code=` (substring, case-insensitive); every
write endpoint validates via a `ModelSerializer` subclass that has **no
`status` field on the plain PATCH serializer** (mass-assignment
protection — status only changes through the action endpoints in §6);
request/response bodies use the field names given in §3 verbatim.

**Example response shape** (`GET .../versions/{public_id}/`):
```json
{
  "public_id": "…",
  "definition_public_id": "…",
  "version_number": 1,
  "status": "draft",
  "effective_date": null,
  "regulatory_basis": "",
  "sections": [
    {
      "public_id": "…",
      "code": "identity-and-precedent",
      "title": "Excipient Identity and IID Precedent",
      "display_order": 1,
      "questions": ["…"]
    }
  ]
}
```

### 8a. Clone semantics (closes SR-02)

`POST /iig-checklists/definitions/{public_id}/clone/` — exact request and
response contract, previously underspecified.

**Request body:**
```json
{
  "source_version_public_id": "…",
  "target_scope_type": "tenant",
  "target_tenant_public_id": "…",
  "new_code": "iig-oral-solid-v2-tenant-draft",
  "new_title": "IIG Oral Solid (tenant working copy)",
  "clone_sections": true,
  "clone_questions": true,
  "clone_applicability_rules": true,
  "reason": "Starting point for a tenant-specific oral-solid checklist"
}
```

- `source_version_public_id` (required): the specific `ChecklistVersion`
  to clone from. **Must be `approved`, `active`, or `superseded`** — a
  `draft`/`under_review`/`returned` version is never clonable (cloning an
  unreviewed draft would let unreviewed content silently become the seed
  of a new definition without ever itself having been reviewed).
  `rejected`/`retired` versions are likewise not valid clone sources —
  their content was specifically found unsuitable or withdrawn, and
  reusing it as a starting point without that context is a governance
  risk, not a convenience.
- `target_scope_type` (required): `platform_master` or `tenant`.
- `target_tenant_public_id` (required when `target_scope_type ==
  "tenant"`, forbidden otherwise): the destination tenant.
- `new_code` (required, always — never auto-generated or auto-suffixed):
  the caller must supply an explicit code for the new definition,
  normalized per §4b before the uniqueness check. Requiring an explicit
  code (rather than silently deriving one, e.g.
  `f"{source_code}_clone"`) avoids an implicit naming decision the
  caller may not want and makes the clone's identity a deliberate choice,
  not a side effect.
- `new_title` (required): likewise never derived automatically.
- `clone_sections`/`clone_questions`/`clone_applicability_rules`
  (booleans, default `true`): when `false`, the new definition/version is
  created as an **empty shell** (no sections/questions copied) — useful
  when only the definition's identity/scope is wanted as a starting
  point, not its content. `clone_questions: false` with
  `clone_sections: true` copies section structure without question
  content. `clone_applicability_rules` is independent of the other two:
  when `true`, any `ApplicabilityRule` referenced by a copied section/
  question is itself cloned (new `ApplicabilityRule` row, `version=1`,
  same `condition_json`) rather than the new question referencing the
  original rule row — consistent with §3e's "rules are cloned, not
  globally shared and mutable."

**Behavior:**
- Creates exactly one new `ChecklistDefinition` (scope/tenant per the
  request) and exactly one new `ChecklistVersion` on it, always
  `version_number=1`, always `status=draft` — **cloning never produces
  `approved` or `active` content**, regardless of the source version's
  own status. A clone is always a fresh starting point requiring its own
  full review cycle.
- When `clone_sections`/`clone_questions`/`clone_applicability_rules` are
  `true`, every copied `ChecklistSection`/`ChecklistQuestion`/
  `ApplicabilityRule` row receives a **new `public_id`** (never reuses
  the source row's `public_id`) and is attached to the new
  `ChecklistVersion` — the source rows are completely unchanged (read-
  only source, matching the design's "correction never mutates existing
  approved content" principle).
- **No provenance is copied**: the new `ChecklistVersion`'s
  `submitted_by`/`reviewed_by`/`approved_by`/`activated_by`/`returned_by`/
  `rejected_by`/`retired_by` and their timestamps are all `NULL` — this
  is a brand-new draft with its own review history starting from zero,
  never inheriting the source's approval chain.
- **No `superseded_by`/active-version pointer is copied** — the new
  version is not linked to the source definition's active-version state
  in any way; it belongs to an entirely separate `ChecklistDefinition`.
- **No `AuditEvent`/history rows are copied** — only a single new
  `iig_checklist.definition.cloned` event is emitted (§10), referencing
  both the source and destination public IDs plus `reason`; the source
  definition's own audit history is untouched and not duplicated onto
  the clone.
- **Authorization:** cloning **to** a `tenant` scope requires the acting
  user to hold `iig_checklist.clone` within that target tenant (checked
  against `target_tenant_public_id`, not the source's tenant).
  Platform-master → tenant cloning is permitted only when the actor
  additionally holds a platform-level grant (the same "platform-level,
  not tenant-membership-derived" check already specified in §7 for
  platform-master content) — **not** implied merely by holding
  `iig_checklist.clone` in some tenant. Tenant-to-*another*-tenant
  cloning (source tenant ≠ destination tenant) is **prohibited** unless
  the actor separately holds a platform-level cross-tenant grant — by
  default, a tenant user may only clone platform-master content or their
  own tenant's content into their own tenant, never reach into another
  tenant's definitions.
- **Conflict handling:** if `new_code` (post-normalization, §4b) already
  exists in the target scope, the endpoint returns a structured **409**
  (`DUPLICATE_CODE`), never a raw `IntegrityError`/500.
- **Atomicity:** the entire clone (new definition + new version + all
  copied sections/questions/rules) is created inside one
  `transaction.atomic()` block. Any failure partway through (including
  the 409 case above, checked before the transaction commits) rolls back
  the whole operation — never a partially-created definition with some
  but not all sections copied.

**Response** (`201`):
```json
{
  "public_id": "…",
  "code": "iig-oral-solid-v2-tenant-draft",
  "title": "IIG Oral Solid (tenant working copy)",
  "scope_type": "tenant",
  "tenant_public_id": "…",
  "current_version": {
    "public_id": "…",
    "version_number": 1,
    "status": "draft",
    "cloned_from_version_public_id": "…"
  }
}
```

`cloned_from_version_public_id` is retained on the response (and stored
as a plain, non-FK `CharField`/`UUIDField` reference on `ChecklistVersion`
for audit-trail readability only — not a foreign key, so deleting or
retiring the source version years later can never cascade into or block
operations on the clone) so a reviewer of the new draft can see what it
originated from without that link constituting shared, mutable state.

### 8b. Deletion policy (closes SR-06)

Previously implicit (via the `PROTECT` choices in §3) rather than stated
as a deliberate boundary. Stated explicitly here:

- **`ChecklistDefinition` is never hard-deleted once any `ChecklistVersion`
  exists on it.** No `DELETE /iig-checklists/definitions/{public_id}/`
  endpoint exists (§8's endpoint list has none, by design, confirmed
  here rather than left as a silent omission).
- **`ChecklistVersion` is never hard-deleted**, in any status. `approved`/
  `active`/`rejected`/`superseded`/`retired` versions are retained
  permanently (matching the design's reproducibility guarantee,
  discovery §18) — a version that reaches any of these statuses is
  governed history, not disposable data.
- **Sections/questions/rules belonging to a version that has ever been
  `submitted_review`d or later are likewise retained permanently** — the
  `DELETE` endpoints on `ChecklistSection`/`ChecklistQuestion` (§8) only
  succeed while the parent `ChecklistVersion.status` is `draft` or
  `returned` (already the same gate as the "editable while
  draft/returned" rule elsewhere in this document — restated here as a
  deletion-specific rule, not merely inferred from the edit-window rule).
- **One explicit, tightly-scoped exception:** an empty, never-submitted
  `ChecklistDefinition` may be hard-deleted (via a dedicated
  `DELETE /iig-checklists/definitions/{public_id}/` — the endpoint list
  in §8 is amended to add this one narrow case), **only when all of the
  following hold simultaneously**:
  1. The definition has **exactly one** `ChecklistVersion`.
  2. That version's `status == draft` and `submitted_at IS NULL` (i.e.
     it has never once been submitted for review, even if since
     returned to draft by some other path — though note nothing in this
     specification's transition table, §6, allows reaching `draft` from
     anywhere except initial creation, so in practice this reduces to
     "the definition's only version is its original, never-submitted
     draft").
  3. That version has no `ChecklistSection`/`ChecklistQuestion`/
     `ApplicabilityRule` rows referencing it that themselves have any
     audit-relevant history (in 4D-1, since sections/questions/rules are
     only ever created after the version, this reduces in practice to
     "the version may have sections/questions, since none of them can
     have audit-relevant history independent of a still-`draft`,
     never-submitted parent").
  4. The acting user holds a dedicated `iig_checklist.delete_draft`
     permission (a Doer-level grant, distinct from `edit_draft` — narrow
     enough that granting ordinary draft-editing access does not also
     grant deletion).
  - This delete **cascades** the definition's single version and its
    sections/questions/rules (a true `CASCADE`, not `PROTECT`, is used
    **only** for this specific in-practice-unreachable-any-other-way
    parent/child relationship — since nothing governed can exist here by
    construction of conditions 1–3).
  - The deletion is audited (`iig_checklist.definition.deleted` — a new
    event added to §10's list) with the definition's `code`/`scope_type`/
    actor, since even a permitted deletion of ungoverned content should
    leave a trace of *that it happened*.
  - **Everything else — an abandoned definition with more than one
    version, or any version beyond the first that has ever been
    submitted — is never deleted, only retired** (`retire` action, §6),
    which is the correct way to withdraw an unwanted definition/version
    from future use while preserving its history.

### 8c. API error semantics

A structured, consistent HTTP-status/error-code contract across every
endpoint in this app — no raw database exception or unhandled Python
exception ever reaches a client:

| Status | Used for |
|---|---|
| `400` | Field-level validation errors; illegal lifecycle transition (`IllegalVersionTransition`, §6); malformed `condition_json` (any of §5's error codes); `UNSUPPORTED_FIELD_REGISTRY_VERSION` (§4b) at `activate` time. |
| `403` | Permission denied — the acting user lacks the required `PERM_*` for the action, or fails the self-approval/scope check (§6/§7). |
| `404` | The requested `public_id` does not exist, or exists but is not visible to the acting user's tenant/scope (generic — never distinguishes "doesn't exist" from "exists but you can't see it," matching every other API in this codebase). |
| `409` | `DUPLICATE_CODE` (normalized-code collision, §3f, §8a); `VERSION_ALLOCATION_CONFLICT` (§6b, defense-in-depth only — should not occur in correct operation); `unique_active_version_per_definition` conflict surfaced as a structured conflict rather than a raw constraint-violation message (§6); a stale-data conflict on `PATCH` (see below). |

Every `400`/`409` response body carries a machine-readable `error_code`
field (one of the specific codes named throughout this document —
`CODE_BLANK`, `CODE_INVALID_CHARACTERS`, `CODE_TOO_LONG`,
`DUPLICATE_CODE`, `VERSION_ALLOCATION_CONFLICT`,
`UNSUPPORTED_FIELD_REGISTRY_VERSION`, plus §5's ten applicability-rule
error codes) alongside a human-readable message — never a bare message
string alone, so a frontend can branch on the exact failure without
string-matching.

**Stale-data/concurrency conflicts on `PATCH`** (editing a
section/question while another actor has concurrently changed the parent
version's status, e.g. it was `submit_review`d by someone else between
the frontend loading the edit form and the `PATCH` being sent): the
serializer re-checks `ChecklistVersion.status` is still `draft`/
`returned` at write time (not just at page-load time) and returns `409`
(`VERSION_NO_LONGER_EDITABLE`) rather than silently succeeding against a
version that has since moved to `under_review` or beyond.

---

## 9. Frontend specification

Routes (matching the existing `/fda-data/...` route-naming convention):

```
/iig-checklists/definitions
/iig-checklists/definitions/new
/iig-checklists/definitions/[publicId]
/iig-checklists/versions/[publicId]
/iig-checklists/versions/[publicId]/edit
/iig-checklists/versions/[publicId]/review
```

**Screens:** definition list (filterable by scope/status), create
definition (scope + code + title), version detail (read-only summary +
section/question tree), section/question editor (only rendered when
`status` is `draft`/`returned`), a lifecycle action panel (buttons gated
by the current user's permissions **and** the version's current status —
never showing an action the backend would reject, matching the mapping-
review page's confirmation-dialog pattern used throughout Milestone 4A–4C
for consistency), a review summary (read-only, for a reviewer/approver),
an activation confirmation dialog (states plainly that this will
supersede the currently-active version, if any), a clone confirmation
dialog.

**Required UI states, every screen:** loading, empty (`"No checklist
definitions match this filter."`, matching the existing empty-state
copy convention), error (with a retry action, matching the pattern
already used on `/fda-data/mappings`), permission-denied (a distinct,
non-alarming message, not a raw 403 dump), read-only rendering for
`approved`/`active`/`superseded`/`retired` versions (no edit controls
rendered at all, not merely disabled ones), a visible "Returned — reason:
…" banner when `status == returned`, and a conflict/concurrency error
surfaced distinctly (e.g. "This version was already activated by another
user" rather than a generic failure) when an `activate` call loses the
race described in §6.

**No checklist *execution* UI exists in 4D-1** — the frontend here is
authoring/governance only, matching the backend scope split in §1.

---

## 10. Audit events

`iig_checklist/audit_events.py`, exact same `emit()` wrapper shape as
`fda_data/audit_events.py`:

```python
class IigChecklistEvent:
    DEFINITION_CREATED = "iig_checklist.definition.created"
    DEFINITION_CLONED = "iig_checklist.definition.cloned"
    DEFINITION_DELETED = "iig_checklist.definition.deleted"  # §8b's narrow empty-draft case only
    VERSION_CREATED = "iig_checklist.version.created"
    VERSION_UPDATED = "iig_checklist.version.updated"
    VERSION_SUBMITTED = "iig_checklist.version.submitted_for_review"
    VERSION_RETURNED = "iig_checklist.version.returned"
    VERSION_APPROVED = "iig_checklist.version.approved"
    VERSION_REJECTED = "iig_checklist.version.rejected"
    VERSION_ACTIVATED = "iig_checklist.version.activated"
    VERSION_SUPERSEDED = "iig_checklist.version.superseded"
    VERSION_RETIRED = "iig_checklist.version.retired"
    SECTION_CREATED = "iig_checklist.section.created"
    SECTION_UPDATED = "iig_checklist.section.updated"
    SECTION_DELETED = "iig_checklist.section.deleted"
    QUESTION_CREATED = "iig_checklist.question.created"
    QUESTION_UPDATED = "iig_checklist.question.updated"
    QUESTION_DELETED = "iig_checklist.question.deleted"
    APPLICABILITY_RULE_CREATED = "iig_checklist.applicability_rule.created"
    APPLICABILITY_RULE_UPDATED = "iig_checklist.applicability_rule.updated"
    APPLICABILITY_RULE_VALIDATED = "iig_checklist.applicability_rule.validated"
```

**Metadata rules (matching the "safe metadata only" bar
`SUBSTANCE_MAPPING_CANDIDATE_CREATED` already established):** `payload`
carries public IDs, actor, tenant (when tenant-scoped), `scope_type`,
`previous_status`/`new_status` for lifecycle events, `reason` (for
`return`/`reject`), and a `correlation_id` — reusing the existing
correlation-ID convention from `fda_data`/`documents`. **Never** the full
`question_text`/`help_text`/`regulatory_reference` payload of a question
in the audit event body (this content may be regulatory-sensitive or, in
a tenant-scoped definition, tenant-proprietary — the audit record proves
*that* a question was created/changed and *by whom*, not a duplicate copy
of its content; the content itself is retrievable, permission-gated,
from the `ChecklistQuestion` row via its own public ID, which the audit
event does carry). No raw storage paths anywhere (not applicable to this
stage, since no evidence-attachment code exists yet — noted for
completeness against the discovery document's general rule). Append-only,
via the same `AuditEvent.objects.create()`-only pattern (no update/delete
path exists on `AuditEvent` at all, DB-trigger-enforced).

---

## 11. Migration plan

**`0001_initial`** — all five models (`ChecklistDefinition`,
`ChecklistVersion`, `ChecklistSection`, `ChecklistQuestion`,
`ApplicabilityRule`), all constraints and indexes from §3, in one
migration. No separate `0002` for DB triggers: unlike `AuditEvent`'s
append-only guarantee (which genuinely needs a Postgres trigger because
Django-level `save()`/`delete()` overrides on that model are the *only*
enforcement and could theoretically be bypassed by raw SQL), the
immutability guarantees here (§3b/§3c/§3d's "no field changes once
approved/active") are enforced by `full_clean()` actually being invoked
at every mutation attempt in the transition-service/serializer layer
(§6), which is sufficient for this stage and consistent with how
`SubstanceSynonymMapping`'s approved-immutability is enforced (model
`clean()`, not a DB trigger) — a DB-level backstop trigger is not part of
4D-1's scope, and this specification does not claim database-level
enforcement beyond the `UniqueConstraint`/`CheckConstraint` entries
explicitly listed in §3.

**Requirements verified before this stage is considered
migration-complete:** the migration applies cleanly from zero on a fresh
database; it applies cleanly on top of current `regx-main`
(`c8da170f7cb275fad34581edfd3b0ddcfde6bf9e`) with no conflicts against
any existing app's migrations; `manage.py makemigrations --check
--dry-run` reports "No changes detected" after the migration is written
by hand (matching the exact verification method already used for
`fda_data`'s `0003_substancesynonymmapping_rejected_by_and_more`
migration in Milestone 4A–4C's remediation); rollback is a plain
`migrate iig_checklist zero` since the app is new and no other app's
migration depends on it. **No data migration is included or needed** —
no production checklist content exists to migrate, and no existing table
is being altered.

---

## 12. Test specification

**Models:** scope/tenant `CheckConstraint` (platform-master requires
`tenant=NULL`, tenant-scoped requires non-null, both directions
attempted and rejected); `code` uniqueness (platform-master global,
tenant-scoped per-tenant, and the "same code across two different scopes
does not conflict" positive case); version-number uniqueness per
definition; active-version uniqueness per definition (including the
atomic-supersession case from §6); `effective_date`/`expiry_date`
ordering validation; immutability of `ChecklistVersion`/`ChecklistSection`/
`ChecklistQuestion` once the parent version is `approved`/`active`/
`superseded`/`retired` (attempted mutation raises `ValidationError`, not
silently succeeds); `ChecklistQuestion.clean()`'s three binding rules
(§3d) each tested independently, both positive and negative cases.

**Lifecycle:** all 7 legal transitions in §6's table; every illegal
transition explicitly enumerated (approve-from-draft, activate-from-
draft, submit_review-from-approved, etc. — matching the exhaustive style
of `test_mapping_lifecycle_transitions.py`); self-approval blocked; Doer
cannot approve/activate/reject/retire; concurrent-activation race
resolved to exactly one winner (real `threading.Thread` test, same
pattern as `TestConcurrentApproval`); rejected/superseded/retired are
terminal (no action succeeds against them); returned version can be
edited then resubmitted, with prior return provenance retained (§6);
approved/active content mutation blocked at the model layer even if a
view bug were to attempt it (defense in depth — tested directly against
the model, not only through the API).

**Applicability rule validation:** valid JSON accepted; each of the 10
error codes in §5 individually triggered and asserted; recursion-depth
and condition-count boundary values (exactly at the limit passes, one
over fails); canonical serialization produces identical output for
differently-ordered-but-equivalent input; explicit assertion that no
`eval`/`exec` path exists (a planted-failure-style test attempting a
condition value containing Python syntax, asserting it is treated as an
inert string/rejected as a type mismatch, never executed — matching this
codebase's existing planted-failure test convention).

**Lifecycle refinement (§6a, SR-01):** `return` from `under_review`
succeeds and sets `returned_by`/`returned_at`/`return_reason`; content is
editable while `returned`; a direct `approve` attempt against a
`returned` version is illegal (400) — it must go through `submit_review`
again first; `resubmit` (i.e. `submit_review` from `returned`) sets a new
`submitted_at`/`submitted_by` while the prior `returned_by`/`returned_at`/
`return_reason` remain unchanged in the row (asserted explicitly, not
merely not-cleared); `reject` is terminal — no action succeeds against a
`rejected` version, including a second `reject` call; a rejected
version cannot be resubmitted, approved, activated, or edited under any
permission.

**Clone (§8a, SR-02):** cloning a specified `source_version_public_id`
produces a new `ChecklistDefinition` + a `version_number=1` `draft`
`ChecklistVersion`; cloning an `under_review`/`draft`/`returned`/
`rejected`/`retired` source version is rejected (400); copied section/
question/rule rows have `public_id`s distinct from the source's; no
`submitted_by`/`reviewed_by`/`approved_by`/etc. provenance is copied
(all `NULL` on the clone); a cross-tenant clone (destination tenant ≠
actor's tenant, without a platform-level grant) is blocked (403); a
platform-master → tenant clone without the platform-level grant is
blocked (403); a duplicate `new_code` (post-normalization) returns 409
(`DUPLICATE_CODE`); a clone that fails partway through (e.g. the 409
case) leaves no partially-created definition/version/section rows behind
(atomic rollback, asserted by querying for orphaned rows after the
failed attempt).

**Code normalization (§3f, SR-03):** `"iig oral"`, `"IIG_ORAL"`,
`" iig_oral "`, and `"iig_oral"` all normalize to the identical stored
value and therefore collide (the second creation attempt with any of
these four inputs returns 409 `DUPLICATE_CODE` after the first
succeeds); an invalid character (e.g. `"iig.oral"`, `"iig#oral"`) is
rejected with `CODE_INVALID_CHARACTERS`; a blank/whitespace-only code is
rejected with `CODE_BLANK`; a code exceeding 100 characters is rejected
with `CODE_TOO_LONG`; the stored value in the database is confirmed to
be the normalized (uppercase, whitespace-collapsed) form, not the raw
input, for all four code-bearing models.

**Concurrent version-number allocation (§6b, SR-04):** two genuinely
concurrent `POST .../versions/` requests against the same definition
(real `threading.Thread` + separate `APIClient`/DB connections,
`pytest.mark.django_db(transaction=True)`, mirroring
`TestConcurrentVersionAllocation` from
`templates_registry/tests/test_review_remediation.py`) produce exactly
two versions numbered `1` and `2` — never a duplicate, never a raw
`IntegrityError` surfaced to either caller; `version_number` is confirmed
absent from the create-version request schema (supplying it in the
request body has no effect on the stored value); an audit event is
emitted only for the version that successfully persists, once per
successful creation.

**Answer-type/classification compatibility matrix (§3d-i, SR-05):** a
single parametrized test exercises **every** `(answer_type,
data_source_classification)` pair against the matrix table, asserting
`ALLOWED`/`CONDITIONALLY_ALLOWED` pairs succeed and every other pair is
rejected with a structured 400; specific floor assertions:
`APPROVAL_METADATA` can never be created with
`data_source_classification` other than `REVIEWER_CONFIRMED`;
`CALCULATED_VALUE`/`CALCULATED_STATUS` can never be created with
anything other than `SYSTEM_CALCULATED`; `EVIDENCE_DERIVED` always
requires `evidence_requirement=required`; `REVIEWER_CONFIRMED` always
requires `reviewer_confirmation_required=True`.

**Deletion policy (§8b, SR-06):** a `ChecklistDefinition` with more than
one version cannot be deleted (404/405 on the delete endpoint, or the
endpoint simply does not exist for that case — confirmed by attempting
it and asserting failure); a definition whose single version has ever
been `submitted_review`d cannot be deleted; the one permitted case
(single, never-submitted `draft` version, actor holds
`PERM_DELETE_DRAFT`) succeeds and cascades its section/question/rule
rows; the deletion emits `iig_checklist.definition.deleted`; an actor
holding only `PERM_EDIT_DRAFT` (not `PERM_DELETE_DRAFT`) is blocked
(403) from the same otherwise-eligible deletion.

**Field-registry versioning (§4b, SR-08):** a rule created against
`allowed_field_registry_version=1` remains valid and reproducible after
`FIELD_REGISTRY_VERSION` is (in the test, monkeypatched/fixture-bumped
to) `2`; a newly-created rule is rejected if it declares an
`allowed_field_registry_version` other than the current constant; an
`activate` attempt on a version whose applicability rules reference an
explicitly-unsupported registry version is blocked (400
`UNSUPPORTED_FIELD_REGISTRY_VERSION`); an already-`approved`/`active`
rule's `allowed_field_registry_version` and `condition_json` are
confirmed unchanged after a registry bump (no silent mutation).

**API:** UUID-only in every response (numeric `id`/`pk` never present,
asserted the same way `test_proposal_public_uuid_only` already asserts
this for `fda_data`); generic 404 for a wrong-tenant or wrong-scope
resource; tenant isolation (a user from tenant A cannot see/edit tenant
B's definitions); platform-master read-visible-to-all-authenticated-
tenant-members but not editable without the platform-level grant;
pagination and filter bounds; mass-assignment protection (a `PATCH`
request smuggling a `status` field is silently ignored, matching
`test_status_cannot_be_supplied_as_approved`'s pattern from Milestone
4A–4C); a direct `activate`/`approve` call against a non-legal source
status returns 400, not a 500 or a silent no-op; every `400`/`409`
response body carries the specific `error_code` named in §8c, asserted
exactly (not just the HTTP status); a stale `PATCH` against a version
that moved to `under_review` between page-load and submission returns
409 `VERSION_NO_LONGER_EDITABLE`.

**Audit:** every lifecycle action emits its corresponding event; an
illegal transition emits **no** audit event (explicitly asserted absent,
not merely not-asserted-present); event payloads never contain
`question_text`/`help_text`/`regulatory_reference`.

**Frontend (Vitest + React Testing Library + jest-axe):** list/create/
edit/review flows; read-only rendering for non-editable statuses;
lifecycle buttons rendered only when both permission and status allow
the action; confirmation dialogs required before every lifecycle action
(never a bare button triggering a mutation); returned-reason banner
rendering; structured API-error rendering; keyboard accessibility (no
serious/critical `jest-axe` violations, matching the existing
accessibility test bar); no optimistic UI state implying success before
the server confirms it.

**Playwright:** create a tenant-scoped definition → add a section and
question → `submit_review` → a reviewer `return`s it with a reason → the
original author edits and resubmits → a different, VP-permissioned actor
`approve`s → `activate`s → a second `activate` attempt (e.g. of another
version) is blocked while this one remains active → the approved/active
content renders read-only with no edit controls.

**Docker smoke** (extends `.github/workflows/docker-integration.yml`,
same production-path philosophy the Milestone 4A–4C remediation
established — no direct ORM creation of governed content in the smoke
flow): fresh migrations apply; a synthetic definition + version + section
+ question are created via the production API (never direct ORM
`.objects.create()` on `ChecklistVersion`); a direct `activate` attempt
on a still-`draft` version is blocked (400); the full `submit_review` →
`approve` → `activate` path succeeds with distinct actors at each step;
active-version uniqueness is verified by attempting to activate a second
version of the same definition and confirming exactly one ends up
`active`; API responses are checked for UUID-only/no-storage-path safety;
zero container restarts; clean teardown.

---

## 13. Security and data-integrity controls

UUID-only public API surface (§8); `BigAutoField` internal PKs never
serialized; tenant isolation enforced at the queryset layer for every
tenant-scoped read/write; platform-master rows readable by any
authenticated tenant member but writable only with a platform-level
grant (§7); `transaction.atomic()` + `select_for_update()` on every
lifecycle transition (§6); no field-level mutation possible once a
version reaches `approved`/`active`/`superseded`/`retired` (§3b–§3d);
generic PATCH serializers carry no `status` field (§8); applicability-
rule JSON payloads are bounded (recursion depth, condition count, byte
size, §5) and validated against a fixed allow-list — no `eval`/`exec`,
no dynamically-interpreted expression, ever; no raw storage path is
introduced by this stage (no file-attachment code exists yet); no
numeric internal ID is ever serialized; no confidential
question/help/regulatory-reference text appears in audit-event metadata
(§10); `AuditEvent` rows are append-only via the existing DB-trigger-
enforced mechanism, unmodified by this stage; no action in this stage
can activate a `ChecklistVersion` automatically — every `activate` call
requires an explicit, permissioned, non-self-approving human action;
cloning (`POST .../clone/`) always produces a new `draft` — never a
clone that starts pre-approved or pre-active; **no real regulatory
checklist content exists anywhere in this stage** — only the synthetic
paracetamol/acetaminophen fixture from the design document is used in
tests, and the production proposal path itself has no privileged
"seed real content" shortcut.

---

## 14. Acceptance criteria

4D-1 is complete only when:

- This app architecture (§2) and model set (§3) are implemented exactly
  as specified, or with any deviation explicitly documented and
  justified in a follow-up to this specification.
- The `ChecklistVersion` lifecycle service (§6), permission model (§7),
  and APIs (§8) are implemented and pass every test in §12.
- The minimal frontend administration screens (§9) are implemented and
  pass their corresponding tests.
- The applicability-rule JSON schema (§5) is validated exactly as
  specified, with every error code in §5 individually exercised by a
  test.
- All backend tests, frontend tests, and the Docker smoke extension in
  §12 pass.
- `manage.py makemigrations --check --dry-run` reports no changes after
  the migration is written (§11).
- A human review of the implementation finds no Critical or Major
  defect (following the same focused-review gate pattern already
  established for Milestone 4A–4C's PR #5).
- Only synthetic `ChecklistDefinition`/`ChecklistVersion` content exists
  anywhere in the implementation's tests and Docker smoke flow — no real
  IIG guidance content, no production FDA data, no production client
  data.
- No `ChecklistExecution`/`ChecklistResponse`/`CalculationOutcome` model,
  API, or UI exists — 4D-1 governs content authoring only.
- No automatic safety, acceptability, or regulatory-approval conclusion
  is possible anywhere in this stage's surface (it has none — this stage
  only governs *definitions*, not assessments of any real formulation).

---

## 15. Implementation-authorization boundary

**This specification does not authorize any code, migration, API,
frontend, or test to be written.** It is a specification-review
artifact, matching the exact boundary already established for
[MILESTONE_4D_DISCOVERY.md](MILESTONE_4D_DISCOVERY.md) itself. After this
specification is reviewed and approved (via a design/spec-review gate,
following the same pattern as the discovery document's two review
passes), **a separate, explicit implementation prompt may authorize
work on 4D-1.** This document, on its own, authorizes nothing beyond its
own existence as a reviewable artifact.

---

## 16. Traceability table

| Approved design requirement (source) | 4D-1 component | Model/API/UI/Test | Security control | Acceptance evidence | Deferred to |
|---|---|---|---|---|---|
| New `iig_checklist` app, not extending `iid_assessment` (discovery §1, DR-06) | App scaffold, import-linter contract | §2 | Forbidden-import-direction contract | `lint-imports` passes with the new contract | — |
| Five-way data classification incl. `EVIDENCE_DERIVED` (discovery §3, DR-01) | `DataSourceClassification` enum | §4, model §3d | `clean()` cross-field rule (evidence_requirement forced for EVIDENCE_DERIVED) | Model tests §12 | Runtime resolution of an actual answer: 4D-2 |
| `NOT_APPLICABLE` as a structural response state, not a data-source category (discovery §3a) | `ApplicabilityOutcome` enum | §4, §5 | N/A at definition stage — no `ChecklistResponse` exists yet | Schema/validation tests §12 | Actual per-response `is_not_applicable` field on `ChecklistResponse`: 4D-2 |
| `ChecklistDefinition` lifecycle/activation table, one-active-per-code (discovery §1a, DR-02) | `ChecklistVersion` model + transition service | §3b, §6 | `unique_active_version_per_definition`, atomic supersession | Lifecycle tests, concurrency test §12 | — |
| Applicability-rule structured JSON, allow-listed operators, no eval (discovery §9a, DR-03) | `ApplicabilityRule` model, schema, field registry | §3e, §4a, §5 | Bounded recursion/count/size, fixed dispatch table (evaluator itself: later stage) | Validation error-code tests §12 | Runtime evaluation against a real execution context: 4D-3 |
| Mutation-boundary immutability, learned from the unenforced `AssessmentSnapshot.clean()` finding (discovery §7/§18, DR-02) | `clean()` invoked at every mutation path, not left unreachable | §3b–§3d | Enforced in serializer/service layer, tested directly against the model | Immutability tests explicitly assert `full_clean()` is invoked, §12 | — |
| Expanded 11-value answer-type enum (discovery §6a, DR-05) | `AnswerType` enum | §4, §3d | N/A | Enum completeness test | — |
| `CANCELLED`/`SUPERSEDED` execution states (discovery §8a, DR-05) | N/A — these are `ChecklistExecution` states, not `ChecklistVersion` states | — | — | — | `ChecklistExecution` model: 4D-2 |
| Single execution-level approval covers all overrides (discovery §12) | N/A — overrides don't exist until executions do | — | — | — | 4D-5 |
| Honest `StubScanner` disclosure (discovery §15, DR-07) | N/A — no evidence-attachment code in 4D-1 | — | — | — | Evidence attachment model/API: 4D-2; scanner deployment remains a separate, cross-cutting item |
| Correct calculation function names, `CalculationOutcome` field completeness (discovery §9, DR-04) | `calculation_binding_identifier` stored as a validated string, not yet bound to a live function call | §2, §3d, §6 | Shape-only validation against a declarative allow-list in 4D-1 | Binding-rule tests §12 | Actual `CalculationOutcome`/live `iid_assessment.calculations` call: 4D-3 |
| SHA-256 export checksum, JSON/CSV export scope, PDF/Word deferred (discovery §17) | N/A — no export exists until an execution exists to export | — | — | — | 4D-7 |
| One execution per formulation version (discovery §8, resolved open question 5) | N/A — no `ChecklistExecution` FK shape exists yet | — | — | — | 4D-2 |
| Controlled-deferral resolution of checklist-template content (discovery, resolved open question 4) | Only synthetic definitions used anywhere in this stage | §1, §12, §14 | No privileged "seed real content" path exists | Acceptance criterion explicitly checked, §14 | Real regulatory content: a separate regulatory-content approval gate, before 4D-4 |
| No Part 11 e-signature claim (discovery §16 additional decisions) | `approved_by`/`approved_at` etc. are standard authenticated-action logging, nothing more | §3b | — | — | — |
| Reviewer/approver provenance never overwritten (HR-03 lesson, carried into discovery §8) | Six distinct provenance field-pairs on `ChecklistVersion` | §3b | Each field set only by its own action | Provenance tests §12 | — |
| **SR-01** — Lifecycle refinement (`RETURNED`/`return`/`resubmit`, distinct terminal `REJECTED`) disclosed and approved, diverging intentionally from discovery §1a's leaner 6-action table | 7-action `ChecklistVersion` transition table | §6, §6a | Self-approval block, Doer-cannot-approve, structured 400, no audit-on-failure — all unchanged from the base pattern | Lifecycle-refinement tests §12 | — |
| **SR-02** — Clone semantics fully specified (source-version eligibility, no provenance copy, new UUIDs, atomicity, cross-tenant/platform authorization, 409 on duplicate code) | `clone` endpoint exact contract | §8a | Atomic transaction, authorization checks, no privileged pre-approved output | Clone tests §12 | — |
| **SR-03** — Code normalization (case/whitespace canonicalization, fixed grammar, deterministic 409) | `normalize_code()`, applied at serializer/model/DB layers | §3f | No reliance on DB collation; explicit collision rule | Normalization tests §12 | — |
| **SR-04** — Concurrent version-number allocation (`select_for_update()` on parent, citing the `templates_registry` precedent) | Version-creation service | §6b | Row lock serializes allocation; 409 backstop, never a raw 500 | Concurrency test §12 | — |
| **SR-05** — Answer-type × classification compatibility matrix (all 90 combinations classified, central registry) | `ANSWER_TYPE_CLASSIFICATION_MATRIX` | §3d-i | `APPROVAL_METADATA`/`CALCULATED_VALUE`/`CALCULATED_STATUS` floors enforced | Matrix-parametrized test §12 | — |
| **SR-06** — Explicit deletion policy (no hard-delete of governed content; one narrow, permissioned empty-draft exception) | Deletion rules + `PERM_DELETE_DRAFT` | §8b, §7 | `PROTECT` by default; `CASCADE` only for the in-practice-unreachable-otherwise empty-draft case | Deletion tests §12 | — |
| **SR-07** — Explicit decision: no `REVIEW_COMPLETE` state for `ChecklistVersion` | Design-decision note | §6c | N/A (a documented non-change) | N/A | — |
| **SR-08** — Field-registry version-bump behavior (immutable per-rule version, additive registry growth, no auto-migration) | `FIELD_REGISTRY_VERSION` handling | §4b | Activation-time support check (`UNSUPPORTED_FIELD_REGISTRY_VERSION`) | Field-registry tests §12 | — |

Full finding-by-finding traceability for SR-01 through SR-08, including
original gap/severity/decision/correction/test-impact/closure status, is
recorded separately in
[MILESTONE_4D_1_SPEC_REMEDIATION.md](MILESTONE_4D_1_SPEC_REMEDIATION.md).

---

## 17. Self-review

- No code, migration, workflow, or Docker file is added by this
  specification — only `docs/MILESTONE_4D_1_IMPLEMENTATION_SPEC.md` and
  `docs/MILESTONE_4D_1_SPEC_REMEDIATION.md`.
- All 4 Critical/Major findings and all 3 Minor findings from the first
  specification-review pass are closed (SR-01 through SR-08, §16).
- No implementation branch is created beyond
  `regx/spec/milestone-4d-1-definition-governance`, which itself carries
  only these two documentation files.
- Naming matches current repository conventions throughout: `PublicIDModel`/
  `TimeStampedModel` from `common.models`; `BigAutoField` internal PKs;
  `TextChoices` enums; `emit()`/event-constant-class pattern from
  `fda_data/audit_events.py`; `PERM_*`/`ROLE_PERMISSIONS`/
  `_*PermissionBase` pattern from `fda_data/permissions.py`; hyphenated
  URL path segments matching `fda-data/`; the exact
  `unique_active_release_per_dataset_type` precedent cited for
  `unique_active_version_per_definition`.
- Calculation function names referenced (§2, §16) are exactly
  `calculate_percentage_w_w`, `calculate_daily_exposure`,
  `calculate_percentage_of_potency`, `calculate_difference_from_potency`,
  `calculate_percentage_of_mde`, `calculate_difference_from_mde` — no
  `iid_`-infixed variant appears anywhere in this document.
- No claim anywhere in this document states or implies that any part of
  4D-1 is already implemented — every section is written in specification
  voice ("is specified as," "would be implemented as"), not
  implementation-report voice.

---

**After this specification is reviewed and approved, a separate
implementation prompt may authorize 4D-1. This specification does not
authorize code changes.**
