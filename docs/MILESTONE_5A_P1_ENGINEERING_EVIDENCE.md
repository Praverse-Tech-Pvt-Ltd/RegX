# Milestone 5A-P1 — Production Content Engine Prerequisites: Engineering Evidence

> **Scope:** engineering prerequisites only. **No production regulatory content
> is authored, loaded or approved.** Approval count unchanged: **0 of 20**.
> **Branch:** `regx/feat/milestone-5a-p1-content-engine-prerequisites`
> **Base:** `regx-main` `620267f7be659fa4c9f4ec9cb654e6ca70d8fd69`
> **Decisions implemented:** `5A-DEC-001` … `5A-DEC-007`

## 0. Engineering prerequisites are not regulatory approval

This milestone builds mechanisms. It does not decide what any regulated question
asks, which templates ship, what an option means, which FDA field answers what,
or what a jurisdiction claim asserts. Those remain regulatory decisions made
through the 5A package by a qualified authority.

Nothing here moves the gate. **0 of 20 before, 0 of 20 after.**

## 1. Gap confirmation — verified independently before building

Each discovery claim was re-checked against merged code at `620267f` rather than
taken from the discovery document. All six held.

| Claim | Verdict | Evidence |
|---|---|---|
| A — FDA-derived binding inert, resolver absent | **CONFIRMED** | `answer_sources.py` did not exist; `create_execution()` set `raw_value=None` for every response; `prefill_source` / `default_value_binding` had no reader anywhere |
| B — applicability stored/validated but not evaluated | **CONFIRMED** | `applicability.py` exposed only `validate_condition_json()` and `canonicalize()` |
| C — select options had no label representation | **CONFIRMED** | `validation_rule["options"]` was a bare `list[str]`; no `QuestionOption` model exists |
| D — no structured jurisdiction | **CONFIRMED** | No `jurisdiction` identifier anywhere in backend code |
| E — export has no per-question exclusion contract | **CONFIRMED** | `controlled_export` projects every response of the execution |
| F — platform-master governance | **ALREADY EXISTS** | `can_author_platform_master()`, `can_mutate_definition_scope()`, wired through `_authorize_mutation()`; 49 existing tests |

F is the reason no platform-master code was written: §7 said add code only if a
gap exists, and there was none.

## 2. `5A-DEC-001` — FDA-derived resolver layer

**New module `iig_checklist/answer_sources.py`** — the module the 4D-3 spec named
(M4D3-SVC-007/008) and that was then held out of scope by instruction.

| Requirement | How it is met |
|---|---|
| Controlled identifier, not executable code | `ANSWER_SOURCE_REGISTRY`, an immutable `MappingProxyType` of module-level functions |
| Allow-list / registry pattern | `is_known_resolver()` is the single authority; refused at authoring **and** at resolution |
| Deterministic | Pure functions of their input; no query, no transaction, no clock, no actor dependence |
| Decimal-safe | `format(value, "f")` — never a float, never scientific notation |
| No DB primary IDs | Provenance carries UUIDs and a source checksum only |
| Source provenance captured | Resolver identifier, resolver version, status, source kind, source public_id, source version, source field |
| Source release/version identity | `"<release public_id>:<source_checksum_sha256>"` — the UUID says *which release*, the checksum says *which exact bytes*; either alone would miss a re-ingest |
| Reproducible after approval | Provenance is persisted on the response and is checksum-covered in the export |
| Explicit failure | Four statuses: `resolved`, `value_unavailable`, `source_unavailable`, `unknown_resolver` |
| No fabricated default | A non-resolved outcome carries `value=None`; zero and empty string are never substituted |
| Tenant isolation | The resolver never queries; the caller supplies an already-scoped governed object |

**Persistence.** New `ChecklistResponse.source_provenance` (JSON, nullable),
written only by the governed population pass at execution creation, read-only on
the serializer, and included in the checksum-covered export when present.

**Authoring validation.** `ChecklistQuestion.clean()` refuses a `prefill_source`
that is not an approved identifier, and refuses one on a question that is not
`FDA_DERIVED_DEFAULT` — nothing would read it there, so it could only mislead a
content reviewer.

**Synthetic bindings only.** Three registry entries exist so the mechanism is
real and exercised. They declare no production regulatory mapping: which FDA
field answers which regulatory question is content the authority approves
(register item 12).

## 3. `5A-DEC-004` — applicability runtime

**Evaluator** (`applicability.py`) implements the already-approved semantics and
invents no vocabulary: the same operators the validator enforces, the same six
registry-version-1 fields, the same three outcomes.

- Pure: no DB, no side effects, no `eval`, no `exec`, no dynamic attribute
  access — asserted structurally through the AST, not by substring scan.
- Returns the rule's own `outcome_if_true` / `outcome_if_false`, never a bare
  boolean: which branch means "not applicable" is the author's decision.
- Absence handling per M4D3-APP-005; explicit `null` is treated as absent.
- `True == 1` is refused. Python conflates them; regulated branching must not.
- Malformed node → `ApplicabilityEvaluationError` (a `RuntimeError`), per
  M4D3-APP-003, distinguishing a contract breach from user-input validation.

**Governed writer** (`applicability_runtime.py`):

- context assembled **once per pass** (M4D3-APP-007) from the execution's own
  `FormulationVersion → ProductDevelopmentRecord`, so every question in one
  execution is judged against identical product state, and never persisted;
- blank product values are treated as absent, not as the empty-string value;
- `REVIEW_REQUIRED` persists as `REVIEW_REQUIRED:<reason_code>` with
  `is_not_applicable` false and `raw_value` untouched (M4D3-PST-002);
- `full_clean()` before every save (M4D3-PST-005);
- runs only for `draft` / `returned` executions (PST-007/008) — a submitted
  execution is never re-assessed from live data;
- only rule-governed responses are ever written (M4D3-APP-012);
- derived read-only `applicability_outcome` (PST-009) exposed on the API and in
  the export.

**Fails closed in both directions that matter:**

| Situation | Behaviour | Why |
|---|---|---|
| Rule reads a source group that could not be assembled | `review_required`, reason `APPLICABILITY_SOURCE_UNRESOLVED` | "We could not find out" is not "no" |
| Stored condition tree the evaluator refuses | `review_required`, reason `APPLICABILITY_RULE_MALFORMED` | One malformed rule must not make an execution uncreatable, and must not be read as applicable either |

**APP-009 untouched.** The client-facing update service still refuses
client-supplied rule-owned applicability; this module is the only writer of the
reserved marker.

## 4. `5A-DEC-002` — select option labels

Governed shape `{"value", "label"}`; legacy bare-string form still parses with
`label = None` — an honest "no approved label", because a data migration cannot
invent labels that never existed and inventing them is what the content gate
exists to prevent.

Refused, each with a governed error code: empty value, empty label, duplicate
value, unknown key, non-string/non-object entry, empty list, over-long label,
more than `MAX_SELECT_OPTIONS`. Validation runs at **authoring** time, so a
content defect is never reported as though a reviewer's answer were wrong.

Authored order is preserved as display order. The separate rule that a
`multi_select` **response** is sorted ascending is about the stored answer and is
untouched.

Answer validation stays **label-blind**: a response is checked against the stable
value, so re-labelling an option can never invalidate an answer already recorded
— and submitting a label instead of a value is refused.

The resolved vocabulary is exposed as a read-only `options` field so no client
reaches into `validation_rule` or prettifies a code.

## 5. `5A-DEC-005` — jurisdiction

Structured, version-governed, controlled vocabulary with exactly one member.

Owned by `ChecklistVersion`, not `ChecklistDefinition`: a version is what is
approved against a defined regulatory basis and source set, and a definition
carries no lifecycle at all, so it cannot express "approved under this regulator
as of this version". It sits beside `regulatory_basis` for that reason.

Frozen by the same `clean()` rule that freezes `regulatory_basis`. Inside the
checksum-covered export payload and the CSV rendering. Emitted as `""` rather
than omitted when not stated, so "not stated" stays distinguishable from "this
export predates the field".

**The migration backfills nothing.** Retro-labelling pre-5A synthetic content
`US_FDA` would assert an approval basis nobody gave it.

## 6. `5A-DEC-003` — controlled export

**No per-question exclusion mechanism was built.** Regressions pin that governed
questions stay included, that applicability state and FDA provenance and
jurisdiction are all covered, that a select value stays interpretable, and that
the checksum moves when any of that provenance changes.

Canonical serialization is unchanged.

## 7. `5A-DEC-006` — platform-master ownership

**Verified, not rebuilt.** `can_mutate_definition_scope()` already separates
visibility from mutation authority: platform-master rows are visible to every
tenant so they can be consumed, and mutating one additionally requires
`can_author_platform_master()`, which no tenant role satisfies. Tenant-scoped
definitions additionally require a matching tenant context. Self-approval is
refused on version approval.

No duplicate-per-tenant mechanism exists or was added. Mutation proof F confirms
the control is load-bearing.

## 8. `5A-DEC-007` — regulatory segregation of duties

Recorded as a **package requirement**, deliberately not a second workflow engine
for a Markdown file:

- the package envelope now carries separate `prepared_by`, `reviewed_by`,
  `regulatory_approver` and `engineering_reviewer` fields;
- item 20 requires the author and the regulatory approver to be different named
  individuals, and requires explicit confirmation that engineering compatibility
  review was **not** treated as regulatory approval;
- the completion checklist validates the inequality.

The application's own self-approval bar on `ChecklistVersion` is a **different
control** governing the later load, and is verified separately. The two are not
conflated.

**No 21 CFR Part 11 electronic-signature compliance is claimed**, and no such
system exists in this repository.

## 9. Migrations and backward compatibility

Two additive migrations, both non-destructive:

| Migration | Change | Backfill |
|---|---|---|
| `0004_jurisdiction_on_version` | `ChecklistVersion.jurisdiction`, blank-default | **None** |
| `0005_response_source_provenance` | `ChecklistResponse.source_provenance`, nullable | **None** |

No column is dropped, renamed or narrowed. Existing synthetic data remains
usable, and the full pre-existing suite passing is the proof.

## 10. Tests

| Suite | Result |
|---|---|
| New `test_5a_p1_content_engine_prerequisites.py` | **90 passed** |
| Full `iig_checklist` app | **1389 passed, 0 failed** |
| New frontend `content-engine-prerequisites.test.tsx` | **13 passed** |
| Full frontend unit | **251 passed** |

Security cases covered explicitly: hostile resolver identifiers
(`os.system`, `__import__`, a dotted model path, a traversal string, empty),
registry immutability, absence of dynamic dispatch (AST-checked), malformed
applicability rules, a label submitted in place of a machine value, duplicate
options, tenant/platform mutation authority, UUID-only provenance, and
server-controlled fields being read-only.

### Two pre-existing tests updated, neither weakened

1. **Export governed-shape test** — the exact-equality key set gains
   `applicability_outcome`. It remains equality, not a subset.
2. **APP-009 inertness test** — now asserts "unchanged by the PATCH" rather than
   "field is empty". With a governed writer in existence, only the former
   actually expresses inertness; the old form passed only because nothing in the
   system had ever written the field.

## 11. Mutation proofs

Each applied alone, measured, reverted. **Residual mutations: NONE** — working
tree verified clean after each.

| | Mutation | Expected | Observed |
|---|---|---|---|
| **A** | Bypass the resolver allow-list (`is_known_resolver` → `True`) | security test fails | **2 failed** — allow-list membership and authoring-time binding refusal |
| **B** | Make the evaluator permissive on a malformed rule | fail-closed test fails | **4 failed** — three malformed-node cases and the malformed-rule containment test |
| **C** | Allow an ordinary PATCH to control rule-owned applicability | APP-009 regression fails | **9 failed** across the APP-009 suite |
| **D** | Render the machine value instead of the label | frontend test fails | **4 failed** — two mapper cases and two rendering cases |
| **E** | Drop jurisdiction from checksum-covered provenance | export/checksum test fails | **3 failed** — presence, checksum sensitivity, and not-stated emission |
| **F** | Let a tenant actor mutate platform-master content | tenant/permission test fails | **13 failed** across the platform-mutation suite |

## 12. What remains open — and is deliberately not answered here

**OQ-8: which `AssessmentSnapshot` governs execution-level `iid.*` values?**

An `AssessmentSnapshot` is scoped to one formulation **component**; applicability
and FDA-derived defaults are properties of the **execution**. No approved
specification says which component's snapshot governs, or whether one must be
created during a population pass. Choosing one would be engineering deciding
which precedent record answers a regulated question.

Until it is answered:

- an applicability rule reading `iid.*` evaluates to `review_required` with
  `APPLICABILITY_SOURCE_UNRESOLVED`;
- an FDA-derived binding records `source_unavailable` with no value.

Both are visible in the API and in the controlled export. Rules and content over
`product.*` are fully functional.

This is the §4 "stop and register the governance question rather than guessing"
path taken deliberately, on exactly one sub-question, while everything the
approved specification does settle was implemented.

## 13. Status

| | |
|---|---|
| Milestone 5A-P1 | **COMPLETE** |
| Milestone 5A | **READY FOR REGULATORY AUTHORING / BLOCKED ON HUMAN REGULATORY APPROVAL** |
| Production regulatory content | **0 of 20** |
| Production questions authored | **0** |
| Production templates loaded | **0** |
