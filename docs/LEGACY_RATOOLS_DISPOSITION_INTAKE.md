# Legacy RATools — Record Authority and Disposition Intake

> **What this is:** a blank decision form for the accountable business and data
> owners. Completing it is what unblocks P13c.
> **What this is not:** migration work, a recommendation, or an approval. **No
> decision field below is pre-filled and no owner is named.** No RATools code,
> data, route, approval state, signature or SQLite file is modified by this
> document.
> **Verified at** `regx-main` `7798f41fed6fac5af3fc6236a5ffc5187f9b163e`. Every
> count in §2 was **measured at this SHA**, not carried over from the earlier
> classification.
> **Companions:** [LEGACY_RATOOLS_CLASSIFICATION.md](LEGACY_RATOOLS_CLASSIFICATION.md),
> [LEGACY_BOUNDARY.md](LEGACY_BOUNDARY.md),
> [EXTERNAL_BLOCKER_READINESS.md](EXTERNAL_BLOCKER_READINESS.md),
> [AUDIT_IMMUTABILITY.md](AUDIT_IMMUTABILITY.md),
> [BACKUP_RESTORE_DR.md](BACKUP_RESTORE_DR.md)

> ## ⚠ The default until a decision exists is **RETAIN AND FREEZE**
>
> Nothing is deleted, rewritten, migrated or replaced while any category below
> reads `NOT DETERMINED`. **Superseded is not removable** — REGX having a newer
> equivalent is not a reason to remove a legacy record.

## 1. Why this needs an owner, not an engineer

The codebase cannot establish whether legacy RATools approval states or stored
signature images remain authoritative records for any client or process. That is
a business and data question. Engineering can describe what exists — and §2 does,
in measured detail — but **cannot decide what it means or what may happen to it.**

**Two failure modes this form exists to prevent:**

1. **Deleting because something is superseded.** REGX has newer equivalents for
   much of RATools. A surface can be superseded in capability and still be the
   only place a record exists.
2. **Fabricating history during migration.** Migration provenance and audit
   history are different things (§E). Converting legacy approval strings into
   REGX-shaped workflow events would assert a record that was never made.

## 2. Measured inventory at this SHA

**Counts below were re-measured, not copied.** Where a value was not measured, the
field is left blank rather than estimated.

### 2.1 Approval flow

| Fact | Measured value |
|---|---|
| Classes in `RATools/models.py` | **38** |
| Models carrying the 7-level approval flow | **7** — `ANDAUserReports`, `DMFChecklistUser`, `IIGChecklistUser`, `ProductComparison`, `ValidationUserReports`, `VPUserReports`, `GeneralChecklistUSer` |
| `approved_by_checkers_level*` field declarations | **49** (7 models × 7 levels) |
| `is_completed_by_doer` fields | **7** |
| Declared choices | `APPROVAL_CHOICES = [('False','False'), ('True','True'), ('Done','Done')]`, default `'False'`, `CharField(max_length=5)` |
| `approved_by_checkers_level*` references in `views.py` | **231** |
| `update_checker_status` occurrences | **29** |
| `get_checker_level` occurrences | **30** |
| Function definitions in `views.py` | **190** |
| `is_authenticated` checks in `views.py` | **45** |

### 2.2 Signature and applicant details

**One** signature field exists: `CCTemplate.signature`,
`ImageField(upload_to='signatures/', null=True, blank=True)`.

It sits on a model that also carries `nda_applicant_name`, `nda_number`,
`company_name`, `company_logo`, `responsible_person_name`, `email_address`,
`telephone`, `mobile`, `fax`, `us_agent_company_name`, `designation` and
`us_regulatory_agent_company_name` — i.e. **stored signature images alongside
regulatory applicant and named-person details.**

### 2.3 Uploaded and supporting files — broader than previously recorded

| Fact | Measured value |
|---|---|
| `ImageField` declarations | **13** |
| `FileField` declarations | **6** |
| Distinct `upload_to` targets | **17** |

Targets: `signatures/` · `logos/` · `media/iig` · `media/capsule_pictures_rld/` ·
`media/capsule_pictures_company/` · `media/capsule_pictures_diff/` ·
`media/capsule_pictures_fda/` · `media/tablet_picture_rld` ·
`media/tablet_picture_company` · `media/tablet_picture_diff` ·
`media/tablet_picture_fda` · `media/appendix_white_paper/rld_package` ·
`media/appendix_white_paper/company_package` ·
`media/GeneralWhitePaper/patent` · `media/GeneralWhitePaper/exclusivity` ·
`media/GeneralWhitePaper/snapshots`

> [LEGACY_RATOOLS_CLASSIFICATION.md](LEGACY_RATOOLS_CLASSIFICATION.md) records the
> signature field. **It does not record the other 18 upload fields.** Uploaded
> files are therefore a broader disposition category than previously captured,
> and they are listed separately in §A and §F.

### 2.4 Audit

**No audit infrastructure exists anywhere in `company_site`** — re-verified at
this SHA: **0** matches for an `AuditLog` / `AuditEvent` / `EventLog` class or a
`log_event` function.

For contrast, REGX `AuditEvent` is append-only at two layers — an ORM guard and
two PostgreSQL triggers ([AUDIT_IMMUTABILITY.md](AUDIT_IMMUTABILITY.md)).

### 2.5 Export and import tooling — none exists

| Fact | Measured value |
|---|---|
| Management commands in `RATools` | **1** — `send_demo_reminders.py` |
| `dumpdata` / `loaddata` references in `RATools` | **0** |
| Export or archive utility | **None found** |

> **This is a dependency for three of the four disposition options.** MIGRATE
> WITH PROVENANCE, ARCHIVE EXTERNALLY and DECOMMISSION each require tooling that
> **does not exist today**. Only RETAIN AND FREEZE needs no new engineering. That
> is a consequence to weigh, **not** an argument for choosing it.

## 3. SQLite inventory

**Five** files, sizes measured at this SHA. **Checksums and record counts are
deliberately blank — they were not measured**, and a disposition decision should
not rest on an estimate.

| Filename | Path | Size (bytes) | Actively referenced? | Nature | Checksum | Record count | Disposition |
|---|---|---:|---|---|---|---|---|
| `db.sqlite3` | `company_site/db.sqlite3` | 7,266,304 | **Yes** — `RAAI/settings.py:106` `NAME: BASE_DIR / "db.sqlite3"` | Live application database | | | |
| `db.sqlite3.bak` | `company_site/db.sqlite3.bak` | 7,159,808 | No | Unknown — name suggests backup, **not verified** | | | |
| `db_17_1_2.sqlite3` | `company_site/db_17_1_2.sqlite3` | 7,159,808 | No | Unknown — name suggests dated snapshot, **not verified** | | | |
| `db_corrupted.sqlite3` | `company_site/db_corrupted.sqlite3` | 6,991,872 | No | Unknown — name asserts corruption, **not verified** | | | |
| `db_old.sqlite3` | `company_site/db_old.sqlite3` | 655,360 | No | Unknown — markedly smaller than the others | | | |

> **A filename is not a provenance record.** `db_corrupted.sqlite3` may or may not
> be corrupt; `db.sqlite3.bak` may or may not correspond to any known point in
> time. **Four of the five files have no established provenance**, and deciding
> their disposition requires establishing it — which is itself work to be
> authorised, not an assumption to make here.

## 4. Route and surface classification — re-verified against BOTH URLconfs

> **The earlier mistake this repeats deliberately not to make:** an app-level
> URLconf scan is **not** a reachability test for a Django project whose root
> URLconf imports views directly. Both were parsed at this SHA.

### 4.1 Project-level `RAAI/urls.py` — measured

```
path('admin/', admin.site.urls)
path('', home)                      <- RATools view, SITE ROOT
path('about-alpesh/', about_alpesh) <- RATools view
path("termsofuse/", terms_of_use)   <- RATools view
path("privacy-policy/", privacy_policy) <- RATools view
path('ratools/', include('RATools.urls'))
path('aidatabase/', include('AIDatabase.urls'))
path('adminmaster/', include('AdminMaster.urls'))
```

**Four RATools views are routed directly by the project URLconf**, imported at
`RAAI/urls.py:5`. **`home` serves the site root `/`.** Removing these four would
take down `/`, `/termsofuse/` and `/privacy-policy/`.

### 4.2 `RATools/urls.py` — measured

| Fact | Measured value |
|---|---|
| Live `path()` entries | **167** |
| Commented-out `path()` entries | **2** |
| File length | 673 lines |

### 4.3 Classification

| Class | Count | Content |
|---|---:|---|
| **live-required** | 13 app routes **+ 4 project-level** | Public marketing, demo booking, contact; plus `/`, `/about-alpesh/`, `/termsofuse/`, `/privacy-policy/` |
| **superseded-but-live** | 147 | Checklist listing, CRUD and sample-report surfaces |
| **dead-unreachable** | 0 live routes | 2 commented-out route entries only |
| **migration-dependent** | all data-backed routes above | Anything backed by the SQLite tree |
| **governance-sensitive** | overlays 103 of the above | Approval flow and signature storage |

**The classes are not mutually exclusive.** A checklist CRUD route is
superseded-but-live, migration-dependent *and* governance-sensitive at once.
**Removability is decided by the strictest class a surface belongs to.**

> **56 routes carry no `@login_required`.** That is a statement about routes, not
> about data: the views test `request.user.is_authenticated` internally —
> **45 such checks** — and render a no-data preview to anonymous visitors. A
> route-level login column alone misreads this surface as open.

---

# A. Record authority determination

**Nothing is preselected.** Each category requires an explicit status.

**Status key:** `AUTHORITATIVE RECORD` · `REFERENCE ONLY` ·
`SUPERSEDED BUT RETAINED` · `NON-RECORD / DISPOSABLE` · `NOT DETERMINED`

| Category | Status | Accountable owner | Basis | Retention requirement | Legal / regulatory / business basis | Evidence | Effective date |
|---|---|---|---|---|---|---|---|
| Checklist records | | | | | | | |
| Approval-state fields | | | | | | | |
| Signature images | | | | | | | |
| Applicant details | | | | | | | |
| Responsible-person details | | | | | | | |
| US-agent details | | | | | | | |
| Uploaded / supporting files (§2.3 — 19 fields, 17 targets) | | | | | | | |
| SQLite data (§3 — five files) | | | | | | | |
| Generated outputs / reports | | | | | | | |

> **`NOT DETERMINED` is a valid entry and is the current state of every row.** It
> is not a failure to complete the form; it is the honest answer until an owner
> decides. What is not valid is leaving a row blank and proceeding as though it
> read `NON-RECORD`.

# B. Disposition decision

**One per record category.** Nothing preselected.

`[ ] RETAIN AND FREEZE`  `[ ] MIGRATE WITH PROVENANCE`
`[ ] ARCHIVE EXTERNALLY`  `[ ] DECOMMISSION AFTER RETENTION DECISION`

| Category | Disposition | Owner | Evidence | Effective date |
|---|---|---|---|---|
| Checklist records | | | | |
| Approval-state fields | | | | |
| Signature images | | | | |
| Applicant / responsible-person / US-agent details | | | | |
| Uploaded / supporting files | | | | |
| SQLite data | | | | |
| Generated outputs / reports | | | | |

## B.1 Consequences of each option — stated, not chosen

### RETAIN AND FREEZE

| Requirement | Decision |
|---|---|
| Read-only treatment — what enforces it | |
| No new approvals — how prevented | |
| No rewrites — how prevented | |
| Backups and retention | |
| Access control | |
| Owner responsibility | |

**The only option requiring no new tooling** (§2.5). That is a fact about cost,
not a reason to choose it.

### MIGRATE WITH PROVENANCE

| Requirement | Decision |
|---|---|
| Exact source record ID | |
| Source database / file (which of the five, §3) | |
| Legacy state preserved verbatim | |
| Migration timestamp | |
| Checksum | |
| Imported-by identity | |
| **Original approval strings preserved as source data** | |
| **No conversion into synthetic REGX workflow events** | |
| Signature treatment | |
| Record mapping (legacy → REGX) | |
| Validation / reconciliation requirement | |

> **Migration provenance is not audit history.** Recording *that* a row was
> imported, from where, when and by whom is provenance. Emitting REGX workflow
> events dated to the original legacy approval is fabrication. See §E.

### ARCHIVE EXTERNALLY

| Requirement | Decision |
|---|---|
| Archive format | |
| Checksum | |
| Index | |
| Retrieval method | |
| Retention duration | |
| Access owner | |
| **Restoration and readability verification** | |

> An archive nobody has proven they can restore and read is not an archive. The
> readability check is part of the disposition, not a later nicety.

### DECOMMISSION AFTER RETENTION DECISION

| Requirement | Decision |
|---|---|
| **Prerequisite retention decision** (§I) | |
| Export / archive evidence | |
| Disposal approval | |
| Backup state — what happens to the five files and to backups | |
| Deletion scope — exactly what is deleted | |
| Approval authority | |
| Irreversible-action controls | |

> **This option is irreversible.** It requires §I complete first, and the
> prerequisite is a hard gate, not a recommendation.

# C. Approval-state semantics

**Current legacy fact.** Seven approval levels per model are stored as
`CharField(max_length=5)` with declared choices `'False'`, `'True'`, `'Done'`,
defaulting to `'False'` — three states in a field shaped like a boolean, across
7 models and 231 references in `views.py`.

> **Engineering does not infer what these strings mean.** `'True'` is not read as
> *approved*; `'Done'` is not read as *completed*, *signed*, *reviewed* or
> *rejected*. The owner defines the business meaning, and until then the values
> carry no interpretation in any downstream system.

**Define the business meaning of each value.** If meanings differ by level,
complete per level.

| Value | Business meaning | Differs by level? | Per-level detail if it differs |
|---|---|---|---|
| `'False'` | | | |
| `'True'` | | | |
| `'Done'` | | | |

**Are these state values themselves authoritative?**

`[ ] YES`  `[ ] NO`  `[ ] PARTIALLY`  `[ ] NOT DETERMINED`

| Field | Value |
|---|---|
| If **PARTIALLY** — exact fields, models and processes that are authoritative | |
| Owner | |
| Evidence | |
| Effective date | |

# D. Signature images

| Question | Decision |
|---|---|
| Are signature images **records**? | |
| Do they represent legally or electronically valid signatures? | |
| Retention period | |
| Who may access them | |
| May they be migrated? | |
| Must image metadata be preserved? | |
| **Can the relationship to the signed record be proven?** | |
| **What happens if that relationship cannot be proven?** | |
| Owner | |
| Evidence | |

> **These are not described as Part 11 signatures, and no signer intent is
> inferred.** They are image files stored on a model that also holds applicant and
> named-person details (§2.2). Whether they constitute signatures in any legal or
> regulatory sense is exactly what this section asks the owner to determine — it
> is not established by the field name, the folder name, or their presence.

# E. Historical audit absence

**Factual boundary.** Legacy RATools does **not** provide the REGX immutable audit
architecture. There is no audit log, no event history and no change record for
approval-state transitions or signature uploads — **0 audit classes measured at
this SHA** (§2.4). Approval state changed across 231 touchpoints with no trail.

> The absence of centralized audit coverage in legacy RATools is a **documented
> governance exposure**. It is **not** evidence that historical approvals are
> invalid, and it does **not** justify retroactively fabricating audit history.

**Owner acknowledgment — historical event-level reconstruction:**

`[ ] PROHIBITED`  `[ ] OTHER — explain below`

| Field | Value |
|---|---|
| If OTHER, explain | |
| Owner | |
| Evidence | |
| Effective date | |

> ## No synthetic audit backfill shall be created
>
> **No synthetic or reconstructed audit event shall be written for any historical
> approval change, signature upload or checklist transition — unless a separately
> approved policy explicitly authorises a non-audit annotation process, clearly
> labelled as such and never presented as contemporaneous audit history.**
>
> An audit trail invented after the fact is worse than an acknowledged absence,
> because it asserts a record that was never made.

**The distinction to preserve:**

| Migration provenance | Fabricated audit history |
|---|---|
| Records that a row was imported | Claims an event occurred at a past time |
| Timestamped at **migration** time | Timestamped at the **original** time |
| Asserts what engineering did | Asserts what a person did |
| **Legitimate and required** | **Prohibited** |

# F. Data inventory

Built from repository findings at this SHA. **Record counts are blank — they were
not measured.**

| Model / table / file | Path | Record type | Approval fields? | Signature fields? | Personal / business data? | Current route exposure | Write-capable surface? | Likely disposition dependency | Owner decision required |
|---|---|---|---|---|---|---|---|---|---|
| `ANDAUserReports` | `RATools/models.py` | Checklist record | **Yes** (7 levels) | No | Yes | ANDA CRUD routes | Yes | Authority + retention | §A, §B, §C |
| `DMFChecklistUser` | `RATools/models.py` | Checklist record | **Yes** (7 levels) | No | Yes | DMF/IIG CRUD routes | Yes | Authority + retention | §A, §B, §C |
| `IIGChecklistUser` | `RATools/models.py` | Checklist record | **Yes** (7 levels) | No | Yes | DMF/IIG CRUD routes | Yes | Authority + retention | §A, §B, §C |
| `ProductComparison` | `RATools/models.py` | Checklist record | **Yes** (7 levels) | No | Yes | Checklist routes | Yes | Authority + retention | §A, §B, §C |
| `ValidationUserReports` | `RATools/models.py` | Checklist record | **Yes** (7 levels) | No | Yes | Validation CRUD routes | Yes | Authority + retention | §A, §B, §C |
| `VPUserReports` | `RATools/models.py` | Checklist record | **Yes** (7 levels) | No | Yes | VP CRUD routes | Yes | Authority + retention | §A, §B, §C |
| `GeneralChecklistUSer` | `RATools/models.py` | Checklist record | **Yes** (7 levels) | No | Yes | Checklist routes | Yes | Authority + retention | §A, §B, §C |
| `CCTemplate` | `RATools/models.py` | Applicant / correspondence record | No | **Yes** (`signatures/`) | **Yes** — applicant, responsible person, US agent, contact details | Template routes | Yes | Signature determination | §A, §B, §D |
| Other models (38 classes total) | `RATools/models.py` | Mixed | No | No | Varies | Various | Varies | Authority | §A |
| Uploaded files — **13 ImageField, 6 FileField, 17 targets** | `company_site/media/…`, `logos/`, `signatures/` | Supporting files | n/a | `signatures/` only | Likely | Served via media | Yes | Retention + archive | §A, §B, §I |
| `db.sqlite3` | `company_site/` | **Live database** | Contains all above | Contains | Yes | Backs every route | Yes | All | §A, §B, §I |
| `db.sqlite3.bak` | `company_site/` | Unknown | Unknown | Unknown | Unknown | Not referenced | No | Provenance first | §A, §B |
| `db_17_1_2.sqlite3` | `company_site/` | Unknown | Unknown | Unknown | Unknown | Not referenced | No | Provenance first | §A, §B |
| `db_corrupted.sqlite3` | `company_site/` | Unknown | Unknown | Unknown | Unknown | Not referenced | No | Provenance first | §A, §B |
| `db_old.sqlite3` | `company_site/` | Unknown | Unknown | Unknown | Unknown | Not referenced | No | Provenance first | §A, §B |

# G. Route / surface classification

Re-verified at this SHA against **both** URLconfs — see §4, which carries the
measured counts and the project-level routing that an app-only scan misses.

| Class | Count | Removable? |
|---|---:|---|
| live-required | 13 app + **4 project-level** | **No** — includes the site root |
| superseded-but-live | 147 | **No** — see below |
| dead-unreachable | 0 live routes (2 commented entries) | Commented text only |
| migration-dependent | all data-backed routes | Blocked on §B |
| governance-sensitive | overlays 103 | Blocked on §A, §C, §D |

> **Superseded is not equivalent to removable.** REGX having a newer equivalent
> says nothing about whether the legacy surface is the only place a record exists,
> the only page a link points at, or the only thing serving a URL somebody uses.
> **No live route, view, model, template, approval field, signature record or
> database table is safe to remove on current evidence.**

# H. REGX relationship

**No option is chosen here.**

| Question | Decision | Owner | Evidence |
|---|---|---|---|
| May REGX replace this legacy function? | | | |
| May historical data be imported into REGX? | | | |
| May legacy approvals appear in the REGX UI? | | | |
| If displayed, must they be labelled legacy? | | | |
| May REGX workflow status coexist with legacy status? | | | |
| **Which system is authoritative after transition?** | | | |
| Cutover date, if any | | | |
| Dual-running period, if any | | | |

> If legacy approvals are ever displayed in REGX, §C must be answered first —
> displaying `'Done'` in a REGX surface asserts a meaning that has not been
> defined.

# I. Retention / destruction

**No period is proposed here.** Inventing one would be engineering setting a
retention policy.

| Requirement | Decision | Owner |
|---|---|---|
| Retention period by record category | | |
| Retention start trigger | | |
| Legal hold handling | | |
| Backup retention (see [BACKUP_RESTORE_DR.md](BACKUP_RESTORE_DR.md)) | | |
| Archive readability requirement | | |
| Destruction authority | | |
| Destruction evidence | | |
| Irreversible-action approval | | |

# J. Owner / approval

**No named individual may be invented, and none is.** Every line is blank because
the repository names no person for any of these roles.

| Role | Named person |
|---|---|
| Business owner | |
| Data owner | |
| QA / regulatory owner, if applicable | |
| IT owner | |

| Field | Value |
|---|---|
| Decision version | |
| Approval evidence | |
| Effective date | |

---

## Engineering handoff criteria

**No P13c engineering starts until every applicable line is complete.**

| # | Required |
|---|---|
| 1 | **Authority status decided** per category (§A) — `NOT DETERMINED` does not satisfy this |
| 2 | **Disposition selected** per category (§B) |
| 3 | **Signature treatment decided** (§D) |
| 4 | **Approval-state semantics decided** (§C) |
| 5 | **Retention defined** (§I) |
| 6 | **System-of-record relationship defined** (§H) |
| 7 | **Migration / archive requirements defined**, if applicable (§B.1) |
| 8 | **Accountable owners named** (§J) — a named person, not a role |
| 9 | **Approval evidence exists** — the approval itself |

## Engineering rejection criteria

Return the package if any of these occur.

| Rejected | Why |
|---|---|
| **"Old system, delete it" is the only rationale** | Age is not a disposition basis; supersession is not removability |
| **"Migrate everything" without record mapping** | Without a legacy→REGX mapping, migration invents relationships |
| **String states interpreted without owner definition** | `'Done'` has no defined meaning; reading one is engineering deciding a business fact |
| **Signature validity assumed** | Neither the field name nor the folder establishes legal or electronic validity |
| **Retention period absent** | Destruction and archive both depend on it |
| **No owner named** | A role with no name cannot approve anything |
| **Synthetic audit backfill requested as normal migration** | Provenance and history are different; see §E |
| **Authoritative system after cutover unspecified** | Two systems both believing they are authoritative is worse than either alone |
| **Archive proposed without retrieval / readability plan** | An unverifiable archive is not a retained record |
| **Decommission proposed without retention / destruction approval** | Irreversible action without the prerequisite gate |
| **Route classification based only on the app URLconf** | Misses the four project-level routes, including the site root — the exact error §4 re-verifies against |
| **Superseded treated as equivalent to removable** | The most common and most costly error in this area |

## Boundaries preserved

* **RETAIN AND FREEZE remains the default** until a decision exists.
* **No synthetic audit backfill.**
* **The absence of audit coverage does not prove historical approvals invalid.**
* **No deletion or rewrite by assumption.**
* **No 21 CFR Part 11 claim** — none is made here, and signature images are not
  described as Part 11 signatures.
* **No regulatory conclusion is created by this document.**

## What this document does not do

It modifies no RATools code, model, route, template, approval field, signature
record, uploaded file or SQLite database. It deletes nothing, migrates nothing
and rewrites nothing. It names no owner, records no approval, and fills no
decision field. It interprets no approval string, asserts no signature validity,
proposes no retention period, and creates no audit record of any kind.

## Standing non-claims — preserved unchanged

1. **No 21 CFR Part 11 compliance claim.** An immutable audit mechanism is not
   compliance, and nothing here asserts one for legacy or current systems.
2. **No validated-production claim for the calculation engine.** Unchanged and
   unrelated to this document.
3. **No regulatory conclusion from any gap report.** Gap reports record what the
   repository contains and what is missing; they determine no regulatory status.
