# Milestone 5A — Production Regulatory Content Approval Register

> **Status:** OPEN — **0 of 20 approved.** No item below is approved.
> **Supersedes the operational role of** `MILESTONE_4D_4_CONTENT_APPROVAL.md` §4;
> that document remains the origin of the gate and holds `4D4-DEC-001`.
> **Companions:** [MILESTONE_5A_DISCOVERY.md](MILESTONE_5A_DISCOVERY.md),
> [MILESTONE_5A_REGULATORY_CONTENT_PACKAGE_TEMPLATE.md](MILESTONE_5A_REGULATORY_CONTENT_PACKAGE_TEMPLATE.md)
> **Engine facts verified against** `regx-main` `8305180` **code, not only docs.**

> ### ▶ Milestone 5A-P1 closed the three capability limits
>
> Items 11, 12 and 18 were marked **capability-limited**: they asked the
> authority to approve content against mechanisms that did not exist. 5A-P1
> built them, so the disclosures below are **resolved**.
>
> - **Item 11** — applicability rules are now actually evaluated (`5A-DEC-004`).
> - **Item 12** — FDA-derived bindings now resolve through a governed allow-list
>   with provenance and explicit failure (`5A-DEC-001`).
> - **Item 18** — no exclusion mechanism is needed: `5A-DEC-003` decided full
>   governed inclusion for the first production release.
>
> Two further decisions bear on this register: `5A-DEC-005` gives jurisdiction
> (item 3) a structured governed home, and `5A-DEC-006` settles item 1's scope
> question — official templates are platform-master content.
>
> **One new constraint applies to items 11 and 12** and must be read before
> approving either: `MILESTONE_5A_DISCOVERY.md` **OQ-8**. Which
> `AssessmentSnapshot` governs execution-level `iid.*` values is not settled by
> any approved specification, so a rule reading `iid.*` currently evaluates to
> `review_required`, and an FDA-derived binding records `source_unavailable`.
> Both are visible and neither fabricates a value — but content depending on
> `iid.*` should not be approved as *automatic* until OQ-8 is answered.
>
> **The approval count is unchanged: 0 of 20.** Engineering prerequisites are
> not regulatory approvals.

## 1. Reading this register

Four ownership classes:

| Class | Meaning |
|---|---|
| **REGULATORY-AUTHORED** | Regulatory writes it. Engineering may format and validate; never choose. |
| **REGULATORY-APPROVED / ENGINEERING-DERIVED** | Engineering derives it mechanically from approved input; Regulatory confirms. |
| **JOINT REGULATORY + ENGINEERING** | Regulatory intent plus a mechanical constraint that can make the intent unimplementable. Neither side can settle it alone. |
| **FORMAL SIGN-OFF** | The signature that closes the gate. |

**"Interpretation risk"** answers one question: *if this decision is wrong, does
the regulatory meaning of the checklist change?* `HIGH` items are where a
mistake alters what the system asks or asserts about a product.

**Owner changes from the 4D-4 table are marked ⚠ and justified.** Nothing was
rewritten silently.

## 2. Register

### Item 1 — Which `ChecklistDefinition` templates ship

| | |
|---|---|
| **Class** | REGULATORY-AUTHORED |
| **Decision needed** | Which production checklist templates exist at all |
| **Owner** | Regulatory (unchanged) |
| **Evidence required** | Scope-decision worksheet per candidate (template §5), source guidance per candidate |
| **Citation required?** | **Yes** |
| **Engineering dependency** | None — this is the first gate; everything else depends on it |
| **Validation rule** | Every candidate resolved `INCLUDE`/`EXCLUDE`/`DEFER`; ≥ 1 `INCLUDE` for the gate to produce loadable content |
| **Completion criterion** | Worksheet complete and signed for every candidate |
| **Downstream model/field** | `ChecklistDefinition` (row existence) |
| **Interpretation risk** | **HIGH** — the wrong set means the wrong products are assessed |
| **Status** | **PENDING** |

Candidates named at `MILESTONE_4D_DISCOVERY.md:1089` — oral solid, oral liquid,
parenteral, topical, "potentially others" — are **candidates only**. Engineering
has selected nothing.

`5A-DEC-006` settles the *scope type* but not the *set*: whatever templates are
included are **platform-master** governed content that tenants consume, never
duplicated per tenant. Which templates ship remains entirely regulatory.

### Item 2 — Checklist title per definition

| | |
|---|---|
| **Class** | REGULATORY-AUTHORED |
| **Owner** | Regulatory (unchanged) |
| **Evidence required** | None beyond the definition's own scope decision |
| **Citation required?** | No |
| **Engineering dependency** | ≤ 255 chars (`models.py:57`) |
| **Validation rule** | Non-blank, ≤ 255 chars |
| **Completion criterion** | Title present for every `INCLUDE`d definition |
| **Downstream** | `ChecklistDefinition.title` |
| **Interpretation risk** | LOW |
| **Status** | **PENDING** |

### Item 3 — Jurisdiction

| | |
|---|---|
| **Class** | REGULATORY-AUTHORED |
| **Owner** | Regulatory (unchanged) |
| **Evidence required** | Statement of jurisdiction and its basis |
| **Citation required?** | **Yes** |
| **Engineering dependency** | ✅ `ChecklistVersion.jurisdiction`, controlled vocabulary, lifecycle-frozen, checksum-covered (`5A-DEC-005`). Vocabulary is `US_FDA` only; another jurisdiction requires a governed decision, not a code change |
| **Validation rule** | Stated explicitly per definition; never inferred |
| **Completion criterion** | Jurisdiction stated per definition (storage settled by `5A-DEC-005`) |
| **Downstream** | `ChecklistVersion.jurisdiction` |
| **Interpretation risk** | **HIGH** — the wrong jurisdiction invalidates every question under it |
| **Status** | **PENDING** |

The 4D-4 table notes "US FDA assumed but unstated". **That assumption is not
carried forward as a decision.** It remains unstated and must be decided.

### Item 4 — Regulatory basis

| | |
|---|---|
| **Class** | REGULATORY-AUTHORED |
| **Owner** | Regulatory (unchanged) |
| **Evidence required** | §4 source records |
| **Citation required?** | **Yes** |
| **Engineering dependency** | ≤ 500 chars (`models.py:110`) |
| **Validation rule** | Non-blank for production content; ≤ 500 chars |
| **Completion criterion** | Basis stated and cited per definition |
| **Downstream** | `ChecklistVersion.regulatory_basis` |
| **Interpretation risk** | **HIGH** |
| **Status** | **PENDING** |

Field exists and is blank-able at model level, so **the engine will not enforce
this**; it is a package-level requirement.

### Item 5 — Source guidance, version, publication date

| | |
|---|---|
| **Class** | REGULATORY-AUTHORED |
| **Owner** | Regulatory (unchanged) |
| **Evidence required** | Complete §4 record per source |
| **Citation required?** | **Yes — this item *is* the citation requirement** |
| **Engineering dependency** | Reproducibility (§18): content answerable without re-querying live data |
| **Validation rule** | Every §4 field present; `reference_locator` precise, not document-level |
| **Completion criterion** | Source inventory complete; every guidance-derived decision references one |
| **Downstream** | Package evidence; `ChecklistQuestion.regulatory_reference` where per-question |
| **Interpretation risk** | **HIGH** — an uncitable decision cannot be defended in audit |
| **Status** | **PENDING** |

### Item 6 — Section structure and ordering

| | |
|---|---|
| **Class** | REGULATORY-AUTHORED |
| **Owner** | Regulatory (unchanged) |
| **Evidence required** | Rationale where structure follows a guidance structure |
| **Citation required?** | Where guidance-derived |
| **Engineering dependency** | Section code unique per version; `display_order` unique per version (`models.py:290-295`) |
| **Validation rule** | Codes match grammar; order values unique and complete |
| **Completion criterion** | Every section titled, coded, ordered, with criticality |
| **Downstream** | `ChecklistSection.*` |
| **Interpretation risk** | MEDIUM — ordering affects reviewer flow and export order |
| **Status** | **PENDING** |

### Item 7 — Question text (verbatim)

| | |
|---|---|
| **Class** | REGULATORY-AUTHORED |
| **Owner** | Regulatory (unchanged) |
| **Evidence required** | §4 source record per question, or declared organizational policy |
| **Citation required?** | **Yes** |
| **Engineering dependency** | `TextField`, no length cap (`models.py:319`) |
| **Validation rule** | Non-blank. **Engineering performs no wording check of any kind.** |
| **Completion criterion** | Every question has text authored by the regulatory author |
| **Downstream** | `ChecklistQuestion.question_text` |
| **Interpretation risk** | **HIGH — the highest in the register** |
| **Status** | **PENDING** |

**Engineering must not draft, reword, shorten, clarify or "improve" any question
text.** This is the specific failure `MILESTONE_4D_DISCOVERY.md:1089` exists to
prevent.

### Item 8 — Question codes / public identifiers

| | |
|---|---|
| **Class** | JOINT REGULATORY + ENGINEERING |
| **Owner** | Regulatory + Engineering (unchanged) |
| **Evidence required** | Coding convention statement |
| **Citation required?** | No |
| **Engineering dependency** | Grammar `^[A-Z0-9][A-Z0-9_-]*$`, ≤ 100 chars, normalized (`codes.py:12-14`); unique **per section** (`models.py:351`); **version-wide unique if used as a calculation binding target** (`activation_validation.py:14-18`) |
| **Validation rule** | Grammar + length + uniqueness; reserved codes honoured |
| **Completion criterion** | Every question coded; no collision; reserved codes present where required |
| **Downstream** | `ChecklistQuestion.code`; external identity remains UUID `public_id` |
| **Interpretation risk** | MEDIUM — codes are regulatory-facing in exports |
| **Status** | **PENDING** |

**Two codes are engineering-reserved**, not regulatory choices:
`Q_SUBJECT_COMPONENT` and `Q_DAILY_EXPOSURE` (`calculation_registry.py:148-149`),
required whenever a calculation is bound. Their **text** is regulatory; their
**codes** are fixed.

### Item 9 — Answer type per question

| | |
|---|---|
| **Class** | JOINT REGULATORY + ENGINEERING |
| **Owner** | Regulatory + Engineering (unchanged) |
| **Evidence required** | `answer_shape_intent` in plain language from Regulatory; mapping rationale from Engineering; **Regulatory confirmation of the mapping** |
| **Citation required?** | No |
| **Engineering dependency** | 18 values (`enums.py:58`); `ALLOWED_MATRIX` closed (`compatibility.py:14`); enforced in `models.py:362` |
| **Validation rule** | Pair present in `ALLOWED_MATRIX`; `quantity_with_unit` ⟹ non-empty `allowed_units` (`services.py:401`) |
| **Completion criterion** | Every question mapped **and the mapping confirmed by Regulatory** |
| **Downstream** | `ChecklistQuestion.answer_type` |
| **Interpretation risk** | **HIGH** — the answer type determines what a reviewer may record |
| **Status** | **PENDING** |

Engineering may propose a mapping; it may **not** substitute a different type
for a rejected one without regulatory re-confirmation.

### Item 10 — Required vs optional

| | |
|---|---|
| **Class** | REGULATORY-AUTHORED |
| **Owner** | Regulatory (unchanged) |
| **Evidence required** | Rationale where a guidance expectation is mandatory |
| **Citation required?** | Where guidance-derived |
| **Engineering dependency** | `required` boolean, default `False` (`models.py:329`); drives completeness gating |
| **Validation rule** | Explicit per question — never defaulted by engineering |
| **Completion criterion** | Every question has an explicit value |
| **Downstream** | `ChecklistQuestion.required` |
| **Interpretation risk** | **HIGH** — a wrongly-optional question lets an execution be approved without it |
| **Status** | **PENDING** |

### Item 11 — Applicability rules

| | |
|---|---|
| **Class** | REGULATORY-AUTHORED (intent); engineering encodes |
| **Owner** | Regulatory (unchanged) |
| **Evidence required** | Plain-language applicability intent + §4 citation |
| **Citation required?** | **Yes** |
| **Engineering dependency** | Only six rule fields exist (`field_registry.py:14`); depth ≤ 5, ≤ 50 leaves, ≤ 8 KiB (`applicability.py:15-17`); rules immutable once approved (`models.py:212`) |
| **Validation rule** | `validate_condition_json()` passes against registry version 1 |
| **Completion criterion** | Intent stated, encodable within the six fields, **and OQ-4 resolved** |
| **Downstream** | `ApplicabilityRule`, `ChecklistSection.applicability_rule`, `ChecklistQuestion.applicability_rule` |
| **Interpretation risk** | **HIGH** — applicability decides whether a question must be answered at all |
| **Status** | **PENDING** — capability limit resolved by `5A-DEC-004` |

✅ **Resolved by 5A-P1.** A deterministic runtime evaluator now exists, and an
approved rule is evaluated and persisted at execution creation. Superseded
disclosure, retained for history: there was **no runtime applicability
evaluator**; `applicability.py` validates and canonicalizes only, and
`MILESTONE_4D_4_APP_009_EVIDENCE.md` §6 states that nothing in production writes
`is_not_applicable` from a rule. An approved rule will be stored, validated and
exported but **not automatically applied**. That is no longer true.

⚠ **Still read OQ-8 before approving a rule that reads `iid.*`:** those three
fields evaluate to `review_required` today, because which component snapshot
governs an execution-level rule is not specified. Rules over `product.*`
evaluate fully.

An intent that cannot be expressed with the six available fields is a **blocking
finding returned to Regulatory** — never approximated by engineering.

### Item 12 — `FDA_DERIVED_DEFAULT` bindings

| | |
|---|---|
| **Class** | JOINT REGULATORY + ENGINEERING |
| **Owner** | Regulatory + Engineering (unchanged) |
| **Evidence required** | Which FDA field feeds which question, and why that field is the correct source |
| **Citation required?** | **Yes** |
| **Engineering dependency** | ✅ Governed allow-list resolver layer (`5A-DEC-001`): `answer_sources.py`, provenance on the response, explicit failure statuses |
| **Validation rule** | Classification and answer-type pair allowed; **the binding identifier is validated against the approved registry at authoring time** and refused again at resolution |
| **Completion criterion** | Binding stated and naming an approved resolver identifier |
| **Downstream** | `ChecklistQuestion.prefill_source` (governed resolver identifier); `ChecklistResponse.source_provenance`. `default_value_binding` remains reserved and unused |
| **Interpretation risk** | **HIGH** — a wrong source field puts a wrong regulated value in front of a reviewer |
| **Status** | **PENDING** — capability limit resolved by `5A-DEC-001` |

✅ **Resolved by 5A-P1.** Superseded disclosure, retained for history: `answer_sources.py`
(`MILESTONE_4D_3_IMPLEMENTATION_SPEC.md` M4D3-SVC-007, M4D3-POP-001/002) **does
not exist**; it was held out of scope by instruction and disclosed at
`MILESTONE_4D_3_IMPLEMENTATION_EVIDENCE.md:3121-3124` and :3149.
`create_execution()` creates every response with `raw_value=None`
(`services.py:439`). `prefill_source`, `default_value_binding` and
`escalation_rule_identifier` are stored, cloned and API-exposed but **validated
against nothing and read by no engine code**.

In the current engine an `FDA_DERIVED_DEFAULT` question **starts empty**, is not
client-writable (`services.py:940`), and can only be filled through a governed
override by a Reviewer or VP. That is no longer true: a bound question now
resolves through the governed registry and records provenance either way.

⚠ **Still read OQ-8 before approving a binding:** no governed rule yet selects
*which* IID precedent record answers a given question, so a binding resolves to
an explicit `source_unavailable` record rather than a value. Nothing is
fabricated, and the failure is visible in the API and the export.

### Item 13 — `SYSTEM_CALCULATED` bindings

| | |
|---|---|
| **Class** | JOINT REGULATORY + ENGINEERING |
| **Owner** | Regulatory + Engineering (unchanged) |
| **Evidence required** | Which calculation applies to which question, and the regulatory reason |
| **Citation required?** | **Yes** |
| **Engineering dependency** | **Exactly six** identifiers (`calculation_registry.py:218`); binding required for `system_calculated` and forbidden otherwise (`models.py:376-384`); reserved codes per §3.3 of the discovery |
| **Validation rule** | Identifier ∈ the six; answer type and classification match the registry entry; activation validation passes (`activation_validation.py:589`) |
| **Completion criterion** | Every calculated question bound to an approved identifier |
| **Downstream** | `ChecklistQuestion.calculation_binding_identifier`; `CalculationOutcome` |
| **Interpretation risk** | **HIGH** — the wrong calculation produces a wrong regulated number |
| **Status** | **PENDING** |

**A seventh calculation cannot be added to satisfy content** (4D-3
`SCOPE-OUT-18`: "Never in 4D"). A requirement needing one is separate approved
engineering scope.

### Item 14 — Calculation dependencies / ordering

| | |
|---|---|
| **Class** | REGULATORY-APPROVED / ENGINEERING-DERIVED |
| **Owner** | Engineering, derived from items 12–13 (unchanged) |
| **Evidence required** | Derivation output; graph validation result |
| **Citation required?** | No |
| **Engineering dependency** | Dependencies are **registry-fixed**, not authored; depth ≤ 5, nodes ≤ 10 (`calculation_registry.py:35-36`) |
| **Validation rule** | `build_graph()` reports no cycle, no depth or node-limit breach, no unknown dependency code |
| **Completion criterion** | Graph validates for every `INCLUDE`d definition |
| **Downstream** | `CalculationOutcome` ordering; cascade behaviour |
| **Interpretation risk** | LOW — derived, not authored |
| **Status** | **PENDING** (blocked on 12–13) |

Note: the "max reachable node count 3" in `MILESTONE_4D_4_CONTENT_APPROVAL.md`
§5.3 describes the **approved six-calculation graph shape**
(`MILESTONE_4D_3_IMPLEMENTATION_SPEC.md:943-946`), not the enforced ceiling of
5 / 10. Both are true; they are different measurements.

### Item 15 — Help / guidance text

| | |
|---|---|
| **Class** | REGULATORY-AUTHORED |
| **Owner** | Regulatory (unchanged) |
| **Evidence required** | §4 record where the text paraphrases guidance |
| **Citation required?** | Where guidance-derived |
| **Engineering dependency** | `TextField`, blank allowed (`models.py:320`) |
| **Validation rule** | None mechanical |
| **Completion criterion** | Present or explicitly declared not required, per question |
| **Downstream** | `ChecklistQuestion.help_text` |
| **Interpretation risk** | **HIGH** — help text steers how a reviewer answers |
| **Status** | **PENDING** |

### Item 16 — Reviewer expectations per question

| | |
|---|---|
| **Class** | REGULATORY-AUTHORED |
| **Owner** | Regulatory (unchanged) |
| **Evidence required** | Statement of what the reviewer must satisfy themselves of |
| **Citation required?** | Where guidance-derived |
| **Engineering dependency** | ⚠ **No dedicated model field.** Nearest are `help_text` and `regulatory_reference`; `reviewer_confirmation_required` is a boolean only |
| **Validation rule** | `reviewer_confirmed` ⟹ `reviewer_confirmation_required = true` (forced, `models.py:398`) |
| **Completion criterion** | Expectation stated per question **and its storage location agreed** |
| **Downstream** | Undecided field; `ChecklistQuestion.reviewer_confirmation_required` |
| **Interpretation risk** | **HIGH** — this defines the review standard |
| **Status** | **PENDING** |

Engineering must **not** silently merge reviewer expectations into `help_text`.

### Item 17 — Override eligibility per question

| | |
|---|---|
| **Class** | ⚠ **JOINT REGULATORY + ENGINEERING** (4D-4 table: "Regulatory") |
| **Owner** | Regulatory expectation, within a fixed engineering floor |
| **Evidence required** | Expectation statement per question |
| **Citation required?** | Where guidance-derived |
| **Engineering dependency** | **Only `fda_derived_default` is overridable** (`overrides.py:188`); permission `PERM_OVERRIDE_EXECUTION` — Reviewer and VP, never Doer (`permissions.py`); **no clear-override path** (APPROVED-DEFERRED) |
| **Validation rule** | Any expectation contradicting the floor is a **blocking finding**, not a configuration |
| **Completion criterion** | Expectation recorded and confirmed consistent with the floor |
| **Downstream** | Governed by classification — **not a per-question stored field** |
| **Interpretation risk** | MEDIUM |
| **Status** | **PENDING** |

⚠ **Reclassification justified.** The 4D-4 table assigns this to Regulatory
alone, while its own evidence column states "Engineering floor is fixed".
Overridability is **derived from classification and not separately
configurable**, so a purely regulatory decision here can be unimplementable.
Recording it as joint makes the existing constraint visible at decision time
rather than at load time. The regulatory *expectation* remains regulatory-owned.

### Item 18 — Export inclusion per question

| | |
|---|---|
| **Class** | ⚠ **JOINT REGULATORY + ENGINEERING** (4D-4 table: "Regulatory") |
| **Owner** | Regulatory intent; engineering feasibility |
| **Evidence required** | Any exclusion requirement and its rationale |
| **Citation required?** | Where guidance-derived |
| **Engineering dependency** | ⚠ **No inclusion/exclusion mechanism exists.** Export covers **every** response of an approved execution (`controlled_export.py:453`), inside the SHA-256 checksum; only `approved` executions are exportable (`controlled_export.py:96`) |
| **Validation rule** | `5A-DEC-003` decided full governed inclusion for the first production release. An exclusion request is deferred to a later governed change, not a 5A blocker |
| **Completion criterion** | Confirm that full governed inclusion is acceptable (`5A-DEC-003`) |
| **Downstream** | `controlled_export` payload and checksum |
| **Interpretation risk** | MEDIUM |
| **Status** | **PENDING** — settled by `5A-DEC-003`; confirmation only |

⚠ **Reclassification justified.** The 4D-4 table asks "Any exclusions?" of
Regulatory alone. Because no mechanism exists, an unqualified regulatory
"exclude X" is not implementable and would otherwise surface only at load. Joint
classification surfaces it at decision time. The *requirement* remains
regulatory-owned.

### Item 19 — Version number and effective date

| | |
|---|---|
| **Class** | ⚠ **REGULATORY-APPROVED / ENGINEERING-DERIVED** (4D-4 table: "Regulatory") |
| **Owner** | Regulatory sets effective date; version number is allocated by the engine and confirmed |
| **Evidence required** | Effective-date rationale |
| **Citation required?** | Where guidance-derived |
| **Engineering dependency** | `version_number` unique per definition (`models.py:157`), allocated by the governed creation path; `effective_date` / `expiry_date` are nullable dates (`models.py:108-109`) |
| **Validation rule** | Version numbering follows the governed sequence; effective date consistent with the approval date |
| **Completion criterion** | Effective date approved; version number confirmed after allocation |
| **Downstream** | `ChecklistVersion.version_number`, `.effective_date`, `.expiry_date` |
| **Interpretation risk** | MEDIUM — effective date determines which version governs an assessment |
| **Status** | **PENDING** |

⚠ **Reclassification justified — partial only.** The **effective date remains a
regulatory decision** and is unchanged. The **version number** is allocated by
the governed lifecycle under a uniqueness constraint and cannot be freely chosen;
recording it as engineering-derived-with-confirmation reflects the code.

### Item 20 — Formal sign-off

| | |
|---|---|
| **Class** | FORMAL SIGN-OFF |
| **Owner** | Regulatory authority holding IIG guidance interpretation authority (unchanged) |
| **Evidence required** | All elements in the table below |
| **Citation required?** | Source-reference inventory for the whole package |
| **Engineering dependency** | Engineering supplies commit SHA, checksum and the compatibility result — **and signs nothing** |
| **Validation rule** | Every element present; checksum matches the signed files |
| **Completion criterion** | **This item closes the gate** |
| **Downstream** | Authorizes the load described in `MILESTONE_5A_DISCOVERY.md` §8 |
| **Interpretation risk** | **HIGH** |
| **Status** | **PENDING** |

| Required element | Present? |
|---|---|
| Author full name and role (individual) | ☐ |
| **Regulatory approver full name and role — must differ from the author (`5A-DEC-007`)** | ☐ |
| Organizational role | ☐ |
| Authority statement (IIG guidance interpretation authority) | ☐ |
| Approval date | ☐ |
| Approved package version (commit SHA) | ☐ |
| Package checksum (SHA-256 over signed file bytes) | ☐ |
| List of checklist definitions included | ☐ |
| Source-reference inventory | ☐ |
| Confirmation that questions, applicability and reviewer expectations were reviewed | ☐ |
| Confirmation that engineering authored no regulatory meaning | ☐ |
| Confirmation that the author and the regulatory approver are different people (`5A-DEC-007`) | ☐ |
| Confirmation that engineering compatibility review was **not** treated as regulatory approval | ☐ |
| Signature evidence per `MILESTONE_5A_DISCOVERY.md` §7.3 | ☐ |

**Signature mechanism — required label.** No 21 CFR Part 11 validated electronic
signature system exists in this repository, and 5A introduces none. Whichever
interim mechanism is used must carry: *"Interim controlled signature. This is not
a 21 CFR Part 11 validated electronic signature; no Part 11 compliance is
claimed."*

## 3. Summary

| Class | Items | Count |
|---|---|---|
| REGULATORY-AUTHORED | 1, 2, 3, 4, 5, 6, 7, 10, 11, 15, 16 | 11 |
| REGULATORY-APPROVED / ENGINEERING-DERIVED | 14, 19 | 2 |
| JOINT REGULATORY + ENGINEERING | 8, 9, 12, 13, 17, 18 | 6 |
| FORMAL SIGN-OFF | 20 | 1 |
| **Total** | | **20** |

**Capability limits — all three resolved by Milestone 5A-P1:**

| Item | Former limitation | Now |
|---|---|---|
| 11 | Rules validated and stored, never evaluated | **Evaluated at runtime** (`5A-DEC-004`), fail-closed. `iid.*` rules await OQ-8. |
| 12 | Bindings inert; no resolver layer | **Governed allow-list resolver** with provenance and explicit failure (`5A-DEC-001`). Source selection awaits OQ-8. |
| 18 | No per-question export exclusion | **Not required** — `5A-DEC-003` chose full governed inclusion. |

**One live constraint remains:** OQ-8 (which `AssessmentSnapshot` governs
execution-level `iid.*`). Content that depends on `iid.*` applicability or on a
resolved FDA-derived value should not be approved as *automatic* until it is
answered. Everything over `product.*` is fully functional.

**High interpretation risk:** items 1, 3, 4, 5, 7, 9, 10, 11, 12, 13, 15, 16, 20.

## 4. Gate status

> ## PRODUCTION REGULATORY CONTENT GATE: **OPEN**
> ## **0 of 20 approved.**
> ## Milestone 5A: **BLOCKED ON REGULATORY APPROVAL.**

No production regulatory checklist content may be authored, loaded or activated
until item 20 is signed. Item 0 of the 4D-4 table (gate scope, `4D4-DEC-001`)
remains approved and remains outside the 20 content items — it decided
sequencing, not content.

**This count changes only when a named regulatory authority supplies a real
approval.** It is not advanced by document completeness, engineering readiness
or milestone progress.
