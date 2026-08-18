# Release Verification and Rollback Runbook

**Scope: the technical procedure for deploying a RegX release, verifying it, and
backing it out.**

This is not a validation protocol, not a regulatory approval, and not business
acceptance. It defines technical pass/fail checks an operator can run. Who is
allowed to authorise a production deployment is a business, QA and IT decision —
see §12.

Verified against `regx-main` `686296ab9c2d5943f2cb50507b0bdf1bcc7e85ad`.

---

## 1. What existed before

Nothing described a deployment or a rollback. A search for `rollback` across the
docs returns almost entirely *transaction* rollback in design specs — a
different meaning. The only deployment-rollback sentence in the repository is a
single line in `MILESTONE_4D_2_IMPLEMENTATION_SPEC.md` §, saying
`python manage.py migrate iig_checklist 0001` would undo that milestone.
**§4 of this runbook shows why that class of instruction is unsafe as a general
rule** — it was demonstrated to fail.

Also established by inspection, not assumption:

| | |
|---|---|
| Deployment automation | **none** — no deploy or release workflow exists |
| Migrations | **not automatic**; the backend image runs `gunicorn` only, no entrypoint migrates |
| Replicas / rolling deploy | **none** — one container per service |
| Tags | three exist (`regx-document-platform-v0.2.0`, `regx-template-governance-v0.3.0`, `regx-fda-iid-foundation-v0.4.0`), milestone-named, with no policy |
| Frontend release doc | `docs/frontend/RELEASE_READINESS.md` — build and test only, nothing about deploying |

No deployment process is invented here. What follows is the sequence the
repository's own mechanisms require.

---

## 2. The release unit

**A release is one immutable git commit SHA.** Everything else is derived from
it: the backend image, the frontend image, the company-site image, the nginx
configuration, the migration set and the environment contract are all built or
read from that single checkout.

No semantic-version or tag policy is introduced. The three existing tags are
milestone markers, not a release scheme, and nothing depends on them.

> **Limitation.** Nothing stamps a commit into a running image, and
> `APP_VERSION` is not wired into `compose.yaml`, so
> `/api/regx/v1/version/` always reports the `0.1.0` default. **The running
> system cannot tell you which release it is.** Verification therefore checks
> the commit of the working tree the operator deployed *from*
> (`release_verify.sh --expect-commit`), which is weaker. Stamping a build arg
> into the images would close this; it is recommended and deliberately out of
> scope here.

Persistent data is **not** part of the release unit. It survives deployments and
is governed by `BACKUP_RESTORE_DR.md`.

---

## 3. Pre-deploy gate

Record each answer. Do not proceed on an unknown.

| # | Check | How |
|---|---|---|
| 1 | Target commit SHA recorded | `git rev-parse HEAD` |
| 2 | Working tree clean | `git status --porcelain` is empty |
| 3 | Required CI green **on that exact SHA** | Backend CI, Frontend CI, Docker Integration, Operational Scripts, as triggered |
| 4 | Environment pre-flight passes | `python scripts/check_env.py` |
| 5 | All four required secrets present | covered by (4) — see `DEPLOYMENT_BOUNDARIES.md` §2 |
| 6 | Document scanner not accidentally `stub` | `check_env.py` warns; **a deployment accepting uploads must set a real scanner** |
| 7 | Backup capability available | `scripts/backup.sh` present, services up |
| 8 | Backup taken, set ID recorded | see §7 |
| 9 | Backup manifest and checksums valid | `scripts/restore.sh --from <set> --verify-only` |
| 10 | Migrations reviewed | `manage.py migrate --plan` |
| 11 | Every migration classified | §4 |
| 12 | Current health known **before** touching anything | `scripts/release_verify.sh` |
| 13 | **Rollback target commit chosen and recorded** | §8 — decided *before* deploying, never during an incident |

**CI green is not regulatory approval.** It says the code builds and the tests
pass. Governance remains 0/20 and production questions remain 0 regardless of
what CI reports.

---

## 4. Migration risk classification

**Classify every migration in the release before deploying.** This is the step
that decides whether a rollback is even possible.

| Class | Meaning | Rollback route |
|---|---|---|
| **A** | Reversible by Django, and safe against the data that will exist | `migrate <app> <previous>` |
| **B** | Code-compatible, reversible only by a deliberate manual step | manual step, planned in advance |
| **C** | Irreversible or destructive | **DATA RESTORE (Level 3)** — never a backward migration |
| **D** | Data migration needing an explicit restore strategy | **DATA RESTORE (Level 3)** |

### The current migration set

23 migrations across 11 apps, surveyed directly:

| Pattern | Count | Note |
|---|---|---|
| `RunPython` | **0** | no data migrations exist today |
| `RunSQL` | 1 | `audit/0001` immutability trigger — **has `reverse_sql`** |
| `DeleteModel`, `RemoveField`, `RenameField`, `RenameModel` | 0 | |
| `RemoveConstraint` | 1 | `iig_checklist/0006` — see below |
| `AlterField` | 3 | JSONField defaults and a `BigAutoField` id; benign |

Structurally this looks entirely reversible. **It is not.**

### Demonstrated: `iig_checklist/0006` is class C once real data exists

`0006` removes `unique_active_execution_per_version_formulation` and re-adds a
constraint of the *same name* but conditioned on `subject_component IS NULL`.
Reversing it restores the original, **unconditioned** constraint: one active
execution per (tenant, checklist_version, formulation_version), regardless of
component.

That directly contradicts the OQ-8 decision the migration exists to implement —
one execution per component. So the moment a second component-scoped execution
exists, the reverse cannot succeed. Rehearsed on synthetic data:

```
django.db.utils.IntegrityError: could not create unique index
  "unique_active_execution_per_version_formulation"
DETAIL:  Key (tenant_id, checklist_version_id, formulation_version_id)=(1, 1, 1)
         is duplicated.
```

**And the failure was not clean.** `manage.py migrate iig_checklist 0005`
reversed `0007` first, then failed on `0006`, leaving:

```
[X] 0006_execution_subject_component
[ ] 0007_definition_execution_scope
```

A schema matching **neither** release. Django does not roll back across
migrations as a unit.

> **Rule: never attempt a backward migration to find out whether it works.**
> A failed attempt can leave the database in a state no release expects, and it
> does so *after* it has already begun modifying the schema. Classify first; if
> the answer is C or D, or unknown, go to Level 3.

### Classifying a new migration

Ask, in order:

1. Does it contain `RunPython`, `RunSQL` without `reverse_sql`, `DeleteModel`,
   `RemoveField`, or a narrowing `AlterField`? → **C or D**.
2. Does it add or restore a constraint that the *new* data model is allowed to
   violate? → **C**. This is the `0006` case, and it is easy to miss because
   Django reports the migration as reversible.
3. Otherwise → **A**, and record the data condition under which that holds.

---

## 5. Forward-compatibility window

| Direction | Status |
|---|---|
| **New code + old DB schema** | **NOT SUPPORTED** |
| **Old code + new DB schema** | **NOT PROVEN** |

*New code on an old schema* is not a judgement call — it was observed. With
`0007` reversed, HEAD code raised:

```
ProgrammingError: column iig_checklist_checklistdefinition.execution_scope does not exist
```

*Old code on a new schema* is untested. Nothing in the repository exercises
either direction, and there is no rolling deploy or second replica that would
require it.

**Therefore: fail closed.** Do not claim zero-downtime deployment. Sequence
migrations and container recreation deliberately (§6) and accept a short
controlled interruption. Whether that requires a maintenance window, and how
long one may be, is **PENDING BUSINESS / IT DECISION** (§12).

---

## 6. Deployment sequence

Derived from how this stack actually works, not a generic template.

| # | Step | Why this position |
|---|---|---|
| 1 | Complete the §3 pre-deploy gate | including choosing the rollback target |
| 2 | `scripts/backup.sh --project <name>` and record the set ID | before anything changes |
| 3 | Check out the target commit; `docker compose build` | images are built from the checkout |
| 4 | `docker compose up -d` | recreates the application containers |
| 5 | `docker compose exec backend python manage.py migrate` | **nothing migrates automatically** — the image runs `gunicorn` only |
| 6 | Wait for health | `docker compose ps`; celery has a 30s `start_period` |
| 7 | **`docker compose restart nginx`** | mandatory whenever upstream containers were recreated — §9 |
| 8 | `scripts/release_verify.sh --expect-commit <sha>` | §7 |
| 9 | Business acceptance | separate, and not an engineering decision — §12 |

**On step 4 before step 5:** the containers are recreated before the schema is
migrated, so new code runs against the old schema for the length of the
migration. §5 records that as NOT SUPPORTED, which is exactly why this is a
controlled interruption rather than a zero-downtime deploy. Reversing the order
would instead run old code against the new schema, which is merely NOT PROVEN.
Neither ordering is safe to treat as seamless; pick one, and expect the window.

---

## 7. Release verification

```bash
scripts/release_verify.sh --expect-commit <sha> [--project NAME] [--origin URL]
```

**Read-only.** It deploys nothing, migrates nothing, restarts nothing and writes
nothing, so it is safe to run at any time against any environment. It exits
non-zero if any check fails, prints no secrets, and makes no regulatory
decision.

It checks:

**Infrastructure** — all seven containers running · all seven healthchecks
healthy (waiting up to 60s for `starting`, so it does not fail a stack that is
merely still booting) · restart counts, to catch crash loops

**Application** — the integrated origin serving `/healthz`, `/`, `/ratools/`,
`/signin`, `/documents` · backend readiness reporting database and cache OK ·
two protected API endpoints returning 401/403 — **not** 200, which would mean
anonymous access, and **not** 404, which would mean the route is unwired ·
Celery replying to a targeted `inspect ping` · `AuditEvent` queryable
(a read-only count; the audit trail is checked for *availability*, and is never
confused with the operational logs below) · `migrate --check` and
`manage.py check`

**Observability** — backend log lines parse as JSON · a probe request receives
`X-Request-ID` and the supplied id is honoured · that probe is findable in the
logs · no credential-shaped string in recent output (reported as a fact, never
echoed)

No destructive business operation is performed. Nothing is created, approved,
submitted or deleted.

### Health is not correctness, and health is not routing

Two results from the rehearsal make this concrete:

- With the schema half-reversed, **all seven services were healthy and all five
  origin routes returned 200** while `ChecklistDefinition` queries were failing
  outright. Only `migrate --check` caught it.
- After recreating the application containers, **all seven services were healthy
  while `/` and `/ratools/` returned 404** (§9).

A smoke test of a few routes would have passed both. That is why the checks
above include migration state and correlation, not just HTTP codes.

---

## 8. Rollback triggers

Objective and technical. Any one of these is sufficient to invoke a rollback:

- migration failure, including a **partially applied** migration set
- any service failing to reach `healthy` inside its bounded period
- readiness reporting database or cache not OK
- integrated-origin routing failure that survives an nginx restart
- repeated container restarts (crash loop)
- a protected API returning 200 to an anonymous caller, or 404 where a route
  should exist
- data-integrity verification failure — a stored file whose bytes do not match
  the checksum its `DocumentVersion` row asserts
- document storage and database disagreeing (orphan rows or orphan files)
- `AuditEvent` unreachable

**Business and regulatory acceptance criteria are not defined here.** A release
can pass every check above and still be rejected by its owner.

---

## 9. nginx after container recreation

**nginx resolves upstream hostnames once at startup and holds the addresses for
the life of the process.** Recreating `backend`, `frontend`, `celery` or
`company_site` gives them new addresses; nginx keeps proxying to the old ones.

This is **not** solved by healthchecks. Reproduced twice during this work, with
two different symptoms:

| Occasion | Symptom |
|---|---|
| F-4, frontend recreated | `/signin`, `/documents` → **502** |
| F-6 rehearsal, application containers recreated | `/`, `/ratools/` → **404** |

The difference is whether the stale address has since been reused: if another
container now holds it, that container answers and simply lacks the route (404);
if nothing holds it, the connection fails (502). **In both cases every service
reported healthy.**

```bash
docker compose restart nginx
```

Restored all routes to 200 both times. This is a restart-to-re-resolve step, and
it is **not** a claim that nginx tracks Docker DNS — it does not, which is
precisely why the restart is required. It applies to any container recreation:
a deployment, a rollback, or a restore.

---

## 10. Rollback levels

Choose the **lowest** level that resolves the problem. Restoring data when a
code rollback would have sufficed discards every legitimate write since the
backup.

### Level 1 — service rollback

Return the application containers to the previous known-good commit and rebuild.
**Only where the schema is unchanged, or the new schema is compatible with the
old code** (§5: currently NOT PROVEN, so treat any schema change as ruling
Level 1 out).

```bash
git checkout <rollback-commit>
docker compose build && docker compose up -d
docker compose restart nginx          # mandatory, see §9
scripts/release_verify.sh --expect-commit <rollback-commit>
```

No data is touched. Rehearsed: containers returned healthy, routing required the
nginx restart, verification then passed.

### Level 2 — code and schema rollback

Level 1 **plus** a backward migration. Permitted **only** where every migration
in the release is class **A** and its data condition still holds (§4).

```bash
docker compose exec backend python manage.py migrate <app> <previous>
```

**If any migration is class B, C or D — or unclassified — do not use Level 2.**
Go to Level 3. A failed backward migration can leave the schema matching no
release at all, as demonstrated in §4.

### Level 3 — data restore

For a destructive or irreversible migration, data corruption, or any case where
application rollback cannot safely use the current data state.

```bash
scripts/restore.sh --from <backup-set> --verify-only        # first, always
scripts/restore.sh --from <backup-set> --project <name> --yes-destroy-data
```

Then verify per §7 **and** confirm data integrity: the recovered file's bytes
must match the checksum its database row asserts.

**Level 3 discards every write since the backup.** That is the cost, and it is
why the backup set ID is recorded before deploying rather than looked for
afterwards.

Full procedure and guarantees: `BACKUP_RESTORE_DR.md`.

---

## 11. Rehearsal evidence

Performed on a disposable `regx-rehearsal` compose project with synthetic data.
**No production data was used.** Torn down afterwards with `down -v`.

| Step | Result |
|---|---|
| Deploy, migrate, verify | **PASS** |
| Backup taken, manifest and checksums verified | **PASS** |
| Two component-scoped executions created on one formulation version | **PASS** |
| Backward migration attempted | **REFUSED** by the database — duplicate key |
| Migration state left partially reversed | **observed** — `0006` applied, `0007` not |
| New code on the resulting old schema | **failed** — `column ... execution_scope does not exist` |
| Verification detected the broken state | **PASS** — while all health and routing checks passed |
| Level 1 service rollback | **PASS** |
| Routing after recreation, before nginx restart | **404** on `/` and `/ratools/` |
| Routing after nginx restart | **PASS** — all 200 |
| Level 3 restore | **PASS** |
| Document row recovered | **PASS** |
| File recovered from `storage_key` | **PASS** |
| Bytes match the checksum the row asserts | **PASS** — `81670dc7…` both sides |
| Size matches | **PASS** |
| Post-restore verification | **PASS** — 40 of 41, the one failure being a deliberately dirty working tree |
| Company database intact | **PASS** — 81 tables |
| Celery, request IDs, JSON logs after restore | **PASS** |

---

## 12. Not decided here

Engineering defines technical pass/fail. These are business, QA and IT
decisions, and none is invented:

| | Status |
|---|---|
| Deployment approver | **PENDING** |
| Release authority | **PENDING** |
| Maintenance window | **PENDING** |
| Downtime SLA | **PENDING** |
| RTO | **PENDING BUSINESS / IT APPROVAL** |
| RPO | **PENDING BUSINESS / IT APPROVAL** |
| Backup retention | **PENDING QA / IT / SECURITY APPROVAL** |
| Business acceptance owner | **PENDING** |

**No Part 11 claim.** This runbook is an operational procedure, not a validated
or qualified deployment process.

---

## 13. Operator release record

An execution record, **not** a regulated approval record. It carries no
signature and no approval, and none should be added to it — attribution for
regulated actions belongs in `AuditEvent`, not here.

**Never record a secret.** Commit SHAs, backup-set IDs and service statuses
only.

```
RELEASE RECORD
  Release commit SHA .......
  Previous commit SHA ......
  Rollback target SHA ......
  Backup set ID ............
  Migration state before ...   (manage.py showmigrations, or "none pending")
  Migration state after ....
  Migration classification .   A / B / C / D per migration
  Deployment start (UTC) ...
  Deployment end (UTC) .....
  Health result ............   PASS / FAIL
  Verification result ......   PASS / FAIL   (scripts/release_verify.sh)
  nginx restarted ..........   YES / NO
  Rollback invoked .........   YES / NO
  Rollback level ...........   1 / 2 / 3 / n-a
  Rollback target used .....
  Final technical state ....
  Issues / deviations ......
  Operator .................
```

---

## 14. Limitations

- **The running system does not report its own commit.** See §2.
- **No deployment automation exists**, and none is added here. Every step is
  manual and operator-driven, by design — automating rollback would need
  stronger safeguards than currently exist.
- **`release_verify.sh` checks the working tree**, which is what was deployed
  *from*, not what is inside a running image.
- **Old code on a new schema is untested**, so §5 fails closed rather than
  claiming compatibility.
- **The rehearsal used synthetic data on a disposable project.** It exercises
  the mechanics; it is not a qualification of a production deployment.
- **Verification is a point-in-time sample.** It is not monitoring; see
  `SERVICE_HEALTH.md` and `OPERATIONAL_LOGGING.md` for what those do and do not
  provide.
