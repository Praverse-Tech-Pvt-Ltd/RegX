# Company Runtime Assets — What Is Versioned and What Is Not

Companion to `BOOKING_FINAL_REGX_INTEGRATION_PLAN.md`. This records the
repository-size decision made before the integration branch was pushed, and
how to obtain the material that is deliberately **not** in Git.

## The rule

Version-control holds everything needed to *render the company website
faithfully*. It does not hold mutable runtime state, dead assets, or
data-import spreadsheets.

| Category | Path | Size | In Git? |
| --- | --- | --- | --- |
| B — required static assets | `company_site/static/img`, `static/assets`, `static/documents` | 399 MB | **Yes** |
| A — application source | `company_site/{RAAI,RATools,AIDatabase,AdminMaster}`, templates | 6.5 MB | **Yes** |
| G — demo database fixture | `company_site/db.sqlite3` | 7.1 MB | **Yes** (see below) |
| C — runtime media | `company_site/media/` | 196 MB | **No** |
| E — dead assets | `company_site/static/videos/` | 82 MB | **No** |
| D — data-import spreadsheets | `company_site/AIDatabase/management/commands/*.xlsx` | 14 MB | **No** |

Net effect: the tracked payload drops from **721 MB to 430 MB** without
removing a single asset any rendered page depends on.

## Why each exclusion is safe

### `company_site/media/` — 196 MB, 1006 files

These are FDA-483 observation images. They are **runtime media**, not source:
they are reached through `AIDatabase.models` `ImageField` rows, are displayed
only by `templates/AIDatabase/Form483/Form483Base.html`, and new uploads are
written by the running application to `new_observation_images/` rather than to
this legacy directory. Mutable, user-generated, per-deployment state does not
belong in version control.

They remain on the local filesystem and are **bind-mounted** into both
containers by `compose.yaml`:

```yaml
company_site:
  volumes:
    - ./company_site/media:/app/media      # read-write, app uploads land here
nginx:
  volumes:
    - ./company_site/media:/srv/company/media:ro   # served at /media/
```

So the local stack behaves exactly as before this change. A **fresh clone**
will not have them: Form 483 observation *detail* images will be missing until
the sync step below is run. Every other page — homepage, navbar, footer,
`/ratools/`, the RegX shell, Audit IQ listings — is unaffected, because none of
them reference this directory.

### `company_site/static/videos/` — 82 MB, 4 files

Four marketing `.mp4` files. The entire codebase contains exactly one
reference to any of them, and it is **commented out**:

```
templates/RATools/RAToolsBase.html:1638
  <!-- <a class="tt-button" href="{% static 'videos/iTechnicalTools - Final Video-v2.0.mp4' %}" ... -->
```

No template, view, CSS or JS links them. Three of the four are superseded
drafts of the same video. Nothing renders them, so nothing regresses.

### `AIDatabase/management/commands/*.xlsx` — 14 MB, 12 files

Source spreadsheets for one-off import commands (`import_form_483`,
`import_deficiency_data`, `import_major_cr`, …). They are inputs to a data
load that has already been performed — the resulting rows are in
`db.sqlite3`. They are never read during request handling.

They are also **client-named** ("… (For Cipla)"), so keeping them out of a
repository that may be shared more widely is the safer default regardless of
size. The commands themselves stay in Git; only their input data does not.

### Why `db.sqlite3` *is* kept

At 7.1 MB it is 1.6% of the payload, and it is the single artefact that makes
the deliverable demonstrable: the homepage's FDA-483 counters, Audit IQ and
all 217 gated legacy tools render from it. Without it the company site starts
but is inert.

It is treated as a **read-only demo fixture**, not as live state:
`docker-entrypoint.sh` copies it once onto the `company_db` named volume, and
the running application reads and writes the volume copy. The committed file
is never mutated by running the stack.

## Restoring the excluded material

The company source tree is read-only and is the authority for all three
categories. From the repository root:

```bash
scripts/sync_company_runtime_assets.sh "../Booking final/booking-demo-final"
```

The script only ever copies **from** the company tree and never writes to it.
Pass the path to your checkout of `booking-demo-final`; it defaults to the
sibling layout used during the integration.

For a deployment rather than a local demo, point `media/` at whatever object
storage the environment already uses and restore the database from a backup —
neither belongs in the image or the repository.

## Assets that are unreferenced but retained

The reference audit also found ~80 MB of company-authored images under
`static/img` and `static/assets/icretegy` with no reference from any template,
view, CSS or JS — including a 14.6 MB `RA tools image.png`, a 5.8 MB
`header.jpg`, and two byte-identical 4.4 MB copies of the iWalkTheTalk logo.

These are **kept**. They are the company's own brand and marketing material
rather than dead vendor boilerplate, and removing company assets purely to
save space is the client's call, not ours. The full list is reproducible with:

```bash
python scripts/audit_company_assets.py company_site
```
