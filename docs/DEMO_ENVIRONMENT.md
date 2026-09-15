# Demo environment

How to get a RegX environment you can actually click through, from a clean
clone. This is a developer/handoff document, not a deployment guide.

## Setup

```bash
git clone https://github.com/Praverse-Tech-Pvt-Ltd/RegX.git
cd RegX
git checkout regx-main          # NOT `main` -- that is the legacy monolith
cp .env.example .env            # generate the four required secrets
docker compose up -d
docker compose exec backend python manage.py migrate
docker compose exec backend python manage.py seed_regx_demo
```

`migrate` is not run on container start; healthy is not the same as migrated.

The seed prints a generated password unless you pass one:

```bash
# stable password across runs
docker compose exec backend python manage.py seed_regx_demo --password-env DEMO_PW

# see what it would do, then roll back
docker compose exec backend python manage.py seed_regx_demo --dry-run
```

| Flag | Purpose |
|---|---|
| `--tenant-slug` | tenant to create or reuse (default `demo`) |
| `--password` / `--password-env` | pin the demo password; otherwise one is generated and printed |
| `--dry-run` | report what would be created, then roll back |

**Idempotent.** Run it as often as you like; a second run reports
`Already seeded; nothing to create.` and emits no further audit events.

## Demo accounts

All on `demo.regx.invalid`, a reserved domain that never resolves.

| Account | Role | Can do |
|---|---|---|
| `doer@demo.regx.invalid` | doer | create and submit checklists, executions, workflows |
| `reviewer@demo.regx.invalid` | reviewer | review executions, enter conclusions |
| `vp@demo.regx.invalid` | vp | approve and activate versions, approve executions, export |
| `tenant_admin@demo.regx.invalid` | tenant_admin | view; **not** a superuser of the domain |

## What gets created

One object per domain, chained the way the product chains them:

```
tenant + 4 users/roles
  └── formulation (approved) ──┐
  └── IIG checklist v1 (ACTIVE) ┴── sample execution
  └── regulatory case RC-000001
        ├── workflow (SUBMITTED)
        ├── dossier ◄── instantiated from ACTIVE blueprint version
        └── package (DRAFT, internal)
  └── governed document (via the real ingest path)
  └── connector (DRAFT, disabled)
```

Everything is prefixed `DEMO-` and every description says it is synthetic.

**Created through the real services, not by writing rows.** The checklist
version walks `draft → under_review → approved → active` through the actual
API views; the workflow moves through `perform_transition`; the blueprint
version is activated through `activate_version`; the dossier is stamped by
`instantiate_version` with provenance intact. Each emits the same audit event
a user action would — 18 audit rows on a clean seed.

## A safe demo flow

1. Sign in as **doer** — the sidebar shows the governed modules
2. **Regulatory Cases** → open `RC-000001` → its dossier and package panels
3. **IIG Checklists → Executions** → open the sample execution, answer, submit
4. Sign in as **vp** → approve the execution (a reviewer conclusion note is
   required — that is the domain, not a bug)
5. **Dossier Blueprints** → the demo blueprint, version ACTIVE
6. **Submission Operations** → read-only overview across cases and dossiers

## What is deliberately NOT seeded

**No frozen package.** The demo package stays DRAFT. Freezing produces an
immutable artifact with a manifest and checksum, and its only evidence here is
a synthetic document. See the scanner note below.

**No upgrade plan.** `dossier_upgrades` has a full sanctioned lifecycle
(`generate_plan` → `set_item_status` → `mark_ready` → `apply_plan`), but a
seeded plan that is re-derived on every run is difficult to keep idempotent
without suppressing a governed transition. Left out rather than half-done.

**No FDA / Orange Book data.** Those tables are empty and their pages have
honest empty states. Importing official source data is a separate exercise
with a real source file; the seed fabricates nothing.

**No production regulatory content is touched.** The six platform checklist
definitions that ship with the database are left exactly as they are. The seed
creates and activates only its own `DEMO-` definition — activating shipped
content would silently promote unreviewed material into an executable state.

## Known limitations

### The document scan is only as real as your scanner

The seed uses `ingest_new_document` and **never writes `scan_status`**. What
you get depends on what is running:

| Environment | Result | Meaning |
|---|---|---|
| No Celery worker | `pending` | nothing has scanned it yet |
| Local compose (StubScanner) | `clean` | **nothing was inspected** |
| ClamAV configured | `clean` / `infected` | a real scan happened |

`DOCUMENT_SCANNER_ALLOW_STUB=true` in `compose.yaml` is what lets the local
stack run the stub. **A `clean` result under StubScanner is not evidence of
malware inspection.** See `docs/MALWARE_SCANNING.md`.

This has a visible consequence: `add_entry` refuses a document version that is
not scanned clean, so with no worker running the demo package is DRAFT **with
no entries**. That is the governance layer working, not a seeding failure.

### The formulation is approved by direct write

`FormulationVersion` is created with `status="approved"` through the ORM,
because the formulations app has **no approval transition service and no
writable status field** — `FormulationVersionSerializer` sets
`read_only_fields = fields`. This is what the app's own test suite does. It is
the one place the seed does not use a sanctioned service, recorded here rather
than papered over with an invented approval helper. Everything else in the
chain goes through its domain's service.

### Resetting

Governed records are deliberately not deletable — packages, blueprints,
documents and cases all refuse `delete()`. To start over, use a fresh
database rather than trying to unpick rows:

```bash
docker compose exec postgres psql -U regx -d postgres \
  -c "DROP DATABASE IF EXISTS regx;" -c "CREATE DATABASE regx OWNER regx;"
docker compose exec backend python manage.py migrate
docker compose exec backend python manage.py seed_regx_demo
```

## Where the command lives

`backend/demo_seed/` — an app with no models, no migrations, no URLs and no
runtime behaviour. It exists because the command composes every domain, and
the import-linter contracts stop any domain app from importing that widely:
`iig_checklist`, where this started, may not import `submission_packages`,
`dossier_upgrades` or `external_integrations`.

`demo_seed` is a composition root: it imports everything, and the
`nothing-depends-on-demo-seed` contract enforces that nothing imports it back.

## This is demo data

Synthetic content for demonstration and development. It is not regulatory
content, contains no real product or substance data, and establishes no
Part 11 compliance, validated-system status or agency acceptance.
