# Backup, Restore and Disaster Recovery

**Scope: a tested technical backup and restore capability.**

This is **not** a validated disaster-recovery system, not a qualified backup
system, and makes **no Part 11 claim**. It is an operational continuity control
whose mechanics have been exercised end to end on disposable synthetic data.
Production qualification — approval of RPO, RTO, retention, off-site handling
and a rehearsed operational drill — is still required and is **not** claimed
here.

Verified against `regx-main` `a4f46dafa5fb81611222d71a76e3ce41142a8795`.

---

## 1. Stateful stores

Enumerated from `compose.yaml` and the settings, not assumed.

| Store | Service | Mount | Data | Classification | Backed up |
|---|---|---|---|---|:-:|
| `postgres_data` | postgres | `/var/lib/postgresql/data` | All RegX operational data: executions, responses, snapshots, audit, identity, tenancy | **AUTHORITATIVE** | **Yes** |
| `document_storage` | backend, celery | `/app/document_storage` | Uploaded evidence files | **AUTHORITATIVE** | **Yes** |
| `company_db` | company_site | `/app/data/db.sqlite3` | Company site runtime state: logins, demo bookings, sessions, FDA-483 content | **AUTHORITATIVE** | **Yes** |
| `./company_site/media` | company_site (rw), nginx (ro) | `/app/media`, `/srv/company/media` | Company observation images | **MIXED** — seeded portion is REBUILDABLE from the read-only company source; anything the app uploaded is AUTHORITATIVE | **Optional** (`--include-company-media`) |
| Redis | redis | *none* | Django cache, Celery broker and results | **EPHEMERAL** | No |
| nginx, frontend | — | config bind mounts only | no state | **EPHEMERAL** | No |

**Redis holds no durable state**: the service declares no volume and no
persistence command, so its data dies with the container. It is a cache and a
task transport. Losing it costs in-flight Celery tasks, not records.

**The company media tree is a host bind mount, not a named volume**, and it is
deliberately excluded from git (`docs/COMPANY_RUNTIME_ASSETS.md`). Its ~200 MB
of seeded observation images can be re-created with
`scripts/sync_company_runtime_assets.sh`; only files the running application
wrote itself exist nowhere else. That is why it is opt-in rather than default.

---

## 2. The consistent recovery unit

**`postgres_data` + `document_storage` are one unit and must be recovered
together.**

`DocumentVersion` rows carry both a `storage_key` naming a file and a
`sha256_checksum` asserting its content. Restore them from different points in
time and you get rows pointing at missing files, orphan files with no rows, or —
worst — a file whose bytes no longer match the checksum the record asserts.
For a system whose value is a defensible audit trail, the third case is the
dangerous one, because it looks like evidence.

`company_db` + `company_site/media` form a second, independent unit: the company
app's `ImageField` rows reference files in that tree. It has no foreign key into
RegX, so it can be recovered separately.

### What is honestly guaranteed

**The artifacts are captured sequentially, not in a single cross-volume
transaction.** No such atomic mechanism is implemented, and this document does
not claim one. Consequences:

- **Backing up with writers quiesced gives a strictly consistent set.** Stop
  `backend`, `celery` and `company_site`, take the backup, start them again.
- **Backing up hot gives a set with a consistency window** the width of the run
  (seconds to minutes). A document uploaded during that window may land in the
  database dump but not the file archive, or the reverse.

The manifest states this in the artifact itself, so a restorer reading only the
backup set cannot mistake the guarantee.

---

## 3. Taking a backup

```bash
scripts/backup.sh [--output DIR] [--project NAME] [--include-company-media]
```

Default output is `./backups/`, and each run creates
`regx-backup-<UTC timestamp>-<commit>/`.

| Artifact | Method | Why this method |
|---|---|---|
| `postgres.dump` | `pg_dump -Fc --clean --if-exists` | Custom format: compressed, selectively restorable, replayable onto a populated database |
| `document_storage.tar.gz` | `tar` streamed out of the backend container | No host path translation; the container is the only thing that needs to see the volume |
| `company_db.sqlite3` | Python `sqlite3.Connection.backup()` | The **online backup API**. A plain `cp` of a live SQLite file can capture a torn page or miss the WAL — that is why the script does not copy the file |
| `company_media.tar.gz` | `tar`, opt-in | Large and largely re-seedable; see §1 |
| `manifest.json`, `SHA256SUMS` | generated | Integrity and provenance |

Behaviours that matter:

- **Fails fast**, non-zero on any partial failure.
- **Never overwrites** an existing backup set.
- **Stages then promotes**: every artifact is written to a temporary directory
  and moved into place only on success, so an interrupted run cannot leave
  something that looks like a complete set. Verified — a mid-run failure during
  development left no set behind, only a log line saying it had cleaned up.
- **Refuses to run** unless `postgres`, `backend` and `company_site` are up.
- **Prints no secrets.**

### Manifest

`manifest.json` carries the backup-set ID, UTC creation time, application
commit, applied-migration count, checksum algorithm, per-artifact SHA-256 and
byte size, `pg_dump` version, an explicit consistency statement, and an explicit
`"secrets": "none"`.

The migration count matters: replaying a dump against a different schema
generation is a silent corruption, not an error, so the restore reports it.

---

## 4. Restoring

```bash
scripts/restore.sh --from DIR --verify-only                          # safe, checks only
scripts/restore.sh --from DIR --project NAME --yes-destroy-data      # destructive
```

Five guards, in the order they fire:

1. `--verify-only` validates the manifest and every checksum and exits without
   touching anything.
2. `--project` must be explicit. There is no default target, so a restore cannot
   land wherever the environment happens to point.
3. `--yes-destroy-data` must be explicit.
4. A target whose name contains `prod`, `production` or `live` is **refused**
   unless `REGX_ALLOW_PROD_RESTORE=1` is also set.
5. **Every checksum is verified before any mutation.** A tampered, truncated or
   missing artifact stops the run while the target is still intact.

Restore order, and why:

| Step | Action | Reason |
|---|---|---|
| 1 | Stop `backend`, `celery`, `company_site` | Nothing may write while state is replaced. `postgres` stays up — it is the restore target |
| 2 | `pg_restore --clean --if-exists --no-owner` | Database first: files are meaningless without the rows referencing them |
| 3 | Clear and re-extract `document_storage` | Cleared first, so files deleted since the backup do not survive as orphans |
| 4 | Overwrite the company SQLite file | Its service is stopped, so nothing holds the file open |
| 5 | Company media, only if the set carried it | Otherwise the operator is told to re-seed |
| 6 | Bring services up, **restart nginx**, check migrations and Django health | See the warning below |

### nginx must be restarted after a restore

**nginx resolves its upstream hostnames once at startup and caches the IPs for
the life of the process.** Restoring recreates `backend`, `celery` and
`company_site`, which receive new addresses on the compose network — so a
long-running nginx keeps proxying to the old ones.

This was found during the restore test, and the symptom is misleading: **not a
502 but a 404**, because the stale address now belongs to a different container
that answers and simply does not have the route. The company site was healthy
and correct on its own port while every page through the origin returned 404.

`restore.sh` now restarts nginx as its final step. **The same applies to any
container recreation, not only a restore** — if routes start 404ing after
recreating a service, restart nginx before looking anywhere else.

---

## 5. Verification performed

End to end on disposable synthetic data. No production data was used.

| Check | Result |
|---|---|
| Backup of a live stack | **PASS** — 3 artifacts + manifest + SHA256SUMS |
| Synthetic RegX data destroyed, then restored from the set alone | **PASS** |
| PostgreSQL rows recovered (tenant, document, version) | **PASS** |
| Evidence file recovered | **PASS** |
| File checksum matches the value asserted by the database row | **PASS** |
| DB → file relationship valid after restore | **PASS** |
| Company database recovered (marker row + 6,306 business rows) | **PASS** |
| `manage.py check` after restore | **PASS** |
| `migrate --check` after restore | **PASS** — no unapplied migrations |
| Site serving through the origin after restore | **PASS** (after the nginx fix in §4) |
| Missing artifact | **Refused** — names the artifact |
| Tampered artifact | **Refused** — size and checksum mismatch reported |
| Malformed manifest | **Refused** — reports invalid JSON |
| No `--project` | **Refused** |
| No `--yes-destroy-data` | **Refused** |
| Production-looking target | **Refused** without the override |

---

## 6. Secrets are never in a backup

No `.env`, signing key, API key, SMTP password or private credential is captured
by `backup.sh`. The manifest records `"secrets": "none"`.

**Deployment secrets are restored through your secret-management process, not
from an application backup.** A restored database is useless without
`DJANGO_SECRET_KEY`, `POSTGRES_PASSWORD`, `MFA_ENCRYPTION_KEY` and
`COMPANY_SECRET_KEY` — see `DEPLOYMENT_BOUNDARIES.md` §2. Losing
`MFA_ENCRYPTION_KEY` in particular makes every stored MFA secret undecryptable;
the backup cannot help you there.

### Outstanding external security actions — unchanged

| Item | Status |
|---|---|
| GitHub Support purge of superseded PR #22 objects | **NOT CONFIRMED** |
| Three historical OpenAI project-key rotations | **NOT CONFIRMED** |
| Historical SMTP password rotation | **NOT CONFIRMED** |

---

## 7. Awaiting approval — not chosen by engineering

These are business, QA and IT decisions. Engineering states the consequence of a
choice; it does not make the choice.

| Parameter | Status |
|---|---|
| **RPO** (tolerable data loss) | **PENDING BUSINESS / IT APPROVAL** |
| **RTO** (tolerable downtime) | **PENDING BUSINESS / IT APPROVAL** |
| **Retention** (how long sets are kept, how many) | **PENDING BUSINESS / QA / IT APPROVAL** |
| Off-site / immutable storage | **PENDING** — sets are written to a local path only |
| Encryption of backup sets at rest | **PENDING** — not currently applied |
| Scheduled execution | **PENDING** — the script is manual; no cron or scheduler is configured |

Consequences, offered as engineering input only:

- Hourly backups mean up to roughly **one hour** of recoverable-data loss; daily
  means up to roughly **a day**. Neither is a target until approved.
- RTO is dominated by restore duration, which scales with `document_storage`
  size, plus the time to obtain the deployment secrets.
- Retention has a cost dimension: a full set is roughly the database dump plus
  the evidence tree, and considerably larger with `--include-company-media`.

The scripts support rotation by writing each set to its own timestamped
directory; **no retention period is selected here.**

---

## 8. Operator prerequisites

- Docker and Docker Compose, with the target project reachable
- `postgres`, `backend` and `company_site` running (for backup)
- Python 3 on the host, for manifest generation and verification
- Enough disk for the set: database dump + evidence tree, plus ~200 MB with
  company media
- Access to deployment secrets through the secret-management process — **the
  backup will not supply them**

---

## 9. Failure handling

| Situation | Behaviour |
|---|---|
| Any backup step fails | Non-zero exit; the staging directory is removed; **no partial set is left** |
| Backup set already exists | Refused; nothing is overwritten |
| A required service is down | Refused before anything is written |
| Checksum or manifest invalid at restore | Refused **before** any mutation; the target is untouched |
| `pg_restore` fails | Restore aborts and the first 20 log lines are shown. **The database may be partially restored — do not return the system to service; investigate and restore again** |
| `migrate --check` reports unapplied migrations | Warning, not a failure: the dump may predate the current code. Review before use |
| Routes 404 after restore | nginx upstream caching — see §4 |

---

## 10. CI coverage

`.github/workflows/operational-scripts.yml` runs on any change under
`scripts/**`: shell syntax, ShellCheck, the four `check_env` behaviours, and the
restore script's refusal paths including checksum verification on a synthetic
backup set.

It deliberately does **not** stand up the stack or perform a full restore on
every commit — that is expensive, and the guards it does test are what actually
prevent data loss. Before this, `scripts/**` had **no CI coverage at all**, which
is how `check_env.py` came to enforce a contract that did not match the runtime
without anyone noticing. A recovery tool that never runs in CI rots the same
way, and rots silently.
