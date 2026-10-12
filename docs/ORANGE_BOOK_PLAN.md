# Orange Book plan: SOW 2.5

Status: **Phase 1 (discovery and design) proposal, for owner review.** Nothing in
this document is built yet. Written 2026-10-12 against `regx-main@732133f`.

Scope: SOW 2.5, "FDA Orange Book Integration". Calculators (2.3), AI features and
the white-paper *calculations* are out of scope until separately signed off.

**Source decision (owner, 2026-10-12):** iCretegy has confirmed in writing that
the **public FDA Orange Book download is the primary data source**. Their Excel
is an optional cross-check only. **No Excel importer will be built.**

---

## 1. Current state vs SOW 2.5

SOW 2.5 (pages 7–8) asks for two things:

> Automated calculations: user enters minimal inputs and the platform fetches
> reference data and performs calculations automatically like in white paper &
> IIG checklist. iCretegy shall provide the FDA database excel and Praverse
> Tech Pvt. Ltd. needs to update accordingly.

| SOW element | Today (verified in code) | Gap |
|---|---|---|
| Ingest Orange Book products | `parsers.parse_orange_book_products` reads `Products.txt` (or the ZIP) and `import_fda_release` registers a release. Lifecycle is `registered → validated → under_review → approved → active`, and only one release is active per dataset type | Never run on a real file: the fixtures are synthetic and the tables are empty |
| Products fidelity | `Type` (RX/OTC/DISCN) is **ignored**. `discontinued` reads a `_discontinued` key the parser never sets (`adapters.py:48`), so **every real product imports as not discontinued**. `approval_date` is **never filled**; only `approval_date_text` is set (`importer.py:190`). `Applicant_Full_Name` is read only if present and is not in the required-column list | The flags and dates a user relies on are wrong or empty |
| Patents | Not imported. `Patent.txt` is deliberately skipped. Dataset type `orange_book_patents` exists but has no model | Model, parser, importer and API |
| Exclusivity | Same: `Exclusivity.txt` is skipped | Model, parser, importer and API |
| Lookup | `GET /fda-data/orange-book/products/` reads the **active release only**. Filters: `active_ingredient`, `route`, `dosage_form`, `strength`, `application_type`, `rld`, `reference_standard`, `discontinued` | **No filter by trade name or application number**, and no single "minimal input" lookup |
| Reference product selection | `formulations` stores an immutable snapshot (application number, product number, product UUID, release UUID). That is good: later releases cannot change past selections | **The submitted identifiers are not validated** (`formulations/serializers.py:69-74`). Any UUID or number is stored, even one that matches no Orange Book row |
| Fetch from fda.gov | None. Local files only | See §3. FDA's abuse detection currently blocks scripted downloads |
| Change report between releases | None | §4 |
| "Calculations like in white paper" | **The legacy white paper performs no calculations** (§6) | The calculation must be specified by the client before anything is built |
| Scheduler | **No Celery beat in REGX.** Compose runs only `celery -A regx worker` (`compose.yaml:92`), and there is no `beat_schedule`, `django-celery-beat` or periodic task anywhere in `backend/` | Needed for Phase 4 |

### What FDA publishes today (checked live 2026-10-12)

Source: <https://www.fda.gov/drugs/drug-approvals-and-databases/orange-book-data-files>
(the page says "Content current as of: 08/18/2026").

- One compressed ZIP (link `/media/76860/download?attachment`), which "unzips into
  three files": **`Products.txt`, `Patent.txt`, `Exclusivity.txt`**.
- "All three files are in ASCII text, tilde (~) delimited format."
- The page states **no update frequency for the ZIP**. Only the separate openFDA API
  says "updated monthly".
- Field definitions on the page, given as display labels:

| File | Fields (page order) |
|---|---|
| Products.txt (14) | Ingredient · Dosage form;Route · Trade Name · Applicant · Strength · Application Type (N/A) · Application Number · Product Number · TE Code · Approval Date ("Mmm dd, yyyy" or "Approved prior to Jan 1, 1982") · RLD · RS · **Type (RX, OTC, DISCN)** · **Applicant Full Name** |
| Patent.txt (10) | Application Type · Application Number · Product Number · Patent Number · Patent Expire Date ("MMM DD, YYYY") · Drug Substance Flag (Y/null) · Drug Product Flag (Y/null) · Patent Use Code · Patent Delist Request Flag (Y/null) · Patent Submission Date |
| Exclusivity.txt (5) | Application Type · Application Number · Product Number · Exclusivity Code · Exclusivity Date ("MMM DD, YYYY") |

**Not verified: the actual header names inside the files.** A scripted download of
the ZIP returned `302 → /apology_objects/abuse-detection-apology.html → 404`, so I
could not open a real file. I did not try to get around this. The page gives display
labels, not header strings. Based on the existing parser and fixtures, I expect the
headers below, but this is unconfirmed:

- Products: `Ingredient~DF;Route~Trade_Name~Applicant~Strength~Appl_Type~Appl_No~Product_No~TE_Code~Approval_Date~RLD~RS~Type~Applicant_Full_Name`
- Patent: `Appl_Type~Appl_No~Product_No~Patent_No~Patent_Expire_Date_Text~Drug_Substance_Flag~Drug_Product_Flag~Patent_Use_Code~Delist_Flag~Submission_Date`
- Exclusivity: `Appl_Type~Appl_No~Product_No~Exclusivity_Code~Exclusivity_Date`

**Differences from what the importer expects:**
1. Products has **14** columns per FDA. The parser requires 12 and ignores `Type` and
   `Applicant_Full_Name`. A real file still parses, because extra columns are allowed,
   but the discontinued flag and the full applicant name are lost.
2. **The RLD/RS values are unconfirmed.** The page says these products are "identified
   by 'RLD' in the RLD column". The adapter treats only `YES` as true (`adapters.py:43-44`).
   If the real file carries `RLD`/`RS` rather than `Yes`/`No`, **every product would
   import as non-RLD**. This must be checked against the real file in Phase 2.
3. The date formats are "Mmm dd, yyyy" or "Approved prior to Jan 1, 1982", and the
   importer parses neither into `approval_date`.

**Phase 2 entry check (mandatory before importing):** an operator downloads the ZIP
in a browser and reads the three header rows plus a sample of `RLD`/`RS`/`Type`
values. If any of the differences above turn out to be real, stop and fix them first
(Phase 1b below).

---

## 2. Data model: patents and exclusivity

The principle: **one FDA ZIP = one release**, and every row from all three files
belongs to that release. That gives release isolation by construction. A patent from
release A can only ever link to a product from release A.

The current schema allows one active release per `dataset_type`. Patents and
exclusivity therefore ride on the **products release** (`orange_book_products`) as
child rows of the same ZIP, rather than as separately activated releases. That makes
it impossible to activate products from one month alongside patents from another.
The `orange_book_patents` and `orange_book_exclusivity` dataset types stay
non-importable on their own (`dispatch.py` keeps the stated reason).

```
FDADataSourceRelease (orange_book_products, one per ZIP)
 ├── OrangeBookApplication (release, appl_type, appl_no)                 [exists]
 │    └── OrangeBookProduct (release, application, product_no)           [exists; + marketing_category]
 │         ├── OrangeBookPatent      (release, product?, …)              [new]
 │         └── OrangeBookExclusivity (release, product?, …)              [new]
 └── FdaImportRowResult, now also for Patent.txt and Exclusivity.txt rows [exists; + source_member]
```

**`OrangeBookProduct` additions (Phase 1b):**
- `marketing_category` (RX / OTC / DISCN, verbatim). `discontinued` is derived as
  `Type == "DISCN"` and nothing else.
- `approval_date`, parsed from "Mmm dd, yyyy". "Approved prior to Jan 1, 1982" stays
  text-only with `approval_date = NULL`; it is never coerced.
- `applicant_full_name` filled from `Applicant_Full_Name`.

**`OrangeBookPatent` (new):**

| Field | Type | Notes |
|---|---|---|
| `release` | FK, PROTECT | Isolation key |
| `product` | FK to `OrangeBookProduct`, **nullable**, PROTECT | Resolved on (release, appl_type, appl_no, product_no). Unmatched rows are kept with `product=NULL` and reported, never dropped |
| `application_type`, `application_number`, `product_number` | char | Verbatim, so unmatched rows stay traceable |
| `patent_number` | char | Verbatim; it may carry a suffix such as `*PED` (pediatric) |
| `patent_expire_date` / `patent_expire_date_text` | date / char | Parsed date plus verbatim text |
| `drug_substance_flag`, `drug_product_flag`, `delist_requested_flag` | bool | `Y` → true; null or blank → false |
| `patent_use_code` | char | Verbatim, e.g. `U-123` |
| `submission_date` / `submission_date_text` | date / char | |
| `source_row_locator`, `raw_row_payload`, `raw_row_checksum` | | Same audit pattern as products |

The unique key is `(release, application_type, application_number, product_number,
patent_number, patent_use_code)`. The same patent legitimately repeats with different
use codes. An exact duplicate row becomes `DUPLICATE` in `FdaImportRowResult`.

**`OrangeBookExclusivity` (new):** `release`, nullable `product`, the three identifier
fields, `exclusivity_code` (verbatim, e.g. `NCE`, `ODE-123`, `M-…`),
`exclusivity_date` / `_text`, and the same audit fields. The unique key is
`(release, appl_type, appl_no, product_no, exclusivity_code, exclusivity_date_text)`.

There are no tenant FKs: this is platform-level reference data (CLAUDE.md, §Tenancy).
Code meanings (patent use codes, exclusivity codes) are **stored, not interpreted**.
FDA's appendices define them, and decoding them is a later, separately approved step.

---

## 3. Fetch design (Phase 4)

**Live finding:** scripted requests to the FDA download URL are redirected to FDA's
abuse-detection page. An unattended fetcher may therefore be blocked. **Before Phase 4
the owner must confirm FDA's terms for automated retrieval.** If automated retrieval
isn't allowed, Phase 4 becomes "operator uploads the ZIP; everything else stays
automatic". **Circumventing the block (spoofed browser headers and the like) is not an
option.**

- **Where the downloader lives:** in `external_integrations`, the only permitted
  outbound edge. Use a system-owned connector (`https://www.fda.gov/media/76860/download`,
  GET only) through its existing SSRF-checked, pinned-IP transport with capped body
  size. `fda_data` must not import `external_integrations`: dependencies point only
  inward. The scheduled task therefore lives in a small composition module, or in
  `external_integrations` itself, which calls `fda_data.importer.register_release`. The
  import-linter contracts decide which; this is to be confirmed at Phase 4 design time.
- **Change detection, cheapest first:**
  1. a conditional request (`ETag` / `Last-Modified`) if FDA sends them;
  2. otherwise download and compute SHA-256.

  An identical checksum means the release already exists. The existing
  `(dataset_type, source_checksum_sha256)` unique constraint makes this idempotent,
  so nothing is created. `normalized_payload_sha256` also detects a re-zipped file with
  identical content.
- **A new file always lands unapproved.** The task runs
  `register → parse → import → validate` and stops at **`validated`**. It never runs
  submit-review, approve or activate. In this codebase that is the equivalent of
  "PENDING". A human takes the release through `submit-review → approve → activate`,
  and activation supersedes the old release through the existing lifecycle.
- **Failure handling:**
  - Network or HTTP failures and parse rejections create **no** release, or a
    `rejected` one with a reason code. The previous active release stays active.
  - A recorded `retrieved_at` gives "last successful check".
  - Retries are bounded (for example 3 with backoff), and the task is idempotent per
    the checksum.
- **Alerting:**
  - A structured `WARNING` or `ERROR` log line per failure, carrying a reason code and
    no file contents.
  - A visible "Orange Book: last check / last change / pending release awaiting
    review" status on the releases page.
  - Email or chat alerts need a channel decision. REGX sends no email today.
- **Schedule:** Celery beat, as its own compose service (Phase 4 adds it, because none
  exists). A daily check is proposed; the FDA page states no ZIP cadence. The task is
  recorded in `docs/TASK_RELIABILITY.md`, as its test requires.

---

## 4. Change report between two releases

Computed when a release reaches `validated`, comparing it with the currently active
release. It is stored as JSON on the release or in a child table, and is readable by
reviewers before they approve.

| Section | Key | Reports |
|---|---|---|
| Products | (appl_type, appl_no, product_no) | new · removed · changed. For changed rows, a per-field before/after: trade name, strength, TE code, RLD, RS, Type (incl. RX → DISCN), applicant |
| Patents | product key + patent_no + use code | new · removed · changed expiry date · delist flag set |
| Exclusivity | product key + code | new · removed · changed expiry date |
| Summary | n/a | counts per section, plus row-level import failures and unmatched patent/exclusivity rows |

The report is descriptive only. It contains no wording about regulatory significance,
and the claim-guard tests apply to it.

---

## 5. User lookup flow (Phase 5, with API work in Phases 1b and 3)

1. **Minimal input:** one search box that accepts an ingredient, a trade name or an
   application number (for example `N021436` or `021436`), plus optional route and
   dosage form. That needs new `trade_name`, `application_number` and combined `q`
   filters on the products endpoint.
2. **Results:** grouped by application, one line per product: trade name, ingredient,
   dosage form; route, strength, applicant, Type, **TE code**, **RLD** and **RS**
   badges.
3. **Product detail:**
   - all product fields;
   - **patents**: number, expiry date, DS/DP flags, use code, delist flag;
   - **exclusivity**: code and expiry date;
   - expiry dates labelled **"per FDA data dated X"**.
4. **On every view:** "Source: FDA Orange Book, release dated X". X is the release's
   FDA data date: `publication_date` where it is known, otherwise the date the file was
   retrieved, with that distinction labelled.
5. **Optional "Use as reference product" action** for the formulations flow. The server
   must validate that the product exists in the stated release and that the numbers
   match it (fixing the §1 gap).

Wording: factual labels only. Nothing says or implies "approved for", "can launch",
"patent-free" or "safe to file". The claim guard is extended to the new page.

---

## 6. White-paper flow: written spec for client sign-off (NOT to be built)

### What the legacy tool actually is (`company_site`, read-only review)

"General White Paper (Structural Research Plan)" (`RATools/views.py:13466-13893`,
`templates/RATools/WhitePaper/GeneralWhitePaper.html`) is a **manually completed
assessment form with a maker/checker approval chain**. Verified:

- **No calculations.** The inline JavaScript only resizes text boxes and serializes
  tables, and the view has no arithmetic.
- **No Orange Book, IID or patent/exclusivity data feed.**
  - RLD/RS fields (proprietary name, strength, NDA/ANDA no., approval date, holder,
    TE code, MDD) are **typed in by the user**.
  - Patent and exclusivity are **screenshot uploads** ("take it from Orange book").
  - The Orange Book appears only as a hyperlink.
- **The "IIG assessment table"** (ingredient, qty/mL, % w/v, total daily intake, IID max
  potency) is **free text with no computation**.
- **No AI/LLM call and no PDF generator.** The output is database records, uploaded
  images and checker notification emails.
- The rest of the tool:
  - a 92-question CTD module checklist (yes/no/NA + comment);
  - a combination-product assessment appendix;
  - up to 7 approval levels.

So **"calculations like in white paper" has no existing formula to port.** The SOW
wording and the legacy tool disagree, and the client must define what is to be
calculated.

### Proposed spec, for the client to accept, amend or reject

**Inputs (minimal):**
- an Orange Book product (chosen through the §5 lookup) as the RLD, plus an optional
  RS;
- the proposed generic's strength, dosage form and route;
- the proposed maximum daily dose (amount + unit + basis);
- for an IIG table: per-unit amounts of each inactive ingredient.

**Auto-filled from Orange Book data:** RLD/RS trade name, application type and number,
product number, strength, TE code, approval date, applicant (full name), Type, patents
and exclusivity, all with source and release date.

**Candidate calculations. Each one needs a formula, units, rounding and source
approved by the client; none is assumed:**
1. % w/v = quantity (mg) per mL ÷ 10. The unit convention needs confirming.
2. Total daily intake per excipient = per-unit amount × maximum dosage units per day.
3. A comparison of total daily intake against the IID maximum potency for the same
   route and dosage form. *This overlaps the existing IIG engine and its 0/20 content
   gate. The client must say whether the white paper reuses that engine or is
   separate.*
4. Strength-match between the proposed generic and the RLD (same strength present in
   the Orange Book: yes or no).

**Outputs:** a stored, reviewable assessment record with every input, every looked-up
value with its source and release date, and each calculated value with the formula
version. It goes through the existing Doer → Reviewer → VP workflow. Any document or
PDF output is a separate decision.

**Open questions for iCretegy:**
1. Which calculations, if any, should the white paper perform (the candidates above or
   others)? The legacy tool performs none.
2. Should it reuse the IIG checklist engine and its calculations for item 3, or stay
   separate?
3. Should patents and exclusivity be structured data from the Orange Book (Phase 3), or
   remain screenshots?
4. Units, rounding and thresholds for each approved calculation, plus who owns and
   signs the formula.
5. Should the 92-question checklist and the combination-product appendix be ported,
   and who owns and versions that question bank?
6. Which fields are mandatory, and must the output be a signed PDF or eCTD-ready
   document (and must it meet 21 CFR Part 11)?
7. The conclusion wording: "Not sure" or "Not sure, require controlled correspondence"?

---

## 7. Phases and sizes (estimates, one developer)

| Phase | Branch | What | Size (estimate) |
|---|---|---|---|
| **1b, recommended before Phase 2** | `regx/feat/orange-book-products-fidelity` | Map `Type` → `marketing_category` + `discontinued`; parse `approval_date`; take `Applicant_Full_Name`; confirm the RLD/RS value parsing against the real file; add `trade_name` / `application_number` / `q` filters; validate reference-product selection against a real product in the stated release. Migration + tests | **M** (1–3 days) |
| **2** | none (no code) | Manual browser download. Entry check of headers and values. Import via `import_fda_release` → validate → submit-review → approve → activate as a platform user. Verify count and 3 real products against the source file. Record the release ID, checksum and FDA date | **S** (< 1 day) |
| **3** | `regx/feat/orange-book-patents-exclusivity` | Models, migration, parser for Patent.txt and Exclusivity.txt, importer into the same release, read endpoints (public UUIDs, existing permission classes), and tests (malformed rows, release isolation, a real FDA sample row) | **M–L** (3–6 days) |
| **4** | `regx/feat/orange-book-auto-fetch` | Celery beat service, the fetch task through `external_integrations`, checksum change detection, release stops at `validated`, change report, failure logging and status, `TASK_RELIABILITY.md`. Mocked-download tests. **Blocked until FDA's automated-access terms are confirmed** (§3) | **L** (1–2 weeks); the upload-only fallback is **M** |
| **5** | `regx/feat/orange-book-lookup-page` | Search and detail page with patents and exclusivity, "Source: FDA Orange Book, release dated X" on every view, an nginx prefix, and vitest + Playwright tests, with the claim guard covering it | **M–L** (3–6 days) |

**Decision needed on Phase 1b.** Phase 2 as briefed allows no code changes. Importing
the real file today would store **wrong discontinued flags, possibly wrong RLD/RS
flags, and no approval dates**. The options:

- **(a)** Do Phase 1b first, so the first real release is correct. *(Recommended.)*
- **(b)** Import now as a baseline, and re-import as a new release after Phase 1b.
  That's allowed, because every load is a new versioned release.

**Phase 2 lookup limitation.** Without Phase 1b, the API can look up only by ingredient
(`active_ingredient`). There is no trade-name or application-number filter, so those
lookups would have to be verified against the database rather than the API.
