# Submission Packages

**A controlled internal assembly of exact document versions, and the frozen
manifest that records it.**

> **A PACKAGE NEVER FOLLOWS "LATEST".** Every entry binds to a
> `DocumentVersion`, never to a `Document`. Uploading a new version of a cited
> document changes nothing about any package that already cites an earlier one.

> **FROZEN IS AN INTERNAL REGX STATE.** It means the manifest can no longer
> change. It is not QA approval, regulatory approval, agency acceptance, or a
> statement that anything is ready to file. There is deliberately no APPROVED
> state.

> **No agency format ships.** No eCTD, no sequence generation, no XML backbone,
> no regional module, no NeeS, no ESG or gateway transmission, no FDA or EMA
> validation, no completeness determination, no electronic signature, no Part 11
> or GxP claim. A package is a manifest and a ZIP of files the tenant chose.

Stacked on Milestone 12 (`regx/feat/submission-operations-dashboard`), branched
from `12ea1552e4f88b242c8a6c62b5b76d9f862a7b10`. **Must not merge before M12,
which must not merge before M11, M10 and M9 in that order.**

---

## 1. The core principle

A package answers one question permanently: *which exact bytes were assembled,
and when*. Everything else in this milestone exists to make that answer hold.

```
Document ─┬─ v1  ◄── package entry binds HERE
          ├─ v2       (uploading v2 changes nothing)
          └─ v3
```

`workflows.WorkflowEvidence` established this pattern for citing one exact
version; a package is the same idea for a set of them, with a manifest over the
whole set. `submission_dossiers.DossierSectionDocument` deliberately does the
opposite — it targets `Document` and follows its versions, because structural
membership is a different question from "which bytes did this cite".

The guarantee is a foreign key, not a rule somebody has to remember.

## 2. Lifecycle

```
DRAFT      ──► IN_REVIEW, CANCELLED
IN_REVIEW  ──► DRAFT, FROZEN, CANCELLED
FROZEN         terminal
CANCELLED      terminal
```

There is **no unfreeze and no reopen**. A manifest that can be reopened is not a
manifest; it is a draft with a checksum attached. Changing a frozen package
means cloning it into a new DRAFT, which leaves the original exactly as it was.

Freezing is reachable only from IN_REVIEW. It is permanent, so it is always a
second deliberate act rather than something that can happen straight out of
assembly — and the database enforces the same table, so the service and the
floor cannot disagree.

Entries may be added, reordered and retired **only while DRAFT**.

## 3. Eligibility

An entry may cite a version only if `scan_status == CLEAN`.

That is stricter than the document platform's serve-time check, which blocks
only QUARANTINED — and deliberately so, matching what `workflows` requires to
cite a version as governed evidence. Serving a PENDING version to the person who
just uploaded it is reasonable; freezing it into a permanent manifest is not.
INFECTED, SCAN_FAILED and SCANNER_UNAVAILABLE are non-conclusions, not
clearances. No new security status is invented; this reads `documents.ScanStatus`
as it stands.

**One message covers absent, cross-tenant and not-cleared.** Distinct messages
would let a caller probe for documents outside their tenant and would disclose
the scan state of one they cannot see — the Milestone 8 existence-oracle lesson.

## 4. Permissions

| Codename | Granted to |
|---|---|
| `.view` | DOER, REVIEWER, VP, TENANT_ADMIN, PLATFORM_SUPPORT |
| `.create` | DOER, TENANT_ADMIN |
| `.edit` | DOER, TENANT_ADMIN |
| `.manage_entries` | DOER, TENANT_ADMIN |
| `.review` | DOER, REVIEWER, TENANT_ADMIN |
| `.freeze` | REVIEWER, VP, TENANT_ADMIN |
| `.cancel` | VP, TENANT_ADMIN |
| `.export` | DOER, REVIEWER, VP, TENANT_ADMIN |

**Package permission is never document permission.**

| Operation | Gates |
|---|---|
| create | `submission_packages.create` + `regulatory_cases.view` |
| add entry | `submission_packages.manage_entries` + `documents.view` |
| export | `submission_packages.export` + `documents.view` |
| manifest | `submission_packages.view` + `documents.view` |

Target-domain gates are checked **before the target is resolved**, so absent /
cross-tenant / unauthorised are one indistinguishable outcome.

### The document projection

A caller may hold `submission_packages.view` and not `documents.view`. The entry
still appears — the package is theirs to see — and its `document` block is
`null`: no title, no filename, no checksum, no version, no scan status. `null`
means *you are not entitled to know*, exactly as on the operations dashboard,
and the UI renders "Unavailable" rather than a blank cell.

**The manifest endpoint is part of that projection, not an exception to it.**
The frozen manifest names every cited document, its exact version, its SHA-256
and its size — the very fields the detail endpoint blanks. Served under package
permission alone it would have been a way around the projection, so it requires
`documents.view` as well.

The gate is checked **after** the tenant-scoped lookup. Checking it first would
answer 403 for a package in another tenant and thereby confirm the package
exists; a foreign package and a missing one stay one indistinguishable 404 for
every caller.

The stored snapshot is never redacted to accommodate anyone. A manifest with
fields removed is a second, differently-hashed document claiming to be the
manifest, and the checksum is the whole point — so the choice is the real
manifest or nothing.

### Export is all or nothing

If the caller cannot retrieve the documents, the **entire** export is refused. A
ZIP silently missing one of ten files looks complete to whoever receives it,
which makes a partial export worse than no export.

## 5. Logical paths

Tenant-defined and **carrying no regulatory meaning**. `01-cover/` is an example,
not a standard, and nothing in the codebase knows what any path means. No CTD,
eCTD, CEP, DMF or ANDA folder structure ships or is inserted.

`documents.validators.validate_filename` is the right model and the wrong tool —
it validates a single uploaded filename against an extension allow-list and
rejects every separator, which is useless for a path made of separators. Its
traversal rules are reproduced in `paths.py`; its extension policy is not.

Refused, each for a reason:

| Refused | Why |
|---|---|
| `..` anywhere | zip slip — `../../etc/x` escapes the extraction root |
| absolute paths, `C:\` | extract to a fixed location rather than under the target |
| backslashes | a Windows extractor treats `a\b` as a separator |
| UNC `\\server\share` | a network location, not a relative path |
| NUL, control bytes | truncate the path in any C-level API downstream |
| trailing dot or space **in a segment** | Windows silently strips them, so `a ` and `a` become one directory |
| `CON`, `NUL`, `COM1`… | Windows devices, whatever extension follows |
| depth > 10, length > 400 | an unbounded path is a denial-of-service on the extractor |

Collapsed rather than refused: `a//b`, `a/./b`, a trailing slash, and whitespace
around the **whole** path — each is unambiguous, and normalising keeps duplicate
detection honest.

### Collision is a separate question from validity

Two *valid* paths can still collide once extracted. `Docs/` and `docs/` are the
same directory on macOS and Windows; NFC and NFD spellings of `café` render
identically. So normalisation returns the stored path and duplicate detection
compares a **collision key** — NFKC-normalised and `casefold()`ed. `casefold()`
rather than `lower()`, because `lower()` leaves the German sharp s alone and
`STRASSE`/`straße` would compare unequal here and collide on disk.

Uploaded filenames are never used as path components directly:
`sanitize_export_filename` replaces anything unsafe rather than refusing, so a
package cannot become un-exportable over a character in a filename somebody
uploaded a year ago.

## 6. The manifest

Canonical JSON, SHA-256 over the exact bytes.

Determinism is the whole point, so:

- `sort_keys=True`, `separators=(",", ":")` — no whitespace or key order to vary
- `ensure_ascii=False` + UTF-8 — a non-ASCII path hashes as the characters it is
- entries sorted by `(sequence, entry public_id)` — the user's arrangement, with
  a tie-break that does not depend on database row order
- **no timestamps inside the hashed structure** — `frozen_at` lives on the
  snapshot row beside the checksum, not inside the bytes it covers, or the same
  package could never hash the same way twice
- no database primary keys anywhere

`repr()` is never used; its output is a Python implementation detail.

Each entry records: entry public id, sequence, logical path, export filename,
document public id, **document version public id**, version number, SHA-256,
size, MIME type, and the dossier section public id if any.

## 7. Freeze

One transaction, in order. A failure anywhere leaves no frozen status, no
snapshot, no checksum and no success audit.

1. lock the package
2. prove it is IN_REVIEW
3. lock the active entries, **by pk**, so two transactions agree on an order
4. **revalidate every document version**, with storage existence checked
5. build the canonical manifest and its checksum
6. write the immutable snapshot
7. set FROZEN and record the checksum
8. emit the success event

Step 4 is not politeness. A version can be quarantined, or a file can vanish,
between review and freeze — and after freeze the manifest is permanent, so this
is the last moment the claim can be checked at all.

### Lock order

```
1. SubmissionPackage — family root    clone only; see below
2. SubmissionPackage — the row itself the serialization point
3. SubmissionPackageEntry             by pk
4. DocumentVersion                    read; documents owns its own locks
```

The package row is why exactly one freeze can win and why no entry can be added
into a package mid-freeze.

**Cloning needs a wider lock than that.** Revision numbers are unique per
*family*, and two clones of two different revisions lock two different package
rows — so the row lock serialises nothing between them, and both can read the
same highest revision and claim it. The family root is locked first, and every
clone in a family resolves to the same root row whichever revision it started
from. Root-before-source is a total order within a family, so two clones queue
rather than deadlock.

## 8. Integrity

`GET /submission-packages/{id}/validate/` — **internal package integrity only**.
Deliberately not named `regulatory-validate` or `submission-validate`: it knows
whether the package can be exported, and nothing about whether it should be.

Enumerated codes, never prose: `no_active_entries`,
`document_version_unavailable`, `scan_not_cleared`, `checksum_missing`,
`duplicate_path`, `tenant_mismatch`, `case_mismatch`, `section_retired`,
`storage_unavailable`, `too_many_entries`, `too_large`.

Every problem is returned, not the first one — and freeze uses the same function,
so the two can never disagree about what "valid" means.

Export bounds (`SUBMISSION_PACKAGE_MAX_ENTRIES`, `SUBMISSION_PACKAGE_MAX_TOTAL_BYTES`)
are settings-overridable and deliberately generous: they exist so no extractor is
handed something absurd, not to express a policy about package size.

## 9. Export

A ZIP with `manifest.json` at the root and files under `files/<logical-path>/`.
**An internal container, not an agency format.** Nothing inserts a folder name
that means something to a regulator.

- The manifest written is the **stored snapshot**, not one recomputed now.
- Every file is streamed in 1 MiB chunks and **hashed as it goes**, then compared
  against the checksum the frozen manifest recorded. If the stored bytes have
  changed, the export fails rather than shipping an archive whose manifest is a
  lie about its own contents. That is a real verification, not a metadata check.
- **The frozen snapshot is the authority — never the live `DocumentVersion`.**
  Expected checksum, size, version identity, logical path and export filename all
  come from `snapshot.manifest`, keyed by entry. The live row is used for exactly
  one thing, finding the object, and is never trusted to describe it.
- The entry sets must match: every active entry is named in the manifest exactly
  once, the manifest names nothing extra, and the count agrees with
  `snapshot.entry_count`. Any drift fails the export closed.

#### Why that distinction is reachable

`DocumentVersion.sha256_checksum`, `size_bytes` and `storage_key` carry **no**
database immutability trigger. This app's own tests already rewrite `storage_key`
with a plain `objects.update()`. If a bug, a migration or a raw cursor rewrote
all three together after a freeze, an exporter comparing streamed bytes against
*today's* metadata would find perfect agreement and ship an archive whose files
contradict the `manifest.json` beside them.

This is **not** a claim that `DocumentVersion` is immutable. The database does
not prove that today, and the snapshot is treated as the authority precisely
because the live row cannot be.
- Archive names are re-checked at write time even though `normalize_logical_path`
  refused all of it at entry time: the value has been through a database
  round-trip and a manifest since, and the cost of being wrong is an archive that
  escapes its extraction directory on someone else's machine.
- Case-insensitive duplicate detection, because the extractor's filesystem
  probably is.
- No symlinks, no absolute entries, no traversal.
- Written to a temporary file rather than an in-memory buffer: a package is many
  documents, and holding all of them in RAM to serve one download is how a large
  export takes the process down.

**No storage duplication.** Freezing copies nothing; the package is exact
references plus an immutable manifest, and the ZIP reads existing controlled
storage. There is no second file lifecycle to manage or back up.

Exports are generated on demand and audited. The snapshot is persistent; the ZIP
is not stored, because a second copy of bytes the document platform already owns
would be a retention question nobody has answered.

## 10. Clone and revision

A frozen package never reopens. `clone` copies it into a new DRAFT: new
`public_id`, the next `revision_number` in the family, `source_package` pointing
at what it copied, `family_root` naming the package that started the family, and
the same **exact** version references.

### The revision family

Revision numbers are unique within a family, so "which family" has to be a
question the database can answer. Two other answers were rejected:

- **`tenant + case + name`.** A package name is display text a user may edit at
  any time. Keying revisions on it means a rename silently forks one family into
  two — or merges two and collides their numbers. Identity may not depend on a
  mutable label.
- **Walking `source_package` at read time.** Correct but unlockable: a query per
  hop, and a concurrent clone can extend the chain mid-walk, so two transactions
  can disagree about the row they are supposed to be serialising on.

`family_root` is written once at insert and frozen by the update guard
thereafter. A founder stores `NULL` — a row cannot reference its own primary key
before that key exists — so the family of any package is
`COALESCE(family_root_id, id)`, and that expression is what both the uniqueness
index and the clone lock use.

**A rename does not fork the family.** `clone(name=...)` gives the copy different
display text and leaves it in the same family at the next revision.

### The real topology

```
source_package : a TREE   two clones of one frozen revision are both legitimate
revision_number: LINEAR   within a family, and now a unique index
```

Earlier comments called `source_package` "a chain, not a tree". The schema never
enforced that, so the claim is withdrawn rather than enforced retroactively —
adding a constraint to forbid branches would break a working feature to make a
comment true. What the schema does enforce is
`unique_revision_per_package_family` over
`(COALESCE(family_root_id, id), tenant, revision_number)`.

The service takes the family-root lock; the index is the floor under it, and
holds for a transaction that never took the lock — a raw cursor, a psql session,
a future code path nobody re-reviewed.

Entry references are copied even when a version would no longer be eligible
today. That is deliberate — the clone starts as a faithful picture of what was
frozen, so the user can see what has to be replaced, and freeze refuses until
they do. The refusal belongs at the moment something permanent is written, not
at the moment someone asked to look.

`revision_number` is internal. **It is not an agency sequence number** and no
external meaning may be read into it; the field is deliberately not called
`submission_sequence`.

## 11. Database governance

`0002` — 7 plpgsql functions, 7 triggers. `0003` — one added, one replaced.

| Trigger | Enforces |
|---|---|
| `guard_update_package` | identity and provenance frozen always; FROZEN/CANCELLED refuse every UPDATE; only the documented transitions; freeze stamps only written by a freeze |
| `no_delete_package` | packages are never deleted |
| `guard_insert_package_entry` | coherent on the way in: entry tenant = package tenant, version owned by that tenant, section on the package's own case, package still DRAFT |
| `guard_update_package_entry` | the binding is immutable; only removal and sequence may move, and only while DRAFT |
| `guard_delete_package_entry` | entries are retired, never deleted |
| `guard_insert_package_snapshot` | tenant coherence, checksum shape, entry count matches the package |
| `freeze_package_snapshot` | a manifest refuses UPDATE and DELETE outright |

`0003` adds one more, and replaces one of the above.

| Trigger | Enforces |
|---|---|
| `guard_insert_package` | family coherence on the way in: a founder has no source and is revision 1; a member names both a source and a family; the family root exists, is a root itself, and shares the tenant and the case; the source shares the tenant, the case and the family |
| `guard_update_package` *(replaced)* | as before, plus `family_root_id` in the immutable set — family membership is provenance, and a row that could change families could change which numbers it collides with |

The insert guards are the Milestone 10 lesson applied up front: freezing a row
that was never checked on the way in preserves whatever was written, not the
truth.

`Model.save()` resolves through `_base_manager` — a plain `Manager` Django
auto-creates, not `objects` — so restricting the public manager cannot cover a
bare `save()`, and a raw cursor never runs a line of Python. The triggers are the
floor, and the tests go around the ORM to prove it.

### What the database does not prove

The snapshot trigger checks that `manifest_checksum` is a 64-character lowercase
hex string and that the entry count agrees with the package. It does **not**
recompute SHA-256 over the JSON: doing that in plpgsql would mean reproducing
Python's exact canonical serialisation — key ordering, separators, Unicode
escaping — in a second language, and two implementations of a canonical form
drift. The cryptographic binding is proved by the freeze transaction and by the
manifest being immutable thereafter. Claiming otherwise would be claiming a
guarantee that is not there.

### Deletion protection

A `DocumentVersion` inside a package cannot be deleted: `on_delete=PROTECT` on
the FK, plus a `DeletionProtectionRegistry` checker registered from `apps.py` —
the same two-layer pair `workflows` uses for evidence, keeping the dependency
one-way so `documents` never imports this app. Removed entries count too: a
version that was once in a package is part of how that package came to look the
way it does.

## 12. Concurrency

| Race | Guard |
|---|---|
| Two simultaneous freezes | package row `select_for_update` + the transition trigger. Exactly one wins. |
| Freeze vs entry add | the package lock. The add lands before the freeze or is refused by it — never inside it. |
| Duplicate entry / path | partial unique index on `(package, document_version)` where active, plus the collision-key check under the lock |
| Two clones of the same revision | the source row lock |
| Two clones of **different** revisions of one family | the **family-root** lock, plus `unique_revision_per_package_family` as the floor |
| Export during a new upload | harmless by construction: the entry binds to an exact version |
| Export vs a rewritten `DocumentVersion` row | the frozen snapshot is the authority; live metadata is never trusted to describe the bytes |

Tested with real threads against PostgreSQL.

> **The clone race that the source lock did not cover.** Cloning r1 and r2 of
> the same family locks two *different* rows, so nothing serialised them and
> both could compute the same next revision. Removing the family-root lock now
> turns that test red — with a deadlock on the unique index, which is the floor
> refusing the duplicate the lock exists to prevent in an orderly way.

## 13. Migration classification

Per [`RELEASE_ROLLBACK_RUNBOOK.md`](RELEASE_ROLLBACK_RUNBOOK.md) §4.

| Migration | Forward | Rollback |
|---|---|---|
| `0001_initial` | **Class A** — three `CreateModel`s, no `RunPython`/`RunSQL`, no existing table altered | **CLASS C — DATA RESTORE REQUIRED** once any package data exists |
| `0002_package_db_governance` | **Class A** — 7 functions, 7 triggers; no table altered, no row read or written | **Class A on its own terms** |
| `0003_package_revision_family` | **Class A, conditional on the data** — one nullable column, one derivation, two constraints, one replaced and one added trigger function | **Class A** — the reverse restores exactly the prior state |

> Reversing `0001` destroys every package, every entry, and — irreplaceably —
> every frozen manifest and its checksum. A frozen manifest is the permanent
> record of exactly which document versions were assembled and when; it is not
> derivable from anything else, precisely because it does not change when the
> documents do. The document versions survive (the document platform owns them);
> the statement about which ones formed a package does not exist anywhere else.
>
> Removing `0002`'s protection does **not** make reversing `0001` safe. The
> relationship is one-way.

The `0002` counts are asserted against the generated SQL by a symmetry test that
ships **with the migration it describes** — M10 shipped a docstring claiming five
functions and eight triggers where the SQL had seven of each, and M11 claimed a
test covered its counts when the test lived in another app entirely.

### `0003`, in detail

**The forward condition.** `unique_revision_per_package_family` refuses to build
if a family already holds two packages with the same `revision_number`. The code
it replaces keyed revisions on `tenant + case + name`, so a package renamed
between two clones could have produced exactly that. Check before deploying:

```sql
SELECT COALESCE(family_root_id, id) AS family, tenant_id, revision_number, count(*)
  FROM submission_packages_submissionpackage
 GROUP BY 1, 2, 3 HAVING count(*) > 1;
```

Empty → Class A. Non-empty → the duplicates must be resolved by hand first;
which package keeps which number is a decision, not something a migration may
guess.

**Why a data step is still not class C or D.** The runbook's rule 1 flags
`RunSQL`/`RunPython` because a data migration usually destroys information a
restore has to bring back. This one destroys none: `family_root` is *derived*
from `source_package`, which the migration never touches. The reverse sets it
back to `NULL` and drops the column — exactly the prior state — and the forward
step can be recomputed at any time by running it again. A test does precisely
that: wipe with the reverse SQL, restore with the forward SQL, compare.

**It disarms a trigger, on purpose and by name.** `guard_update_package` refuses
every UPDATE to a FROZEN or CANCELLED row, so the derivation cannot run while it
is armed — a database holding one frozen package would fail the migration
outright. It is disabled by name for the length of the derivation and re-armed
in the same transaction, which is safe for one specific reason: `family_root_id`
is not new information, it is computed from `source_package_id`, which the guard
already holds immutable. The column is being *completed* for rows frozen before
it existed, not rewritten.

Two tests hold that window shut: one asserts the SQL disables and re-enables
exactly one trigger in both directions, and one reads `pg_trigger` after
migration to prove the guard is armed.

> Django declares foreign keys `DEFERRABLE INITIALLY DEFERRED`, and PostgreSQL
> refuses to `ALTER` a table with pending trigger events — so the re-arm needs a
> `SET CONSTRAINTS ALL IMMEDIATE` first. Without it the migration fails on any
> database that actually has clones and succeeds on one that does not, which is
> worse. The backfill test found this.

**Reversal is deliberately asymmetric.** `0003` *replaces* a function `0002`
created, so a symmetric reverse would `DROP FUNCTION
submission_packages_guard_package_update` and take `0002`'s protection with it.
The reverse restores `0002`'s body instead — imported from `0002` rather than
retyped, because two hand-maintained copies of the same plpgsql drift and the
one that drifts is the one nothing runs.

**One new trigger.** `guard_insert_package` checks family coherence on the way
in: a founder has no source and is revision 1; a member names both a source and
a family; the family root exists, is a root itself, and shares the tenant and
the regulatory case; the source shares the tenant, the case and the family.

## 14. Testing

**Backend (210)**: the exact-version guarantee at the service, the API and
inside the produced archive; manifest determinism and every way to change it;
freeze preconditions, transactionality and injected-failure rollback; frozen
immutability through the service, the ORM, `governed.update()` and raw SQL;
insert coherence; tenant isolation across every service and endpoint; the
document projection; path security including Unicode and case collision; export
integrity, ZIP safety and all-or-nothing authorisation; clone and revision;
real-thread concurrency; and query-cost invariance.

The review-fix module adds 44 more: the manifest's second gate and what its
refusal must not say; the frozen snapshot as the export authority, including
the mirror case where the live row is corrupted and the export must still
*succeed*; revision families, their database floor, their insert coherence,
and three real-thread clone races; plus the `0003` migration's own SQL run
forward and backward against rows the service built.

**Frontend**: 31 unit, 15 new accessibility checks (89 → 104), 16 Playwright.

### Mutation testing

Every guard turned tests red; all files restored md5-identical.

| Mutation | Red |
|---|---|
| Service tenant gate neutered | 3 |
| Export follows `document.current_version` | 2 |
| Manifest canonical ordering removed | 2 |
| Document permission gate removed | 1 |
| Freeze status gate removed | 1 |
| Path traversal check removed | 1 |
| Cross-case section validation removed | 1 |
| Export authorisation gate removed | 1 |
| Export checksum verification removed | 1 |
| **Manifest document gate removed** | 3 |
| **Export trusts live `DocumentVersion` again** | 2 |
| **Family-root lock removed from clone** | 1 |
| **`unique_revision_per_package_family` removed** | 3 |
| **`guard_insert_package` never attached** | 8 |

Two mutations initially turned **nothing** red, and both were real test defects:

- **Manifest ordering** — the determinism test reversed a list of one entry,
  which is the same list. It now uses three, and a second test asserts the
  documented ordering directly against a shuffled input.
- **Export authorisation** — the test asserted `403 or 404` for a caller who
  lacked *both* export and document permission, so it was proving that
  PLATFORM_SUPPORT cannot export, which was never in question. The gate is now
  isolated: the caller is granted `submission_packages.export` and still denied
  `documents.view`, with a control test proving an authorised caller does get the
  archive.

## 15. Regulatory boundaries

No production regulatory structure. No CTD, eCTD, CEP, DMF, ANDA, USFDA or EMA
content, rules, folder names or validation. No sequence generation, XML backbone,
regional envelope, NeeS structure or gateway transmission. No completeness
determination, regulatory approval, QA release, electronic signature, Part 11
compliance certification or validated-production claim. Synthetic codes
throughout. No change to the 20 governance decisions, the 0/20 approval state,
Item 1, the 13 owner-policy decisions, S1 or S2.

**Frozen means the internal manifest can no longer change. It means nothing
else**, and the screen says so in standing copy.
