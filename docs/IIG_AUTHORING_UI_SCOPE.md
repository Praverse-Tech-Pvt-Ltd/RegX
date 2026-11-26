# IIG checklist authoring UI: scope (2026-11-26)

Scoping only. No code is in this PR.

**Why this exists:**
- The browser regression of 2026-11-25 (`docs/VALIDATION_REPORT_2026-11-25.md`, N-1) found that checklist content can be written only through the API.
- There is no screen to set a definition's execution scope, set a version's effective date, or add sections and questions.
- A definition created in the UI is saved with `execution_scope: ""`, and can therefore never be executed (`execution_scope_unclassified`).

**What this covers:** the screens, the API call behind each one, what the API lacks, an estimate, and what depends on the client's checklist content.

**Basis:** read from `regx-main@987c6bc`:
- `backend/iig_checklist/urls.py`, `views.py`, `serializers.py`, `enums.py`, `question_options.py`;
- `frontend/src/app/(regx)/iig-checklists/`.

**Estimates** are for one experienced developer and include tests (backend, vitest, and Playwright in its own spec file). They are estimates, not commitments.

## 1. What exists today

| Area | UI | API |
|---|---|---|
| Create a definition | Code, title, description, scope (tenant / platform master) | `POST iig-checklists/definitions/` accepts `execution_scope` too (QA-01, #156); the UI does not send it |
| Definition detail | Versions list; "Create new version" (no fields); delete an empty draft | `GET`/`DELETE definitions/<id>/`; **no PATCH** |
| Create a version | One click, no fields | `POST definitions/<id>/versions/` accepts the draft fields (`effective_date`, `expiry_date`, `regulatory_basis`, `jurisdiction`, `change_summary`; QA-06, #155) |
| Edit a draft version | Not possible | `PATCH versions/<id>/` with the same five draft fields, while the version is a draft or returned |
| Sections | Read-only list | `GET`/`POST versions/<id>/sections/`; `GET`/`PATCH`/`DELETE sections/<id>/`. Fields: `code`, `title`, `description`, `display_order`, `criticality` (required), `applicability_rule_public_id` |
| Questions | Read-only list | `GET`/`POST sections/<id>/questions/`; `GET`/`PATCH`/`DELETE questions/<id>/`. Fields: `code`, `question_text`, `help_text`, `display_order`, `answer_type`, `data_source_classification`, `required`, `criticality` (required), `allowed_units`, `evidence_requirement`, `calculation_binding_identifier`, `prefill_source`, `reviewer_confirmation_required`, `escalation_rule_identifier`, `regulatory_reference`, `default_value_binding`, `validation_rule` (select options in the governed `{value, label}` shape, `question_options.py`), `applicability_rule_public_id` |
| Applicability rules | None | `GET`/`POST versions/<id>/applicability-rules/`; `POST applicability-rules/validate/` |
| Lifecycle | Submit, approve, return, reject, activate, supersede, retire | The action endpoints. Submit, approve and activate check the effective date, at least one question (the empty-version fix of 2026-11-26) and the calculation bindings |

## 2. Screens to build

| # | Screen | What the user does | API calls | Missing API | Estimate |
|---|---|---|---|---|---|
| S1 | **New definition**: add an "Execution scope" choice | Choose "Formulation version" or "Formulation component" (required for a tenant definition that will be executed) | `POST definitions/` with `execution_scope` | none | S (½ day) |
| S2 | **Definition settings** | Correct the title or description; set the execution scope of a definition saved without one | — | **A1** | S (½ day, after A1) |
| S3 | **New version form** | Effective date (required before submit), expiry date, change summary, regulatory basis, jurisdiction | `POST definitions/<id>/versions/` with the draft fields | none | S (½ day) |
| S4 | **Draft version editor: header** | Edit the five draft fields while draft or returned; read-only otherwise | `PATCH versions/<id>/` | none | S (½ day) |
| S5 | **Draft version editor: sections** | Add, rename, set criticality, reorder, delete | `POST versions/<id>/sections/`, `PATCH`/`DELETE sections/<id>/` | **A4** (optional) | M (2 days) |
| S6 | **Draft version editor: questions** | Add, edit, reorder, delete. The form changes with the answer type: options for single/multi select (value and an approved label each), allowed units for quantity with unit, a calculation binding (and its required selector question), prefill source, evidence requirement, reviewer confirmation, escalation rule, regulatory reference | `POST sections/<id>/questions/`, `PATCH`/`DELETE questions/<id>/` | **A3** (the lists to choose from) | L (1–1½ weeks) |
| S7 | **Applicability rules** | Write a rule, validate it, attach it to a section or question | `GET`/`POST versions/<id>/applicability-rules/`, `POST applicability-rules/validate/`, then `PATCH` on the section or question | none | M (2–3 days) |
| S8 | **Pre-submit check panel** | See, before clicking Submit, everything submit would refuse: no effective date, no questions, a binding without its selector question | — | **A2** | S (1 day, after A2) |

**Roles (unchanged; enforced by the server):**
- Doer: authors drafts.
- Reviewer / VP: return, reject, approve.
- VP: activates.
- Platform-master content needs the platform-actor permission.

The screens only hide what the server would refuse. The server stays the authority.

## 3. Missing in the API

| # | What | Why | Estimate |
|---|---|---|---|
| **A1** | `PATCH definitions/<id>/`: title and description, plus the execution scope **once**, while it is blank | Definitions already created in the UI have a blank scope and can never be executed. Today the only way out is a new definition. The model already refuses changing a scope once it is set | S (½–1 day) |
| **A2** | `GET versions/<id>/prerequisites/` (or `POST …/validate/`): the activation prerequisites as a list of findings, changing nothing | Submit returns only the first problem. Authors need the whole list before they submit | S (1 day) |
| **A3** | A read-only catalogue (e.g. `GET iig-checklists/catalogue/`) of the governed vocabularies: answer types, data-source classifications, criticality, evidence requirements, the calculation-registry bindings (identifier, answer type, required selector question, unit) and the prefill sources | Without it the frontend copies backend enums and registry identifiers by hand, which drifts silently. The registry rules (selector question, units) are needed to build a form that passes activation | M (2–3 days) |
| **A4** | Optional: one call to reorder sections or questions | Reordering works today with one `PATCH display_order` per row; a bulk call only saves round trips | S (½ day) |

**Also found while scoping (not authoring, but the same screens):** `ChecklistVersionSerializer` does not return `return_reason`, `reviewed_by_email`, `returned_at`, `rejected_at` or `retired_at`, although the frontend type expects them. The small-fixes PR of 2026-11-26 adds only `submitted_by_email`, `approved_by_email` and `activated_by_email`.

## 4. Estimate

| Part | Estimate |
|---|---|
| API A1–A3 (A4 optional) | about 4–5 days |
| Screens S1–S5, S8 | about 5 days |
| S6 questions editor | about 1–1½ weeks |
| S7 applicability rules | about 2–3 days |
| **Total** | **about 3–4 weeks**, one developer, synthetic content only |

The order that unblocks the most:
1. S1 + S3 + A1 (scope and date: about 2 days). This alone makes a UI-created checklist executable.
2. S4–S6.
3. A2 + S8.
4. S7.

## 5. What depends on the client's checklist content

The screens can be built and tested now with synthetic content. **What may not happen before the client's sign-off:**

- **Sample content must be labelled as sample text, never look real** (owner condition, 2026-11-27). Every synthetic or demo definition, version, section, question and option label created while building or testing these screens carries the words **"SAMPLE – not real checklist content"** in its title or text (codes start `SAMPLE-` or `DEMO-`). Do not copy or paraphrase wording from real checklists, agency guidance or the client's files, and do not use realistic regulatory phrasing, product names or limits. This covers test fixtures, e2e mocks, screenshots and seed data alike.

- **No real checklist content may be activated** until the 20-item content gate is signed off. It is still **0 of 20** (`docs/REGULATORY_CONTENT_GATE_20_ITEM_DECISION_INTAKE.md`). The gate decides which definitions ship, their titles and jurisdiction, and more. The demo seed keeps its own `DEMO-` definition for this reason.
- **The content itself comes from the client:** question wording, criticality, which questions are required, evidence requirements, and the approved labels for every select option. Under 5A-DEC-002 a label cannot be invented or derived from a code (`question_options.py`).
- **Which calculation applies to which question** is Approval Register items 13/14 (`docs/APPROVAL_REGISTER_13_14_DECISION_INTAKE.md`). The screen can offer the registry bindings; choosing them for real content is the client's decision.
- **iCretegy's 2026-11-16 delivery looks like cGMP site-audit checklists, not IIG content** (`docs/CHECKLIST_INTAKE_2026-11-16.md`); they may belong to Part 1 / AuditIQ. The owner is confirming this with the client (19 Nov), so do not assume either way. Until then there is no confirmed IIG content to enter.
- **A named regulatory reviewer** must sign off content before activation (overview §12). That is a person, not a screen.

**Recommendation:** build S1 + S3 + A1 first. They are small, they don't depend on the client, and they close N-1 for synthetic and demo use. Build the full editor (S5–S7) when the client's content is close, so its forms match the real content.
