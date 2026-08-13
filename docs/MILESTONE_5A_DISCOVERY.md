# Milestone 5A Discovery — Production Regulatory Checklist Content Approval Readiness

> **Status:** DISCOVERY. **No implementation is authorized by this document.**
> **Gate state:** production regulatory content **0 of 20 approved — OPEN**.
> **Assessed at:** `regx-main` `83051802f52d51e63efc3d542a697eb4871874c2`
> **Predecessor:** Engineering Milestone 4D — COMPLETE (PR #18, PR #19).
> **Companions:** [MILESTONE_5A_REGULATORY_CONTENT_PACKAGE_TEMPLATE.md](MILESTONE_5A_REGULATORY_CONTENT_PACKAGE_TEMPLATE.md),
> [MILESTONE_5A_APPROVAL_REGISTER.md](MILESTONE_5A_APPROVAL_REGISTER.md)

## 0. What this document is, and what it deliberately is not

Milestone 5A turns an unspecific "0 of 20" gate into a **complete, controlled
approval package that a qualified RA/QA authority can actually review and sign**.

It contains **no production regulatory content**. No question text, no
jurisdiction selection, no template selection, no guidance interpretation, no
applicability meaning, no reviewer expectation, and no approval, signature or
date. Anything of that kind written by engineering would be exactly the
"silently invent real regulatory questions" failure the gate exists to prevent
(`MILESTONE_4D_DISCOVERY.md:1089`).

What it does contain: **the questions the authority must answer, the evidence
each answer must carry, the engine constraints every answer must satisfy, and
the process by which the answers become governed application records.**

A useful test for every line below: *could an engineer have written this without
holding IIG guidance interpretation authority?* If no, it is not here.

## 1. Authoritative starting facts

Carried forward unchanged from `MILESTONE_4D_4_CONTENT_APPROVAL.md`:

1. The production-content gate is **OPEN**; **0 of 20** items approved.
2. Engineering must **never** silently invent real regulatory questions.
3. Regulatory content requires **IIG guidance interpretation authority**.
4. **Synthetic** engineering content is allowed and is what every merged test
   suite uses.
5. **Production** content is not allowed until approved.
6. Approved content will later be loaded through the **existing governed
   definition/version/section/question lifecycle** — never a migration, seed or
   fixture (`MILESTONE_4D_4_CONTENT_APPROVAL.md` §6.1).

Item 0 (gate scope, `4D4-DEC-001`, approved 2026-08-11) decided *sequencing*
only and is deliberately not counted among the 20 content items. That remains
true; 5A does not reopen it.

## 2. Milestone 5A operating model

### A. What the regulatory authority must provide

For **each** checklist definition proposed for production:

| Provide | Granularity |
|---|---|
| Template-scope decision (INCLUDE / EXCLUDE / DEFER) with rationale | per candidate template |
| Definition identity, title, jurisdiction, regulatory basis | per definition |
| Source guidance references with version and dates | per definition, and per question where the basis differs |
| Section structure, titles and ordering | per definition |
| Question text, verbatim | per question |
| Required vs optional | per question |
| Applicability intent, expressed in plain regulatory language | per question/section |
| Help/guidance text | per question, optional |
| Reviewer expectations | per question |
| Answer-shape intent (what kind of answer is being asked for) | per question |
| Override intent | per question |
| Export intent | per question |
| Version number and effective date | per definition |
| Formal sign-off | per package |

**Answer-shape intent, not `AnswerType`.** The authority states what is being
asked for ("a percentage the system computes", "a free-text justification", "a
yes/no confirmation by the reviewer"). Engineering maps that to one of the 18
`AnswerType` values and returns the mapping for regulatory confirmation. The
authority is not required to learn the enum, but must confirm the result,
because the mapping changes what a reviewer may enter.

### B. Evidence that must accompany every decision

Every regulatory decision carries a **source-evidence record** (§4 of the
package template): source title, issuing authority, version, publication or
revision date, retrieval date, precise section/page/paragraph reference, official
location, an interpretation statement, author, reviewer and approval status.

A decision with no source reference is acceptable **only** when explicitly marked
`ORGANISATIONAL_POLICY` rather than guidance-derived, and is signed on that
basis. What is not acceptable is a guidance-derived decision with no citation.

### C. Mechanically derivable by engineering *after* regulatory approval

These require **no** regulatory judgement and must not consume the authority's
review time. Each is derived, then shown back for confirmation:

| Derived | From | Mechanism |
|---|---|---|
| `display_order` for sections and questions | approved ordering | sequence numbering |
| Normalized `code` values | approved codes | `codes.normalize_code()` |
| `calculation_dependencies` / recalculation triggers | approved calculation bindings | `CALCULATION_BINDING_REGISTRY` — fixed, not authored |
| Dependency-graph shape, depth, cycle-freedom | approved bindings | `calculation_graph.build_graph()` |
| `evidence_requirement=required` on `EVIDENCE_DERIVED` | classification | `models.py:391` — forced |
| `reviewer_confirmation_required=True` on `REVIEWER_CONFIRMED` | classification | `models.py:398` — forced |
| `condition_json` encoding | approved applicability intent | `applicability.validate_condition_json()` |
| `public_id` values | — | server-generated UUID |

### D. Regulatory ownership (sole)

Items 1–7, 10, 11, 15, 16, 17, 18, 19 of the register. Content, meaning and
intent. Engineering may format and validate; it may not choose.

### E. Joint Regulatory + Engineering confirmation

Items 8, 9, 12, 13. Each has a regulatory intent **and** a mechanical constraint
that can make the intent unimplementable. Neither side can settle these alone:
engineering knows what the engine accepts, regulatory knows what the guidance
requires, and a mismatch must surface as a decision rather than a silent
substitution.

### F. Review, signing and version control of the package

§6 below. In short: the package is version-controlled as repository documents,
reviewed in named stages, and signed at item 20 with a checksum over the exact
approved content files.

### G. When the package is complete enough to hand back to engineering

§7 (gate closure). All 20 resolved, item 20 signed, zero unresolved decisions
for included definitions.

### H. Loading without engineering inventing regulatory meaning

§8 (handoff). Every loaded field traces to a package field; anything absent from
the package is a blocking question back to the authority, never an engineering
default.

## 3. Engine constraints the approved content must satisfy

**Cross-checked against merged code on `regx-main` `8305180`, not only against
docs.** Where a document and the code disagreed, the code is recorded as
authoritative and the discrepancy is called out.

### 3.1 Answer type × source classification

`backend/iig_checklist/compatibility.py:14` — `ALLOWED_MATRIX` is exhaustive and
closed; any pair absent from it is prohibited, enforced in both
`ChecklistQuestion.clean()` (`models.py:362`) and the serializer.

Consequences a content author must know:

- `PERCENTAGE`, `CALCULATED_VALUE`, `CALCULATED_STATUS` → **`SYSTEM_CALCULATED` only.**
  A percentage a human types is not `PERCENTAGE`; it is `DECIMAL`.
- `REVIEWER_CONCLUSION`, `APPROVAL_METADATA` → **`REVIEWER_CONFIRMED` only.**
- `LONG_NARRATIVE` → never `FDA_DERIVED_DEFAULT`.
- `FDA_RECORD_REFERENCE` → `FDA_DERIVED_DEFAULT` or `REVIEWER_CONFIRMED` only.
- `FORMULATION_COMPONENT_REFERENCE` → `USER_REQUIRED` or `REVIEWER_CONFIRMED` only.

### 3.2 Calculations — six, closed

`backend/iig_checklist/calculation_registry.py:218`. The approved binding
identifiers are exactly:

`percentage_w_w`, `daily_exposure`, `percentage_of_iid_potency`,
`difference_from_iid_potency`, `percentage_of_iid_mde`, `difference_from_iid_mde`.

- A `SYSTEM_CALCULATED` question **must** carry one (`models.py:384`), and a
  `calculation_binding_identifier` on any other classification is rejected
  (`models.py:376`).
- **No seventh calculation exists and none may be added to satisfy content**
  (4D-3 `SCOPE-OUT-18`: "Never in 4D"). A regulatory requirement needing one is
  a separate approved engineering scope, not a content decision.

### 3.3 Two reserved question codes

`calculation_registry.py:148-149` defines `Q_SUBJECT_COMPONENT` and
`Q_DAILY_EXPOSURE` as **structural binding points**, and activation validates
that each referenced code exists in the version being activated
(`activation_validation.py:589`).

Therefore, if the approved content uses **any** of the six calculations:

- a question coded exactly `Q_SUBJECT_COMPONENT` must exist, with
  `answer_type = formulation_component_reference` (enforced,
  `activation_validation.py:487`);
- if `percentage_of_iid_mde` or `difference_from_iid_mde` is used, a question
  coded exactly `Q_DAILY_EXPOSURE` must exist, be `SYSTEM_CALCULATED`, be bound
  to `daily_exposure`, and carry the matching output unit — all four checked at
  activation.

These two codes are **reserved engineering identifiers**, not regulatory
question codes. The authority owns their *question text*; it does not own their
*codes*. This must be stated plainly to the authority, because it is the one
place where the engine dictates a code value.

### 3.4 Dependency graph limits

Enforced: `CALCULATION_MAX_DEPENDENCY_DEPTH = 5`,
`CALCULATION_MAX_CASCADE_NODES = 10` (`calculation_registry.py:35-36`), checked at
activation via `calculation_graph.build_graph()`.

**Doc-vs-code note.** `MILESTONE_4D_4_CONTENT_APPROVAL.md` §5.3 states "max
reachable calculated node count from any single question is **3**". Read against
`MILESTONE_4D_3_IMPLEMENTATION_SPEC.md:943-946`, the 3 (and depth 2) describe the
**shape of the approved six-calculation graph**, not the enforced ceiling. Both
statements are true; they are different things. Content cannot exceed the shape
anyway, because it cannot add calculations.

### 3.5 Applicability rules — validated, but not evaluated at runtime

- Allowed rule fields, registry version 1 (`field_registry.py:14`), exactly six:
  `product.route`, `product.dosage_form`, `product.release_type`,
  `iid.match_status`, `iid.has_mde`, `iid.has_potency`.
- Structural limits (`applicability.py:15-17`): recursion depth ≤ 5, ≤ 50 leaf
  conditions, ≤ 8 KiB payload. Operators are a closed set (`applicability.py:19-25`).
- Rules are version-scoped and immutable once approved (`models.py:212`).

**Capability boundary — must be disclosed to the authority.** There is **no
runtime applicability evaluator** in merged code. `applicability.py` validates
and canonicalizes only, and `MILESTONE_4D_4_APP_009_EVIDENCE.md` §6 states it
directly: *"There is no governed applicability writer yet… Nothing in production
writes `is_not_applicable` from a rule today."* An approved applicability rule
will therefore be **stored, validated and exported, but not automatically
applied** until that engine stage is built.

### 3.6 FDA-derived defaults — declared, not populated

`FDA_DERIVED_DEFAULT` is a real classification with real consequences:

- it is **server-controlled** — a client PATCH is refused
  (`services.py:940`, `SERVER_CONTROLLED_CLASSIFICATIONS`);
- it is the **only** overridable classification (`overrides.py:188`), by a holder
  of `PERM_OVERRIDE_EXECUTION` (Reviewer or VP).

**But nothing populates it.** `create_execution()` creates every response with
`raw_value=None` (`services.py:439`), and there is no FDA-derived resolver
module: `answer_sources.py` (required by `MILESTONE_4D_3_IMPLEMENTATION_SPEC.md`
M4D3-SVC-007 and M4D3-POP-001/002) **does not exist**. This was deliberate and
disclosed — `MILESTONE_4D_3_IMPLEMENTATION_EVIDENCE.md:3121-3124` lists it under
"Held out of scope, by instruction", and `answer_sources.py added: NO` at
:3149. `overrides.py:40-42` is written around the same fact.

`prefill_source`, `default_value_binding` and `escalation_rule_identifier`
(`models.py:337-342`) are **inert**: stored, cloned, exposed through the API,
validated against nothing, and read by no engine code.

**Consequence for item 12.** An approved FDA-derived binding is today a
*documented intention*, not an executable one. In the current engine, an
`FDA_DERIVED_DEFAULT` question starts empty and can only be filled through a
governed override. The authority must be told this before approving any such
binding, and engineering must not present the binding fields as if they worked.
Whether to (a) approve bindings now and build the resolver layer as a
prerequisite to load, (b) classify those questions differently, or (c) defer
them, is **Open Question OQ-1** in §9 — a joint decision, not an engineering one.

### 3.7 Overrides

Only `FDA_DERIVED_DEFAULT` is overridable (`overrides.py:188`; §12 of the 4D
discovery). Content **cannot** make a `SYSTEM_CALCULATED`, `USER_REQUIRED`,
`EVIDENCE_DERIVED` or `REVIEWER_CONFIRMED` question overridable, and cannot
remove overridability from an `FDA_DERIVED_DEFAULT` one. Item 17 therefore
records a regulatory *expectation*, and any expectation that contradicts this
floor is a blocking finding, not a configuration.

There is **no clear/withdraw-override path** (APPROVED-DEFERRED, §AC.4). An
override, once recorded, can be amended but not cleared.

### 3.8 Calculated values and `CalculationOutcome`

A `SYSTEM_CALCULATED` response keeps `raw_value` null (M4D3-MDL-006); the result
lives in `CalculationOutcome`, created at execution start with status
`data_required` (`services.py:454-460`). Content must not expect a calculated
answer to be readable as a stored response value, and no status vocabulary
beyond the existing `CalculationStatus` / `MatchStatus` may be introduced.

### 3.9 Codes, identity, and units

- Code grammar (`codes.py:14`): `^[A-Z0-9][A-Z0-9_-]*$`, max 100 chars,
  normalized (trim → whitespace to `_` → uppercase) before storage. An invalid
  character is a hard rejection, never a silent rewrite.
- Question codes are unique **per section**, not per version
  (`models.py:351`) — so the same code may legitimately appear in two sections,
  and every calculation-binding lookup requires exactly one match version-wide
  (`activation_validation.py:14-18`). **Content that reuses a code across
  sections will fail activation if that code is a binding target.**
- Definition codes: unique per platform-master, and per tenant
  (`models.py:81-90`).
- **UUID-only external identity.** `public_id` everywhere client-facing; no
  database IDs are exposed.
- `QUANTITY_WITH_UNIT` questions must declare non-empty `allowed_units` — checked
  at execution creation (`services.py:401`), which means a violation surfaces
  only when someone tries to *run* the checklist. Engineering compatibility
  checking must catch it earlier.
- Select options: there is **no `QuestionOption` model**. Option codes are
  authored into `validation_rule.options` and are the only closed-vocabulary
  mechanism (`response_validation.py:130-142`). **There is no field for an
  option's human-readable label** — see OQ-2.

### 3.10 Export

`EXPORTABLE_EXECUTION_STATUSES = {"approved"}` (`controlled_export.py:96`), and
the export includes **every response of the execution**
(`controlled_export.py:453`), ordered by `question__display_order`, `code`,
`public_id`.

**There is no per-question export inclusion or exclusion mechanism.** Item 18
("export inclusion per question") therefore has no engine support today: a
question in the version is a question in the export, inside the checksum. If the
authority requires an exclusion, that is new engineering scope — see OQ-3.

### 3.11 Authority required to load approved content

- Platform-master definitions require `is_superuser`
  (`permissions.py:130` — `can_author_platform_master()`); **no** tenant role
  (Doer, Reviewer, VP, Tenant Admin, Platform Support) satisfies it.
- Tenant-scoped definitions require `PERM_CREATE_DEFINITION` (Doer).
- Approve and activate require `PERM_APPROVE` / `PERM_ACTIVATE` (**VP only**).
- **Segregation of duties is enforced:** a user cannot approve a version they
  submitted (`views.py:581`).

So loading a platform-master production template needs **at least two distinct
humans** — a superuser to author/submit and a VP to approve/activate. That
staffing requirement is a 5A output, not a load-day surprise.

## 4. The 20-item classification

Full register: [MILESTONE_5A_APPROVAL_REGISTER.md](MILESTONE_5A_APPROVAL_REGISTER.md).

Summary of ownership classes:

| Class | Items | Count |
|---|---|---|
| REGULATORY-AUTHORED | 1, 2, 3, 4, 5, 6, 7, 10, 11, 15, 16 | 11 |
| REGULATORY-APPROVED / ENGINEERING-DERIVED | 14, 19 | 2 |
| JOINT REGULATORY + ENGINEERING | 8, 9, 12, 13, 17, 18 | 6 |
| FORMAL SIGN-OFF | 20 | 1 |

**Existing owner assignments are preserved.** Three are refined, each because
repository evidence shows the current label is inconsistent with the engine, and
each refinement is recorded with its reason in the register (items 17, 18, 19).
No owner was silently rewritten.

## 5. Engineering compatibility boundary

The single most important separation in this milestone.

### Engineering MAY check, before regulatory approval

Purely mechanical, decidable without reading a guidance document:

1. `answer_type` is one of the 18 enum values.
2. `data_source_classification` is one of the 5 enum values.
3. The (`answer_type`, `classification`) pair is in `ALLOWED_MATRIX`.
4. `calculation_binding_identifier` is one of the six registry identifiers.
5. `SYSTEM_CALCULATED` ⟺ a binding identifier is present.
6. Reserved codes `Q_SUBJECT_COMPONENT` / `Q_DAILY_EXPOSURE` exist with the
   required answer type and classification when a calculation is used.
7. Dependency graph: no cycle, depth ≤ 5, reachable nodes ≤ 10.
8. Question codes: grammar, length ≤ 100, uniqueness per section, and
   version-wide uniqueness for any code used as a binding target.
9. Section/question `display_order` uniqueness and completeness.
10. `allowed_units` non-empty for every `QUANTITY_WITH_UNIT` question.
11. Applicability `condition_json`: field names in registry version 1, operator
    validity, depth ≤ 5, ≤ 50 leaves, ≤ 8 KiB.
12. `EVIDENCE_DERIVED` ⟹ `evidence_requirement = required`;
    `REVIEWER_CONFIRMED` ⟹ `reviewer_confirmation_required = true`.
13. Field lengths: title ≤ 255, `regulatory_basis` ≤ 500,
    `regulatory_reference` ≤ 500, code ≤ 100.
14. All required package fields present; schema well-formed.
15. Every source-evidence record structurally complete (fields present — **not**
    whether the citation is correct).

The result is a **findings list**, never an edit.

### Engineering MUST NOT

1. Write, rewrite, shorten, clarify or "improve" question text.
2. Choose or amend regulatory basis, jurisdiction or citations.
3. Interpret guidance, or resolve an ambiguity in it.
4. Decide what an applicability rule *should mean* — only encode an approved meaning.
5. Approve or author reviewer expectations.
6. Add a calculation, resolver, field, status value or answer type because
   content needs one.
7. Loosen, waive or reinterpret a regulatory requirement to make content load.
8. Choose which templates ship.
9. Substitute an `AnswerType` for a rejected one without regulatory
   re-confirmation — the substitution changes what a reviewer may answer.
10. Fill a package gap with a default.

**Escalation rule.** A compatibility failure returns to Regulatory with the
constraint stated in plain language and the options available. Engineering
proposes; regulatory decides. Engineering never resolves a failure by editing
regulatory meaning.

## 6. Approval workflow

### 6.1 Should this live in the application?

**No — and this is a deliberate finding, not an omission.**

The application's `ChecklistVersion` lifecycle (draft → under_review →
returned/approved → active, with distinct actor columns and enforced segregation
at `views.py:581`) is a genuinely good governance engine. It cannot be used for
*package* approval for one decisive reason: **using it requires first creating
the production content as application records, which is precisely what the gate
forbids** until item 20 is signed.

Building a second workflow engine for documents would also be disproportionate.
The smallest controlled process is therefore:

> **Package approval is a document-level control in version control.
> The application lifecycle governs *loading*, after the gate closes.**

### 6.2 Stages

| Stage | Owner | Entry condition | Exit condition |
|---|---|---|---|
| **DRAFT** | Regulatory | 5A template issued | All required fields populated for candidate definitions |
| **ENGINEERING COMPATIBILITY CHECK** | Engineering | Draft submitted | Findings list returned; no edits made |
| **RETURNED** | Regulatory | Any blocking finding | Findings resolved by Regulatory |
| **REGULATORY REVIEW** | Regulatory reviewer (≠ author) | Compatibility clean | Reviewed, comments resolved |
| **REGULATORY APPROVED** | Regulatory authority | Review complete | Every item 1–19 resolved |
| **FORMALLY SIGNED** | Regulatory authority | Items 1–19 resolved | Item 20 complete, checksum recorded |
| **READY FOR ENGINEERING LOAD** | Joint | Item 20 signed | Handoff package accepted (§8) |

The compatibility check sits **before** regulatory review deliberately: it is
cheap, mechanical, and prevents the authority spending review time on content
that cannot load.

Author ≠ reviewer mirrors the segregation the application already enforces. If
one person holds both roles, the package must record that explicitly rather than
imply two-person review.

### 6.3 Version control

Package files live in `docs/`, so every change is a reviewable commit with an
author, timestamp and diff. The approved package version is the **git commit
SHA** of the signed content files plus a content checksum (§7.2). No separate
document-management system is introduced.

## 7. Gate closure

### 7.1 Closure criterion

**Milestone 5A is COMPLETE only when all 20 items are resolved AND item 20
contains a valid formal sign-off by the identified regulatory authority.**

Until then, the status is exactly:

> **5A = BLOCKED ON REGULATORY APPROVAL.**

Explicitly insufficient for closure: that these documents exist; that the
template is complete; that engineering compatibility passes; that a draft is
circulating. **Documents existing is not approval.** Engineering implementation
of approved content begins only after closure.

### 7.2 What item 20 must contain

| Element | Requirement |
|---|---|
| Approver full name | Named individual, not a role or team |
| Organizational role | The role held at signing |
| Authority statement | Explicit assertion of IIG guidance interpretation authority |
| Approval date | Actual date of signing |
| Approved package version | Git commit SHA of the signed content files |
| Package checksum | SHA-256 over the exact approved content file bytes |
| Included definitions | Explicit list; anything not listed is not approved |
| Source-reference inventory | Every citation relied upon |
| Review confirmation | That questions, applicability and reviewer expectations were each reviewed |
| Non-authorship confirmation | That engineering authored no regulatory meaning |
| Signature mechanism | See §7.3 |

### 7.3 Signature mechanism — no compliance claim

**No 21 CFR Part 11-compliant electronic signature system exists in this
repository.** Every prior milestone states this (`ROADMAP.md`, Milestones 2, 3,
4A–4C; `MILESTONE_4D_CLOSEOUT_STATUS.md` §6), and 5A introduces none.
Documents 2, 3 and 4 of this milestone must not imply otherwise.

**Interim controlled-signature evidence** — acceptable, and honestly labelled:

1. A signed commit, or a commit authored by the approver's own account, adding
   the completed item 20 to `MILESTONE_5A_APPROVAL_REGISTER.md`; **or**
2. A countersigned PDF/scan stored as a controlled document, referenced by
   checksum from the register; **or**
3. A written approval from the approver's verified organizational email,
   archived and referenced by checksum.

Each carries: approver identity, date, the exact package checksum, and an
explicit statement of what is being approved.

**Required label on any of these:** *"Interim controlled signature. This is not a
21 CFR Part 11 validated electronic signature; no Part 11 compliance is claimed."*

If the organization requires Part 11, that is a **separate validated-system
milestone** and a prerequisite to any Part 11 claim — it is not satisfiable by
5A and must not be represented as such.

## 8. 5A → engineering handoff

### 8.1 What engineering receives

1. Approved checklist-definition inventory (explicit list).
2. Approved content file(s) in the package schema.
3. Source-reference inventory.
4. Decision log for all 20 items.
5. Approval/signature evidence per §7.2–7.3.
6. Package version (commit SHA) and checksum.
7. Compatibility-validation result — clean.
8. **Unresolved or deferred decisions: NONE for included definitions.** A
   definition with any open decision is EXCLUDED or DEFERRED, never loaded
   partially.

### 8.2 Future engineering tasks — *not performed in this branch*

1. Create governed draft `ChecklistDefinition` / `ChecklistVersion` records
   through the existing 4D-1 path.
2. Create approved sections and questions exactly as specified — no additions,
   no omissions, no rewording.
3. Bind approved resolver and calculation identifiers from the registry.
4. Validate the dependency graph.
5. Submit through the existing review → approve → activate governance, honouring
   segregation of duties and the superuser requirement for platform-master scope.
6. Verify activated content matches the approved package byte-for-byte on every
   content field, and record the comparison.
7. Generate controlled implementation evidence.

Any prerequisite engine work identified by OQ-1/OQ-3 must complete **before**
step 1 for the affected questions.

## 9. Open questions requiring an owner decision

None is engineering's to settle.

| ID | Question | Why it cannot be decided by engineering | Owner |
|---|---|---|---|
| **OQ-1** | FDA-derived defaults are declared but never populated (§3.6). Approve bindings now and build the resolver layer as a load prerequisite; classify those questions differently; or defer them? | Changes who supplies a regulated answer and how it is evidenced | Regulatory + Eng lead |
| **OQ-2** | Select options have codes but **no label field** (§3.9). Display raw codes to reviewers; encode labels in question text; or add a labelling mechanism (new engineering scope)? | What a reviewer sees when choosing an answer is regulatory-facing | Regulatory + Eng lead |
| **OQ-3** | No per-question export inclusion/exclusion exists (§3.10). Accept that every question is exported inside the checksum, or fund an exclusion mechanism? | Export content is a regulatory artifact decision | Regulatory |
| **OQ-4** | Applicability rules are stored and validated but not evaluated (§3.5). Approve rules now as documented intent, or defer applicability entirely until the evaluator exists? | Determines whether a "not applicable" outcome is system- or human-determined | Regulatory + Eng lead |
| **OQ-5** | Jurisdiction has **no model field** (item 3). Record it in `regulatory_basis`, in the definition `description`, or add a field? | Where a regulatory attribute is recorded affects export and review | Regulatory + Eng lead |
| **OQ-6** | Will production templates be `platform_master` (superuser authoring, shared) or `tenant`-scoped (per-client)? | Determines who may load content and who may vary it | Project owner + Regulatory |
| **OQ-7** | Is the same person permitted to author and review the package (§6.2)? | A single-person package must be labelled as such, not implied to be two-person reviewed | Project owner |

## 10. Production-readiness boundary

**Milestone 5A does NOT mean any of the following:**

- real FDA data ingestion is complete;
- real client formulation onboarding is complete;
- regulatory template migration is complete;
- infrastructure is production-ready;
- 21 CFR Part 11 is validated or claimed;
- system go-live is approved.

**5A is exactly:** *production regulatory checklist content approval readiness,
plus the human approval gate.*

Those other concerns belong to later milestones (5B–5D). This document
deliberately records **no** detailed 5B/5C/5D requirements; naming boundaries is
useful, inventing their scope is not. Each needs its own discovery.

## 11. Document set and why it is shaped this way

`MILESTONE_4D_4_CONTENT_APPROVAL.md` is correct but is a **4D-4-scoped gate
statement**: it names what must be decided, not how it gets decided, evidenced or
signed. It is 146 lines and cannot function as a working approval package.

Rather than duplicate it, 5A **keeps it as the origin of the gate** — it holds
`4D4-DEC-001` and the original item enumeration — and adds:

| File | Role |
|---|---|
| `MILESTONE_5A_DISCOVERY.md` | This document: operating model, engine constraints, workflow, boundaries |
| `MILESTONE_5A_REGULATORY_CONTENT_PACKAGE_TEMPLATE.md` | The controlled schema the authority fills in, the source-evidence model, and the template-scope worksheet |
| `MILESTONE_5A_APPROVAL_REGISTER.md` | The working 20-item register: ownership, evidence, validation, completion criteria |

The 4D-4 document gains a forward pointer and nothing else. The item table is
**not** duplicated: the 5A register is the working copy.
