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
| Products fidelity | `Type` (RX/OTC/DISCN) is **ignored**. `discontinued` reads a `_discontinued` key the parser never sets (`adapters.py:48`), so **all 23,217 `DISCN` products in the real file (48%) would import as not discontinued**. `approval_date` is **never filled**; only `approval_date_text` is set (`importer.py:190`). `Applicant_Full_Name` is read only if present and is not in the required-column list | The flags and dates a user relies on are wrong or empty |
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

### Verified against the real file (2026-10-12)

**Source file:** `EOBZIP_2026_08.zip`, downloaded manually by the owner (scripted
downloads are blocked by FDA's abuse detection, see §3).
- Kept outside the repo at `D:/Praverse/data/fda/orange-book/2026-10-12/`.
- 1,097,768 bytes, SHA-256 `84e616aacf4f42bb85a94586c10abfc260f8fb9b60f07db3f10315ae70a3298e`.
- Members: **`products.txt`, `patent.txt`, `exclusivity.txt` (lower case)**. The parser
  matches member names case-insensitively, so this is fine.
- **The member timestamps are 2026-09-11**, while the FDA page says "content current
  as of 08/18/2026" and the file is named `_2026_08`. Phase 2 should record all three
  dates (file name month, page date, member timestamp) and treat none of them alone as
  "the FDA data date".

**All three files share one format:** ASCII (no byte ≥ 0x80, no BOM), **CRLF** line
endings, **no newline after the last row**, tilde (`~`) delimiter, header on line 1.
Every row has the same number of fields as its header.

| File | Rows | Header (exact) |
|---|---|---|
| `products.txt` | 48,761 | `Ingredient~DF;Route~Trade_Name~Applicant~Strength~Appl_Type~Appl_No~Product_No~TE_Code~Approval_Date~RLD~RS~Type~Applicant_Full_Name` |
| `patent.txt` | 22,303 | `Appl_Type~Appl_No~Product_No~Patent_No~Patent_Expire_Date_Text~Drug_Substance_Flag~Drug_Product_Flag~Patent_Use_Code~Delist_Flag~Submission_Date` |
| `exclusivity.txt` | 2,400 | `Appl_Type~Appl_No~Product_No~Exclusivity_Code~Exclusivity_Date` |

**Values (verified counts):**

| Column | Distinct values |
|---|---|
| Products `Type` | `RX` 24,757 · `DISCN` 23,217 · `OTC` 787 |
| Products `RLD` | `Yes` 7,829 · `No` 40,932 (only these two) |
| Products `RS` | `Yes` 4,508 · `No` 44,253 (only these two) |
| Products `Appl_Type` | `A` 37,875 · `N` 10,886 |
| Products `TE_Code` | 26 distinct; empty 26,830 · `AB` 14,901 · `AP` 3,821 · `AA` 1,048 · `AB1` 597 · `AT` 516 · `AB2` 314 · `AB3` 131 · `AN` 127 · `AO` 73 · `BX` 52 …, **including comma lists** such as `AB1,AB2,AB3,AB4` (longest is 15 characters) |
| Patent `Drug_Substance_Flag` | `Y` 3,549 · empty 18,754 |
| Patent `Drug_Product_Flag` | `Y` 9,704 · empty 12,599 |
| Patent `Delist_Flag` | `Y` 127 · empty 22,176 |
| Patent `Appl_Type` | `N` only |
| Patent `Patent_No` | digits, **some with the suffix `*PED`** (pediatric), e.g. `10946015*PED`; up to 12 characters |
| Patent `Patent_Use_Code` | 2,825 distinct (`U-nnnn`); empty 8,240 |
| Exclusivity `Exclusivity_Code` | 475 distinct; `NCE` 434 · `PED` 344 · `NPP` 168 · `NP` 132 · **`ODE*`** 92 · `PC` 59 · `M-14` 52 · `GAIN` 46 · `CGT` 38 … |
| Exclusivity `Appl_Type` | `N` 2,303 · `A` 97 |

**Dates.** Every date is `Mmm d, yyyy` or `Mmm dd, yyyy` (Python `%b %d, %Y` parses
both), with these exceptions:
- Products `Approval_Date`: 42,888 parse, and **5,873 are exactly
  `Approved Prior to Jan 1, 1982`** (capital "P"; the FDA page writes "prior"). There
  are no other unparseable values.
- Patent `Patent_Expire_Date_Text`: all 22,303 parse.
- Patent `Submission_Date`: 19,498 parse and **2,805 are empty**.
- Exclusivity `Exclusivity_Date`: all 2,400 parse.

**Integrity across files:**
- 48,761 unique product keys `(Appl_Type, Appl_No, Product_No)`, with no duplicates.
- **Every** patent and exclusivity row matches a product in `products.txt` (0
  orphans).
- 3,077 `DISCN` products are still marked `RLD=Yes`.

**Field lengths all fit the current model columns** (longest in brackets): ingredient
(233 / 1000), trade name (97 / 500), strength (215 / 500), applicant (20 / 255), full
applicant name (88 / 500), TE code (15 / 20), DF;Route (77).

**What this means for the importer (supersedes the earlier assumptions):**
1. **`Type` is a real 14-column field and is ignored today.** `discontinued` reads a key
   the parser never sets (`adapters.py:48`), so **all 23,217 `DISCN` products (48%)
   would import as not discontinued.** Must fix.
2. **RLD/RS are `Yes`/`No`.** The existing `== "YES"` comparison (`adapters.py:43-44`)
   is **correct**. The earlier concern, based on the FDA page's wording, does not apply.
3. **`approval_date` is never filled** (`importer.py:190`). 42,888 values parse; the
   5,873 pre-1982 values must stay text-only, with `approval_date = NULL`.
4. **`Applicant_Full_Name` is present in every row** and should be required.
5. Search needs `trade_name` and `application_number` filters; reference selection
   needs validation (unchanged from §1).
6. For Phase 3: patent numbers keep their `*PED` suffix verbatim; exclusivity codes
   keep `*` verbatim (`ODE*`); empty `Submission_Date` is allowed; patent rows are all
   `N` applications.

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

## 2b. openFDA API assessment (researched 2026-10-12, read-only)

Sources: official open.fda.gov pages and `api.fda.gov` only. **9 test calls** (of
30 allowed), with no API key. No integration code was written.

### What exists

| Claim | Evidence |
|---|---|
| openFDA drug endpoints: adverse events, product labeling, NDC directory, recall enforcement, **Orange Book**, Drugs@FDA, drug shortages | <https://open.fda.gov/apis/drug/> |
| **An official Orange Book endpoint exists**, described as "Approved Drug Products with Therapeutic Equivalence Evaluations (Orange Book)". The page says "Frequency of API updates: Monthly" and also "Content current as of: null" | <https://open.fda.gov/apis/drug/orangebook/> |
| Its schema covers **products, patents and exclusivity**: 27 fields, including `products.therapeutic_equivalence_codes`, `reference_listed_drug`, `reference_standard`, `patents.patent_number`, `expiration_date`, `patent_use_code`, `drug_substance_flag`, `drug_product_flag`, `patent_delist_flag`, `patent_submission_date`, `exclusivity.exclusivity_code`, `exclusivity_expiration_date`, plus `*_definition` fields | <https://open.fda.gov/fields/drugorangebook.yaml> (linked from the searchable-fields page) |
| Live endpoint: `https://api.fda.gov/drug/orangebook.json`. One record per product, `meta.last_updated = 2026-10-07`, **`total = 48,761`, the same as the ZIP's `products.txt` row count** | calls 1–4, 8 |
| Drugs@FDA (`https://api.fda.gov/drug/drugsfda.json`), "Daily (Monday-Friday)". **No patents or exclusivity** | <https://open.fda.gov/apis/drug/drugsfda/>, <https://open.fda.gov/fields/drugsfda.yaml> |
| Bulk export index `https://api.fda.gov/download.json`: Orange Book `export_date 2026-10-08`, `total_records 48,761`, one JSON ZIP partition on `download.open.fda.gov` (not downloaded) | call 9 |
| Rate limits: **without a key**, 240 requests/minute and **1,000/day per IP**; **with a free key**, 240/minute and **120,000/day per key**. Contact open@fda.hhs.gov for more | <https://open.fda.gov/apis/authentication/> |
| Terms: most data public domain (copy, modify, distribute, even commercially); attribution requested ("Data provided by the U.S. Food and Drug Administration"); "FDA makes no warranty that openFDA data will be error free"; access may be limited. Automated use is **not explicitly addressed**, but trying to exceed or get around limits can lead to restriction | <https://open.fda.gov/terms/> |
| Each API response carries: "Do not rely on openFDA to make decisions regarding medical care. … you should assume all results are unvalidated." | `meta.disclaimer`, every call |

### Field mapping: openFDA vs `products.txt` (as observed)

| products.txt | openFDA `orangebook` | Drugs@FDA |
|---|---|---|
| Ingredient / Strength | `products.active_ingredients[].name` / `.strength` | `products.active_ingredients[].name` / `.strength` |
| DF;Route | `products.dosage_form` + `products.route` | `products.dosage_form` + `products.route` |
| Trade_Name | `products.brand_name` | `products.brand_name` |
| Applicant / Applicant_Full_Name | `products.application_name` / `products.application_full_name` | `sponsor_name` (short name only) |
| Appl_Type / Appl_No | `products.application_type` / `products.application_number` | `application_number` as `NDA212379` / `ANDA210928` |
| Product_No | top-level `product_number` | `products.product_number` |
| TE_Code | `products.therapeutic_equivalence_codes` (array) | `products.te_code` |
| Approval_Date | top-level `approval_date` (`YYYYMMDD`) + `approved_prior_to_1982` | not per product (submission dates only) |
| RLD / RS | `products.reference_listed_drug` / `reference_standard` (boolean) | `products.reference_drug` / `reference_standard` (`Yes`/`No`) |
| Type | **`products.marketing_status`** ("HUMAN PRESCRIPTION DRUG", "DISCONTINUED"…). **Not in the YAML**, which documents `product_type` | `products.marketing_status` ("Prescription", "Discontinued"…) |

### ZIP vs API comparison (3 products, field by field)

Products tested: AMZEEQ `N212379/001` (RLD + RS, Rx, 12 patents), AZELAIC ACID
`A210928/001` (DISCN), BUDESONIDE `A215328/001` (TE `AB`).

- **Every data value matched.** That covers ingredient, strength, dosage form/route,
  trade name, both applicant names, application type/number, product number, TE code,
  approval date (after `Mmm d, yyyy` → `YYYYMMDD`), RLD and RS.
- **All 12 AMZEEQ patents** (number, expiry, use code, flags) and the exclusivity lists
  were identical.
- **6 mismatches, all the same vocabulary difference** in `Type`:
  - `RX` ↔ "HUMAN PRESCRIPTION DRUG" (Orange Book API) and "Prescription" (Drugs@FDA);
  - `DISCN` ↔ "DISCONTINUED" and "Discontinued".

  No values differ.
- **Documented but absent in practice:** `patent_use_code_definition` and
  `exclusivity_code_definition` did not appear in the AMZEEQ or N215358 records.
- **Optional fields:** flags that are false are omitted rather than sent as `false`.

### Third-party "Orange Book API" claims

None were encountered. All research used open.fda.gov and api.fda.gov only. Any
third-party API would be unverified and must not be used.

### Recommendation

- **(a) Source of record: the FDA Orange Book ZIP only.** The ZIP is FDA's primary
  publication, and the evidence doesn't justify replacing it:
  - The API matches it on the sample, but every response says "assume all results are
    unvalidated".
  - The schema and the data disagree in two places (`marketing_status` vs
    `product_type`, and the missing `*_definition` fields).
  - The API's dates can't be tied to a specific Orange Book edition.
- **(b) Optional cross-check on lookup: use the openFDA `orangebook` endpoint, not
  Drugs@FDA.** It has the same fields plus patents and exclusivity. A per-product
  comparison of the fields above could flag "differs from openFDA as of
  `last_updated`" without ever overriding the release.
  - Watch the **1,000 calls/day limit without a key**, or register a free key (an
    owner decision, since the key is an account).
  - Calls go through `external_integrations`, the only outbound edge.
- **(c) "New FDA data available" detection: poll `https://api.fda.gov/download.json`**
  once a day. One call; the response is about 0.6 MB.
  - A change in `results.drug.orangebook.export_date` or `total_records`, or in the
    Orange Book endpoint's `meta.last_updated`, raises an operator task: "download the
    current Orange Book ZIP and upload it".
  - This avoids fda.gov's file pages, where scripted downloads are blocked (§3).
  - It does not make the openFDA bulk JSON a source. Whether that export could ever
    serve as an automated source of record is an **open owner decision**: it is
    machine-downloadable and FDA-published, but it is a reshaped derivative.

**Effect on the plan:**
- **Phases 1b, 2, 3 and 5 are unchanged.** The ZIP remains the input, and the importer
  bugs are the same either way.
- **Phase 4 changes shape.** "Download the ZIP from fda.gov" (blocked) becomes
  "**detect via openFDA, then the operator uploads the ZIP; everything after the upload
  is automatic**". That is the upload-only variant already sized at M in §7. A
  daily-scheduled detection task still needs Celery beat.

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

> **The client-facing version, with our proposed answer to each question, is
> `docs/ORANGE_BOOK_WHITE_PAPER_SPEC.md`.** This section stays as the engineering
> background.

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
| **1b (approved by owner; in progress 2026-10-12)** | `regx/fix/orange-book-importer` | Map `Type` → `marketing_category` + `discontinued`; parse `approval_date`; require `Applicant_Full_Name`; RLD/RS parsing already correct (verified `Yes`/`No`); add `trade_name` / `application_number` / `q` filters; validate reference-product selection against a real product in the stated release. Migration + tests | **M** (1–3 days) |
| **2** | none (no code) | Manual browser download. Entry check of headers and values. Import via `import_fda_release` → validate → submit-review → approve → activate as a platform user. Verify count and 3 real products against the source file. Record the release ID, checksum and FDA date | **S** (< 1 day) |
| **3** | `regx/feat/orange-book-patents-exclusivity` | Models, migration, parser for Patent.txt and Exclusivity.txt, importer into the same release, read endpoints (public UUIDs, existing permission classes), and tests (malformed rows, release isolation, a real FDA sample row) | **M–L** (3–6 days) |
| **4** | `regx/feat/orange-book-auto-fetch` | Celery beat service, the fetch task through `external_integrations`, checksum change detection, release stops at `validated`, change report, failure logging and status, `TASK_RELIABILITY.md`. Mocked-download tests. **Blocked until FDA's automated-access terms are confirmed** (§3) | **L** (1–2 weeks); the upload-only fallback is **M** |
| **5** | `regx/feat/orange-book-lookup-page` | Search and detail page with patents and exclusivity, "Source: FDA Orange Book, release dated X" on every view, an nginx prefix, and vitest + Playwright tests, with the claim guard covering it | **M–L** (3–6 days) |

**Decision needed on Phase 1b.** Phase 2 as briefed allows no code changes. Importing
the real file today would store **wrong discontinued flags (23,217 rows) and no approval
dates (42,888 parseable values lost)**. RLD/RS would be correct. The options:

- **(a)** Do Phase 1b first, so the first real release is correct. *(Recommended.)*
- **(b)** Import now as a baseline, and re-import as a new release after Phase 1b.
  That's allowed, because every load is a new versioned release.

**Phase 2 lookup limitation.** Without Phase 1b, the API can look up only by ingredient
(`active_ingredient`). There is no trade-name or application-number filter, so those
lookups would have to be verified against the database rather than the API.
