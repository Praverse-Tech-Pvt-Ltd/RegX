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

Target-domain gates are checked **before the target is resolved**, so absent /
cross-tenant / unauthorised are one indistinguishable outcome.

### The document projection

A caller may hold `submission_packages.view` and not `documents.view`. The entry
still appears — the package is theirs to see — and its `document` block is
`null`: no title, no filename, no checksum, no version, no scan status. `null`
means *you are not entitled to know*, exactly as on the operations dashboard,
and the UI renders "Unavailable" rather than a blank cell.

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
1. SubmissionPackage          the serialization point
2. SubmissionPackageEntry     by pk
3. DocumentVersion            read; the document platform owns its own locks
```

The package row is why exactly one freeze can win and why no entry can be added
into a package mid-freeze.

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
`public_id`, `revision_number + 1`, `source_package` pointing at what it copied,
and the same **exact** version references.

Entry references are copied even when a version would no longer be eligible
today. That is deliberate — the clone starts as a faithful picture of what was
frozen, so the user can see what has to be replaced, and freeze refuses until
they do. The refusal belongs at the moment something permanent is written, not
at the moment someone asked to look.

`revision_number` is internal. **It is not an agency sequence number** and no
external meaning may be read into it; the field is deliberately not called
`submission_sequence`.

## 11. Database governance

`0002` — 7 plpgsql functions, 7 triggers.

| Trigger | Enforces |
|---|---|
| `guard_update_package` | identity and provenance frozen always; FROZEN/CANCELLED refuse every UPDATE; only the documented transitions; freeze stamps only written by a freeze |
| `no_delete_package` | packages are never deleted |
| `guard_insert_package_entry` | coherent on the way in: entry tenant = package tenant, version owned by that tenant, section on the package's own case, package still DRAFT |
| `guard_update_package_entry` | the binding is immutable; only removal and sequence may move, and only while DRAFT |
| `guard_delete_package_entry` | entries are retired, never deleted |
| `guard_insert_package_snapshot` | tenant coherence, checksum shape, entry count matches the package |
| `freeze_package_snapshot` | a manifest refuses UPDATE and DELETE outright |

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
| Two simultaneous clones | revision numbers claimed under the source package's lock |
| Export during a new upload | harmless by construction: the entry binds to an exact version |

Tested with real threads against PostgreSQL.

## 13. Migration classification

Per [`RELEASE_ROLLBACK_RUNBOOK.md`](RELEASE_ROLLBACK_RUNBOOK.md) §4.

| Migration | Forward | Rollback |
|---|---|---|
| `0001_initial` | **Class A** — three `CreateModel`s, no `RunPython`/`RunSQL`, no existing table altered | **CLASS C — DATA RESTORE REQUIRED** once any package data exists |
| `0002_package_db_governance` | **Class A** — 7 functions, 7 triggers; no table altered, no row read or written | **Class A on its own terms** |

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

## 14. Testing

**Backend (144)**: the exact-version guarantee at the service, the API and
inside the produced archive; manifest determinism and every way to change it;
freeze preconditions, transactionality and injected-failure rollback; frozen
immutability through the service, the ORM, `governed.update()` and raw SQL;
insert coherence; tenant isolation across every service and endpoint; the
document projection; path security including Unicode and case collision; export
integrity, ZIP safety and all-or-nothing authorisation; clone and revision;
real-thread concurrency; and query-cost invariance.

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
