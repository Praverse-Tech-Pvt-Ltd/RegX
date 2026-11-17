# Checklist intake — iCretegy delivery of 2026-11-16 (report only)

> **What this is:** an inventory and fit analysis of the checklist files iCretegy sent on 2026-11-16.
> **What this is not:** approved content, an import, or a change to any database or code.
> - No question text from the files is reproduced here. Section and column names are given only where they describe structure.
> - The files stay outside the repository at `D:/Praverse/data/icretegy/checklists/2026-11-16/` (original: a WeTransfer folder in the owner's Downloads).
> - They are never to be copied into the repository, the review hand-off or any test fixture.
> - **The 20-item content gate is unchanged: 0 of 20 approved.**

Verified at `regx-main` `47021f7`. Analysis scripts and raw counts: `D:/Praverse/session-work/2026-11-17/checklists/`. The files were read with the Python standard library and, for the PDFs, `pypdf` in an offline container. No content was sent anywhere.

## Summary

- **What arrived:** six checklists, each as a DOCX and a PDF (12 files, all "v2.0").
- **What they are:** the six FDA cGMP inspection **systems**: Quality, Facilities & Equipment, Materials, Production & Process Controls, Packaging & Labeling, Laboratory Controls.
  - They are **site audit / inspection-readiness checklists**: 100 Yes/No/NA checkpoints each, with an evidence column.
- **They are not the IIG checklist content that SOW §2.2 (row 2.2 a) is waiting for.** They contain no dosage form, inactive ingredient, IID limit, unit or calculation.
- **Where they come from:** the legacy site already offers per-system checklists as downloads under **AuditIQ** (`company_site/AIDatabase`, `SystemChecklist` model, files named `<System>_Checklist_v1.pdf`). These files are most likely **v2.0 of those downloads**. The local copy has no v1 files to compare: that table and the media folder are empty here.
- **Likely the "six platform checklist definitions"** that `demo_seed`'s docstring says "ship with the database" (an open question in `PROJECT_OVERVIEW.md`). The number and naming fit, but nothing in the repository says so. **Ask iCretegy/Pratham to confirm; do not assume.**
- **Can REGX hold and run them?**
  - **Hold:** `templates_registry` (draft-only, checksummed source packages) can, with a DOCX adapter.
  - **Run:** `iig_checklist` cannot. Every execution is tied to a **formulation**, and a site audit has none. Three more gaps are listed in §3.
- **Scope decision first:**
  - REGX's template pipeline **excludes AIDatabase-originated content** by rule (`templates_registry/classification.py:15-41`).
  - These checklists contain no 483 or warning-letter wording, but they were an AuditIQ (AIDatabase) feature, which is SOW Part 1, not Part 2.
  - Whether they belong in REGX at all is for the owner and Pratham to decide, not engineering.

## 1. Inventory

### Files

| File | Type | Bytes | SHA-256 |
|---|---|---:|---|
| Facilities & Equipment Checklist-v2.0.docx | DOCX | 861,100 | `103ba5bf959db9dcfe50b20bca4eed2986c2cceb7f4892e4286eac8b79bfb085` |
| Facilities & Equipment Checklist-v2.0.pdf | PDF | 1,760,238 | `00410a7233f19e7cd9ba8fcc314d75fed7e15c78197c7966b1d6d3e5bb81924b` |
| Laboratory Control System checklist-v2.0.docx | DOCX | 861,393 | `e12a862537045397aee948e96bf580c028b77a93390c25283010065bd1745bb9` |
| Laboratory Control System checklist-v2.0.pdf | PDF | 1,771,518 | `749d0de7e4ac096acf9a841795266b27e3749dc8de6222575e987371bc7b2efc` |
| Materials System Checklist-v2.0.docx | DOCX | 861,250 | `7a099ea49788dfe151ce17e81f32898ae3791be4b50f864aeceeaa445bdb9fe8` |
| Materials System Checklist-v2.0.pdf | PDF | 1,754,719 | `26a11a3fff8ca51c1ee90018eb1bdbfb232abcbe4a4abc878846fecb1acd79c7` |
| Packaging & Labeling System Checklist-v2.0.docx | DOCX | 1,138,204 | `d140b5c027167cf12e387fc21e582aff70b741dae9ad1984b0a9f85c6c72d86b` |
| Packaging & Labeling System Checklist-v2.0.pdf | PDF | 1,859,822 | `56d39d1e041514f3c8926b47efbfa4a9539258a20d9be895b31fb37317730b21` |
| Production & Process Controls System Checklist-v2.0.docx | DOCX | 1,138,292 | `7414ff875332e52a9428757d9a7b63c06bc5d6f57de81ef88fcfe99757058289` |
| Production & Process Controls System Checklist-v2.0.pdf | PDF | 1,746,468 | `8d0eb07a099901b999c7f4f22061ff5b8e8955cb51b48bfeae419d82ca150f18` |
| Quality System Checklist-v2.0.docx | DOCX | 862,034 | `d132ff40aa39035f267078cad49beb509f2663dc99f78c7ea3418aba72983637` |
| Quality System Checklist-v2.0.pdf | PDF | 1,044,148 | `c506c0afa7523877e62cf10f3a83617124275ad6aa11a67a62734e7efe25aabd` |

- **Each PDF is an export of its DOCX:** Acrobat PDFMaker for Word, created 14–17 Apr 2026. It has the same 100 checkpoint IDs and runs to 10 pages.
- **Treat the DOCX as the source of record.** It is machine-readable; the PDF adds nothing.

### Per checklist

| Checklist (purpose) | ID prefix | Checkpoints | Sections inside the table | Answer columns | Rows with "if / where applicable" style wording | Rows with a number + unit | Rows citing a source |
|---|---|---:|---|---|---:|---:|---:|
| Quality System | `QS` | 100 | none (flat) | Yes · No · NA (an empty checkbox each), Evidence / Remarks (blank) | 0 | 0 | 0 |
| Facilities & Equipment System | `FE` | 100 | none | same | 2 | 0 | 0 |
| Materials System | `MS` | 100 | none | same | 2 | 0 | 0 |
| Production & Process Controls System | `PC` | 100 | none | same | 7 | 0 | 0 |
| Packaging & Labeling System | `PL` | 100 | none | same | 5 | 0 | 0 |
| Laboratory Control System | `LB` | 100 | none | same | 2 | 0 | 0 |

**Common structure:**
- **Front matter:** a title (also in the page header) and three narrative blocks: "Preamble and Purpose", typical risk areas / inspection triggers, and the system's role in product quality and patient safety.
- **Table:** one table of 1 header row plus 100 checkpoint rows. IDs run `XX-001` … `XX-100` with no gaps.
- **Checkpoint length:** median about 75–80 characters (41–224).
- **No sections, no sub-numbering, no weights, scores or pass marks.**

**Versions, dates, authorship and approval:**

| Mark | Present? |
|---|---|
| Version | **Only in the file name** ("v2.0"). No version field in the document body, header or footer. |
| Dates | **None in the document.** File metadata only: DOCX created 2025-12-01 (one 2026-04-16), last modified 2026-04-14 to 2026-04-17. These are file dates, **not effective dates**. |
| Author | File metadata names a generic account and individual client staff as last editors (names not reproduced here). |
| Approval / sign-off | **None.** No prepared/reviewed/approved block, signature, document number or effective date in the DOCX or the PDF. "signature" matches in the PDFs are inside checkpoint wording, not approval marks. |

**References and limits cited:**
- **Front matter:** every checklist names **21 CFR Parts 210/211**, the Quality System also Part 210 explicitly. Packaging & Labeling mentions **EU GMP** once.
- **Checkpoints:** no checkpoint cites a source.
- **Not cited at all:** no FDA guidance documents, ICH, USP, PIC/S or WHO references; no numeric limits; no IID references.

## 2. Comparison with what exists

| Existing content | What it is | Relation to the new files |
|---|---|---|
| **12 IIG dosage-form checklists** hard-coded in `company_site/templates/RATools/IIG/*.html` | Excipient (inactive ingredient) clearance per dosage form: tablets & capsules, injection, liquid orals, topical, semi-solids, nasal, inhalation, MDI, DPI, microsphere, liposome, transdermal | **No overlap.** Different subject (an excipient in a product versus a manufacturing site). |
| Legacy `RATools_generalreportquestions` (92) | ANDA dossier review, general requirements: drug product 75, drug substance 17 | **No overlap.** Dossier content review, not site audit. |
| Legacy `RATools_andareportquestions` (44) | ANDA report per dosage form: Module 1 administrative 22, 3.2.P 16, 3.2.S 6 | **No overlap.** |
| Legacy `RATools_vpreportquestions` (46) | Per-dosage-form report questions: drug substance 28, drug product / excipient / container closure 18 | **No overlap.** |
| Legacy `RATools_validationreportquestions` (17) | Analytical procedure validation/verification (3.2.S.4.3): API validation, API verification, drug product validation | **Topic overlap only.** The Laboratory Control checklist audits method validation practice at a site; the legacy rows check what a dossier section contains. Different question, different subject. |
| Legacy DMF tables (13 + 9) | DMF review and DMF completeness assessment (eCTD-numbered) | **No overlap.** |
| Legacy AuditIQ `SystemChecklist` (AIDatabase) | Upload slot: one downloadable file per system | **Same six systems.** Most likely a **newer version (v2.0)** of the downloadable checklists. Not verifiable locally: the table and media folder are empty. |
| REGX `iig_checklist` content | Only the demo seed's `DEMO-EXCIPIENT-REVIEW` (1 definition, 1 section, 3 questions) | **New.** Nothing comparable exists. |
| REGX `templates_registry` content | None loaded locally | **New.** |

**Net result:**
- **New:** all six checklists, as content.
- **Overlap:** only conceptually with the legacy AuditIQ download slot, and at topic level with the validation rows.
- **Differ:** from all IIG and dossier checklists in **subject** (site versus product or dossier).

## 3. Mapping to REGX

Two REGX structures could receive them. They do different jobs.

### 3a. `iig_checklist` (definitions that are **executed**: answers, review, gap analysis)

| Element | Fits as-is? | Notes |
|---|---|---|
| Definition / version / section / question | **Yes, structurally** | One definition per system, one version, **one section** (the files have no sections), 100 questions with codes `XX-NNN`. |
| Answer type | **Yes** | `yes_no_na` exists (`iig_checklist/enums.py`, `AnswerType`). |
| Evidence / Remarks column | **Gap** | A response has `raw_value`, `not_applicable_reason` and `override_reason` (`iig_checklist/models.py`, `ChecklistResponse`), but **no free-text remarks**. Options: (a) add a remarks field to responses; (b) a companion `long_narrative` question per checkpoint, which doubles each list to 200 and is not recommended; (c) attach evidence documents if that is what "Evidence" means. **Needs a decision on which.** |
| Conditional wording (18 rows) | **Partly** | No applicability rule is needed: all questions apply, and "not applicable" is an answer. Applicability rules could not express these conditions anyway: the six rule fields are all product/IID fields (`iig_checklist/field_registry.py:14`). |
| Calculations / IID / units | **Not needed** | No numbers, no units, no IID links. |
| Criticality | **Gap** | Required on every question and section (`Criticality`: informational … critical). The files assign none. |
| Scoring | **Gap if wanted** | The files have none. REGX gap analysis works on answers; whether a "No" is a gap needs a rule per question. |
| **Execution subject** | **Blocking gap** | `ChecklistExecution.formulation_version` is a **required** link, and `ChecklistDefinition.execution_scope` allows only `formulation_component` or `formulation_version`. **A site audit has no formulation.** Running these needs a new governed scope (for example "site"), a nullable or alternative subject, and a migration. The scope enum is governed configuration: adding a member is a decision, not a convenience. |
| Jurisdiction | **Yes** | `US_FDA` is the only member and matches 21 CFR 210/211. The single EU GMP mention needs a reviewer's call. |

**Verdict:** the content can be stored as **draft** `iig_checklist` definitions with no model change. They **cannot be executed** until the execution-subject gap is solved. The remarks and criticality gaps need decisions too.

### 3b. `templates_registry` (iCretegy source **templates**: imported, reviewed, versioned; no execution)

| Element | Fits as-is? | Notes |
|---|---|---|
| Source package with checksum, version, source date, licensing/ownership | **Yes** | `TemplateSourcePackage`: `source_checksum`, `source_version`, `source_date`, `licensing_ownership_status`, `approval_state` (`templates_registry/models.py:312`). |
| Template → version → section → item | **Yes** | Items keep `raw_text`, `legacy_identifier` (`XX-NNN`), `source_locator`, `response_type = yes_no_na`. Versions are created as **DRAFT/IMPORTED**, never active (`docs/TEMPLATE_IMPORT_PIPELINE.md`). |
| DOCX reading | **Gap** | The adapters read controlled JSON exports only (`templates_registry/adapters.py`). A DOCX adapter is needed. |
| **Exclusion guard** | **Decision** | `classification.py` excludes 483, warning-letter, inspection-analytics and **AIDatabase-originated** content. These files contain no 483 wording, but they come from the AuditIQ (AIDatabase) product line. Importing them means deciding they are REGX content, not Part 1 content. |

**Verdict:** the best fit for **holding** them under governance. It is not a place to **run** them.

## 4. The 20-item content gate

From `docs/REGULATORY_CONTENT_GATE_20_ITEM_DECISION_INTAKE.md`:
- The gate was written for `iig_checklist` definitions. If these files are imported through `templates_registry`, the template lifecycle governs instead (`docs/TEMPLATE_GOVERNANCE.md`), and the owner should say whether the gate applies to them too.
- **No item is marked approved by this report. Gate status stays "OPEN — 0 of 20 approved".**

| # | Item | Can these files help? | Still needs a named reviewer's sign-off |
|---|---|---|---|
| 1 | Which definitions ship | **Partly:** they propose six (one per system). But they are not IIG content, so they do not answer "which IIG definitions ship". | Yes, plus the scope decision. |
| 2 | Title per definition | **Yes, as a candidate** (page header titles). | Yes |
| 3 | Jurisdiction | **Candidate:** US FDA (21 CFR 210/211 in the front matter). One EU GMP mention. | Yes |
| 4 | Regulatory basis | **Partly:** Part-level citation only (210/211), none per question. | Yes |
| 5 | Source guidance, version, publication date | **No:** no guidance cited, no publication or effective date, version only in the file name. | Yes. This is the citation requirement and is unmet. |
| 6 | Section structure and ordering | **Partly:** order is given (001–100); there are no sections. | Yes |
| 7 | Question text (verbatim) | **Candidate text exists** (the highest-risk item). | Yes |
| 8 | Question codes | **Yes, as a candidate:** stable `XX-NNN` IDs. | Yes (joint) |
| 9 | Answer type | **Candidate:** Yes/No/NA, plus the remarks gap (§3a). | Yes (joint) |
| 10 | Required vs optional | **No:** not stated. The NA column suggests "all required, NA allowed"; that is an inference, not content. | Yes |
| 11 | Applicability rules | **No rules given.** 18 rows carry conditional wording handled by NA. | Yes |
| 12 | `FDA_DERIVED_DEFAULT` bindings | **Not applicable:** no FDA-data fields. | Confirmation that none apply |
| 13 | `SYSTEM_CALCULATED` bindings | **Not applicable:** no calculations. | Confirmation that none apply |
| 14 | Calculation dependencies | **Not applicable.** | Confirmation |
| 15 | Help / guidance text | **Partly:** the front matter could become definition-level guidance; there is none per question. | Yes |
| 16 | Reviewer expectations per question | **No:** only an empty "Evidence / Remarks" column. | Yes |
| 17 | Override eligibility | **No.** | Yes |
| 18 | Export inclusion | **No.** | Yes |
| 19 | Version number and effective date | **Partly:** "v2.0" from the file name; **no effective date**. | Yes |
| 20 | Formal sign-off | **No:** the files carry no approval or sign-off. | Yes, for the whole package |

**Also unanswered by the files:**
- criticality per question;
- the execution subject (site);
- what "Evidence" means (free text or attached documents).

## 5. Proposed import design (not built)

**Precondition:** the owner and Pratham decide that these checklists are REGX content, and in which structure (§3). Until then, nothing is imported.

**Recommended first step: hold them, don't run them.** Add a management command, `import_checklist_package`, built on the existing `templates_registry` pipeline:

1. **Input:** a manifest (JSON, kept outside the repository) listing each DOCX with its SHA-256, the received date (2026-11-16), the source reference ("iCretegy delivery 2026-11-16, WeTransfer"), the source version ("v2.0") and a licensing/ownership note. The command **refuses a file whose checksum differs from the manifest**. PDFs are recorded as companions, not imported.
2. **`register_source_package`:**
   - `source_checksum` holds the package checksum; per-file checksums go in `file_metadata`.
   - `source_date` is the received date and `source_version` is "v2.0".
   - `approval_state = pending`.
   - Platform-level (`tenant = null`).
3. **DOCX adapter (new):**
   - Reads the single table using the standard library, as the analysis scripts here do.
   - One record per row: `legacy_identifier = XX-NNN`, `raw_text` verbatim, `source_locator = file#row`, `response_type = yes_no_na`.
   - The front matter becomes the template description or guidance.
   - Refuses a file whose table shape differs: header columns, a row count other than 100, or a broken ID sequence.
4. **Exclusion guard:** classify as usual. If the owner rules these in scope, record that ruling in `docs/decisions/` and exempt this package explicitly. **Never weaken the guard in general.**
5. **Import** into a new **DRAFT/IMPORTED** template version. Never approved, never active. Re-running is idempotent (`get_or_create` per source record), and a changed file becomes a new package, never an edit.
6. **Activation:** only through the existing review flow (`MigrationBatchReviewView` → `lifecycle.approve` → `lifecycle.activate`, each permission-gated and audited), and only **after** the gate (or the template governance the owner names) is signed. The command has no activate option.
7. **Tests:** synthetic DOCX fixtures generated in the test itself. **No client file or text in fixtures.** Cover: checksum mismatch refused, wrong shape refused, draft only, idempotent re-run, guard behaviour.

**Second step, only if they must be run as audits in REGX:** the `iig_checklist` changes from §3a:
- a governed "site" execution scope and subject;
- a remarks field on responses;
- criticality assignment;
- then a converter from approved templates into DRAFT checklist definitions.

**Size estimate** (one experienced developer):

| Piece | Size |
|---|---|
| Manifest + command + DOCX adapter + tests (step 1) | **M (2–3 days)** |
| Scope exemption record + guard test | S |
| `iig_checklist` site scope + subject + migration + remarks field + tests (step 2) | **L (1–2 weeks)**, after a governed decision on the scope enum |
| Template → checklist definition converter (draft only) | M |

## Open questions for the owner, Pratham and iCretegy

1. Are these six system checklists meant for REGX (SOW Part 2) or for the AuditIQ / inspection product (Part 1)?
2. Are they the "six platform checklist definitions" the seed refers to?
3. Is v2.0 the controlled version? Is there a document number, effective date and an approver to record (gate items 5, 19, 20)?
4. What should "Evidence / Remarks" capture: free text, attached documents, or both?
5. Is criticality or scoring expected per checkpoint?
6. **When will the IIG checklist content for §2.2 arrive?** These files do not provide it.
