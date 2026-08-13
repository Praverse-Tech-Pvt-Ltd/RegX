# Milestone 5A — Regulatory Content Package Template

> **Status:** TEMPLATE — contains **no production regulatory content**.
> Every value below is a **field definition, placeholder or worked
> illustration of *form*.** Nothing here is a proposed answer.
> **Companions:** [MILESTONE_5A_DISCOVERY.md](MILESTONE_5A_DISCOVERY.md),
> [MILESTONE_5A_APPROVAL_REGISTER.md](MILESTONE_5A_APPROVAL_REGISTER.md)

## How to read this document

Placeholders are written `<ANGLE_BRACKETS>`. Where an example appears, it uses
obviously non-regulatory filler (`EXAMPLE_ONLY`, `<…>`) so it can never be
mistaken for approved content or copied into a package by accident.

**Engineering fills in nothing in §2–§5.** Engineering supplies only the
`engineering_check` blocks, and only after the authority has authored the rest.

---

## 1. Package envelope

One package may propose several checklist definitions. Metadata applies to the
package as a whole.

| Field | Type | Owner | Required | Notes |
|---|---|---|---|---|
| `package_id` | string | Regulatory | yes | Stable label, e.g. `<ORG>-IIG-<YYYY>-<NN>` |
| `package_version` | string | Regulatory | yes | Increments on every re-issue |
| `package_status` | enum | Regulatory | yes | `DRAFT` \| `ENGINEERING_CHECK` \| `RETURNED` \| `REGULATORY_REVIEW` \| `REGULATORY_APPROVED` \| `FORMALLY_SIGNED` \| `READY_FOR_ENGINEERING_LOAD` |
| `prepared_by` | person | Regulatory | yes | Name and role |
| `prepared_date` | date | Regulatory | yes | |
| `reviewed_by` | person | Regulatory | yes | **Must differ from `prepared_by`** (`5A-DEC-007`) |
| `regulatory_approver` | person | Regulatory authority | at signing | The qualified authority signing item 20. **Must differ from `prepared_by`** (`5A-DEC-007`) |
| `engineering_reviewer` | person | Engineering | at compatibility check | Records who ran the mechanical check. **This is not a regulatory approval** and must never be recorded as one |
| `definitions_included` | list | Regulatory | yes | Only listed definitions are in scope |
| `commit_sha` | string | Engineering | at signing | Git SHA of the signed content files |
| `content_checksum` | string | Engineering | at signing | SHA-256 over the exact approved file bytes |

---

## 2. Checklist definition

One block per proposed definition.

| Field | Type / constraint | Owner | Maps to |
|---|---|---|---|
| `definition_code` | `^[A-Z0-9][A-Z0-9_-]*$`, ≤ 100 chars, unique in scope | Regulatory (Eng confirms grammar) | `ChecklistDefinition.code` |
| `definition_title` | ≤ 255 chars | Regulatory | `ChecklistDefinition.title` |
| `description` | free text | Regulatory | `ChecklistDefinition.description` |
| `scope_type` | `platform_master` for official content (`5A-DEC-006`) | Project owner + Regulatory | `ChecklistDefinition.scope_type` |
| `jurisdiction` | controlled vocabulary — `US_FDA` | Regulatory | `ChecklistVersion.jurisdiction` (`5A-DEC-005`) |
| `regulatory_basis` | ≤ 500 chars | Regulatory | `ChecklistVersion.regulatory_basis` |
| `source_references` | list of §4 records | Regulatory | evidence only, not stored on the model |
| `version_number` | positive integer | Regulatory | `ChecklistVersion.version_number` |
| `effective_date` | date | Regulatory | `ChecklistVersion.effective_date` |
| `expiry_date` | date, optional | Regulatory | `ChecklistVersion.expiry_date` |
| `change_summary` | free text | Regulatory | `ChecklistVersion.change_summary` |

```yaml
definition:
  definition_code: "<CODE>"
  definition_title: "<TITLE>"
  description: "<DESCRIPTION>"
  scope_type: "platform_master"              # 5A-DEC-006 for official content
  jurisdiction: "US_FDA"                     # controlled vocabulary (5A-DEC-005)
  regulatory_basis: "<BASIS>"                # <= 500 chars
  source_references: [ "<SRC-ID>", ... ]     # see section 4
  version_number: <N>
  effective_date: "<YYYY-MM-DD>"
  expiry_date: "<YYYY-MM-DD|null>"
  change_summary: "<SUMMARY>"
```

---

## 3. Sections and questions

### 3.1 Section

| Field | Type / constraint | Owner | Maps to |
|---|---|---|---|
| `section_code` | code grammar, unique per version | Regulatory | `ChecklistSection.code` |
| `section_title` | ≤ 255 chars | Regulatory | `ChecklistSection.title` |
| `section_description` | free text | Regulatory | `ChecklistSection.description` |
| `section_order` | integer, unique per version | Regulatory (Eng derives `display_order`) | `ChecklistSection.display_order` |
| `criticality` | `informational`\|`low`\|`medium`\|`high`\|`critical` | Regulatory | `ChecklistSection.criticality` |
| `applicability_rule_code` | optional | Regulatory | `ChecklistSection.applicability_rule` — **evaluated at runtime** (`5A-DEC-004`) |

### 3.2 Question

| Field | Type / constraint | Owner | Maps to |
|---|---|---|---|
| `question_code` | code grammar, unique per section; **version-wide unique if a binding target** | Regulatory + Eng | `ChecklistQuestion.code` |
| `question_text` | verbatim, free text | **Regulatory only** | `ChecklistQuestion.question_text` |
| `question_order` | integer, unique per section | Regulatory | `ChecklistQuestion.display_order` |
| `answer_shape_intent` | plain-language statement of what is being asked | **Regulatory** | — (input to the mapping) |
| `answer_type` | one of 18 enum values | **Joint** — Eng maps, Regulatory confirms | `ChecklistQuestion.answer_type` |
| `source_classification` | one of 5 enum values | **Joint** | `ChecklistQuestion.data_source_classification` |
| `required` | boolean | Regulatory | `ChecklistQuestion.required` |
| `criticality` | criticality enum | Regulatory | `ChecklistQuestion.criticality` |
| `help_text` | free text | Regulatory | `ChecklistQuestion.help_text` |
| `regulatory_reference` | ≤ 500 chars | Regulatory | `ChecklistQuestion.regulatory_reference` |
| `reviewer_expectation` | free text — what the reviewer must satisfy themselves of | **Regulatory only** | ⚠ **no dedicated field — see note below** |
| `reviewer_confirmation_required` | boolean | Regulatory | `ChecklistQuestion.reviewer_confirmation_required` — **forced true** for `reviewer_confirmed` |
| `evidence_requirement` | `none`\|`optional`\|`required`\|`required_if_overridden` | Regulatory | `ChecklistQuestion.evidence_requirement` — **forced `required`** for `evidence_derived` |
| `allowed_units` | list; **non-empty required** for `quantity_with_unit` | Joint | `ChecklistQuestion.allowed_units` |
| `options` | list of `{value, label}` for `single_select`/`multi_select` | Regulatory | `validation_rule.options` (`5A-DEC-002`). **Both required**: an empty value or label is refused, as are duplicates. Authored order is the display order |
| `calculation_binding_identifier` | one of the six | **Joint** | `ChecklistQuestion.calculation_binding_identifier` |
| `fda_derived_binding` | an **approved resolver identifier** | **Joint** | `ChecklistQuestion.prefill_source` (`5A-DEC-001`). Validated against the registry at authoring time; an unknown identifier is refused. See **OQ-8** on source selection |
| `applicability_rule_code` | optional | Regulatory | `ChecklistQuestion.applicability_rule` — **evaluated at runtime** (`5A-DEC-004`) |
| `override_expectation` | regulatory expectation | Regulatory, within a fixed floor | governed by classification, not stored per question |
| `export_inclusion` | not required for 5A | — | `5A-DEC-003`: full governed inclusion for the first production release |

**`reviewer_expectation` has no dedicated model field.** The nearest existing
fields are `help_text` and `regulatory_reference`. Where a reviewer expectation
is recorded is a joint decision at load time and must be resolved before load —
it must not be silently merged into `help_text` by engineering.

```yaml
question:
  question_code: "<CODE>"
  question_text: "<VERBATIM REGULATORY QUESTION TEXT — REGULATORY AUTHOR ONLY>"
  question_order: <N>
  answer_shape_intent: "<PLAIN-LANGUAGE STATEMENT OF WHAT IS BEING ASKED>"
  answer_type: "<mapped by engineering, confirmed by regulatory>"
  source_classification: "<mapped by engineering, confirmed by regulatory>"
  required: <true|false>
  criticality: "<informational|low|medium|high|critical>"
  help_text: "<GUIDANCE TEXT>"
  regulatory_reference: "<REFERENCE>"
  reviewer_expectation: "<WHAT THE REVIEWER MUST SATISFY THEMSELVES OF>"
  evidence_requirement: "<none|optional|required|required_if_overridden>"
  allowed_units: [ "<UNIT>", ... ]           # required if quantity_with_unit
  options:                                   # single_select / multi_select
    - { value: "<STABLE_MACHINE_VALUE>", label: "<APPROVED HUMAN LABEL>" }
  calculation_binding_identifier: "<one of the six|null>"
  fda_derived_binding: "<APPROVED RESOLVER IDENTIFIER|null>"   # 5A-DEC-001
  applicability_rule_code: "<RULE_CODE|null>"        # evaluated at runtime (5A-DEC-004)
  override_expectation: "<EXPECTATION>"
  # export_inclusion omitted: 5A-DEC-003 mandates full governed inclusion
  source_references: [ "<SRC-ID>", ... ]
  engineering_check:                                  # ENGINEERING ONLY
    matrix_pair_allowed: <true|false>
    binding_identifier_known: <true|false|n/a>
    findings: [ ]
```

### 3.3 Fixed engine facts a content author must know

Reproduced from `MILESTONE_5A_DISCOVERY.md` §3, which carries the code citations.

1. `percentage`, `calculated_value`, `calculated_status` → `system_calculated` **only**.
2. `reviewer_conclusion`, `approval_metadata` → `reviewer_confirmed` **only**.
3. Exactly **six** calculations exist; a seventh cannot be added for content.
4. If any calculation is used, a question coded exactly **`Q_SUBJECT_COMPONENT`**
   must exist with `answer_type = formulation_component_reference`. If an MDE
   calculation is used, **`Q_DAILY_EXPOSURE`** must also exist as a
   `system_calculated` question bound to `daily_exposure`. These two **codes**
   are engineering-reserved; their **text** is regulatory.
5. Only `fda_derived_default` is overridable; there is no clear-override path.
6. A `system_calculated` answer stores no value on the response; the result lives
   in `CalculationOutcome`.
7. Applicability rules may reference only six fields: `product.route`,
   `product.dosage_form`, `product.release_type`, `iid.match_status`,
   `iid.has_mde`, `iid.has_potency`.
8. All external identifiers are UUIDs; no database IDs appear anywhere.
9. Content must be answerable without re-querying live FDA/formulation data
   after approval (reproducibility, §18).
10. **Select options carry an approved label** (`5A-DEC-002`). The stored answer
    is always the machine value; the label is what a reviewer sees, and it is
    never derived from the value.
11. **Applicability rules are evaluated at runtime** (`5A-DEC-004`). A rule over
    `product.*` decides applicability automatically. A rule reading `iid.*`
    currently evaluates to `review_required` pending **OQ-8**.
12. **FDA-derived bindings must name an approved resolver identifier**
    (`5A-DEC-001`). An unknown identifier is refused when the question is
    authored. Until **OQ-8** is answered a binding records
    `source_unavailable` rather than a value -- nothing is fabricated.

---

## 4. Source-evidence model

Every regulatory decision carries one or more of these. **No external guidance
is fetched, quoted or interpreted in this discovery slice** — this defines the
evidence requirement only.

| Field | Required | Notes |
|---|---|---|
| `source_id` | yes | Stable label used in `source_references` |
| `source_title` | yes | Full title as published |
| `issuing_authority` | yes | e.g. the issuing agency or standards body |
| `source_version` | yes | Edition/revision designation |
| `publication_date` | yes | As published |
| `revision_date` | if applicable | |
| `retrieval_date` | yes | When the referenced copy was obtained |
| `reference_locator` | yes | Section / page / paragraph — **precise, not document-level** |
| `official_location` | yes | Official source location |
| `excerpt` | **only where licensing permits** | Omit rather than risk it; a locator is always sufficient |
| `interpretation_statement` | yes | How the source supports this decision — **the regulatory judgement itself** |
| `interpretation_author` | yes | Named individual |
| `interpretation_reviewer` | yes | Named individual, ideally ≠ author |
| `approval_status` | yes | `DRAFT` \| `REVIEWED` \| `APPROVED` |

```yaml
source_reference:
  source_id: "<SRC-ID>"
  source_title: "<TITLE>"
  issuing_authority: "<AUTHORITY>"
  source_version: "<VERSION>"
  publication_date: "<YYYY-MM-DD>"
  revision_date: "<YYYY-MM-DD|null>"
  retrieval_date: "<YYYY-MM-DD>"
  reference_locator: "<SECTION / PAGE / PARAGRAPH>"
  official_location: "<OFFICIAL LOCATION>"
  excerpt: "<OMIT UNLESS LICENSING PERMITS>"
  interpretation_statement: "<REGULATORY INTERPRETATION>"
  interpretation_author: "<NAME, ROLE>"
  interpretation_reviewer: "<NAME, ROLE>"
  approval_status: "<DRAFT|REVIEWED|APPROVED>"
```

**Non-guidance decisions.** A decision resting on organizational policy rather
than external guidance is recorded with `source_id: ORGANISATIONAL_POLICY`, an
interpretation statement, and no citation. This is acceptable **when declared**.
What is not acceptable is a guidance-derived decision with no citation.

---

## 5. Template-scope decision worksheet — **Item 1, the first gate**

The candidates below are quoted from `MILESTONE_4D_DISCOVERY.md:1089`, which
names them as **candidates only**, with a question mark. They are reproduced
here because they are the repository's own list.

**No template has been selected, recommended, ranked or excluded by
engineering.** The candidate list is not a proposal, and "potentially others" is
part of the original text — the authority may add, replace or reject any of it.

One worksheet per candidate. `INCLUDE` / `EXCLUDE` / `DEFER` is a regulatory
decision.

| Field | Owner | Notes |
|---|---|---|
| `candidate_name` | Regulatory | |
| `intended_scope` | Regulatory | Dosage form / use scope the template covers |
| `regulatory_rationale` | Regulatory | Why this template should or should not exist |
| `source_guidance` | Regulatory | §4 records |
| `applicability_boundary` | Regulatory | What is in scope for this template |
| `exclusions` | Regulatory | What is explicitly out of scope |
| `shares_questions_with` | Regulatory | Other candidates sharing questions |
| `distinct_reviewer_expectations` | Regulatory | Whether reviewer expectations differ |
| `engine_support_assessment` | **Engineering** | Whether current answer types and the six calculations can express it — **mechanical only** |
| `decision` | **Regulatory** | `INCLUDE` \| `EXCLUDE` \| `DEFER` |
| `decision_rationale` | Regulatory | |
| `decided_by` / `decision_date` | Regulatory | |

```yaml
template_scope_decision:
  candidate_name: "<CANDIDATE>"
  intended_scope: "<SCOPE>"
  regulatory_rationale: "<RATIONALE>"
  source_guidance: [ "<SRC-ID>", ... ]
  applicability_boundary: "<BOUNDARY>"
  exclusions: "<EXCLUSIONS>"
  shares_questions_with: [ "<CANDIDATE>", ... ]
  distinct_reviewer_expectations: <true|false>
  engine_support_assessment: "<ENGINEERING: mechanical feasibility only>"
  decision: "<INCLUDE|EXCLUDE|DEFER>"
  decision_rationale: "<RATIONALE>"
  decided_by: "<NAME, ROLE>"
  decision_date: "<YYYY-MM-DD>"
```

### Candidate worksheets — all UNDECIDED

| # | Candidate (from `4D_DISCOVERY.md:1089`) | Decision | Decided by | Date |
|---|---|---|---|---|
| C-1 | oral solid | **UNDECIDED** | | |
| C-2 | oral liquid | **UNDECIDED** | | |
| C-3 | parenteral | **UNDECIDED** | | |
| C-4 | topical | **UNDECIDED** | | |
| C-5 | *"potentially others"* — any further candidate the authority identifies | **UNDECIDED** | | |

---

## 6. Machine-readable form

For load, the package is supplied as **JSON or CSV** matching §2–§4, with this
Markdown as the human-reviewable counterpart. Both must be byte-identical in
meaning; the signed checksum covers whichever files item 20 lists.

Recommended layout:

```
<package_id>/
  package.yaml            # section 1 envelope
  definitions/<code>.yaml # sections 2-3 per definition
  sources.yaml            # section 4 records
  scope_decisions.yaml    # section 5 worksheets
```

Format is an engineering convenience and carries **no** regulatory meaning. The
authority may work entirely in the Markdown; engineering transcribes without
altering content, and the checksum is computed over what was signed.

---

## 7. Completion checklist for the authority

A package is ready for engineering compatibility check when:

- [ ] Every candidate in §5 has a decision of `INCLUDE`, `EXCLUDE` or `DEFER`.
- [ ] Every `INCLUDE`d definition has a complete §2 block.
- [ ] Every section and question has a complete §3 block.
- [ ] Every question has `question_text` authored by the regulatory author.
- [ ] Every question has an `answer_shape_intent`.
- [ ] Every guidance-derived decision cites a §4 source record.
- [ ] Every §4 record is complete and its `approval_status` is set.
- [ ] Reviewer expectations are stated for every question.
- [ ] Every select question carries `{value, label}` options with a non-empty
      approved label for each (`5A-DEC-002`).
- [ ] Every FDA-derived binding names an approved resolver identifier
      (`5A-DEC-001`).
- [ ] Every definition states a `jurisdiction` from the controlled vocabulary
      (`5A-DEC-005`).
- [ ] `prepared_by`, `reviewed_by` and `regulatory_approver` are named, and
      **`prepared_by` differs from `regulatory_approver`** (`5A-DEC-007`).
- [ ] **OQ-8** has a recorded position for any content depending on `iid.*`
      applicability or on a resolved FDA-derived value.

Item 20 is signed **after** compatibility is clean and items 1–19 are resolved —
never before.
