#!/usr/bin/env bash
# Restore a RegX backup set. THIS DESTROYS THE TARGET'S CURRENT DATA.
#
#   scripts/restore.sh --from DIR --project NAME --yes-destroy-data
#   scripts/restore.sh --from DIR --verify-only
#
# Guards, in the order they fire:
#
#   1. --verify-only checks the manifest and every checksum and exits without
#      touching anything. Always available, always safe.
#   2. --project must be given explicitly. There is no default, so a restore
#      cannot land in whatever project happens to be configured in the
#      environment.
#   3. --yes-destroy-data must be given explicitly. Restoring is destructive and
#      the caller has to say so.
#   4. A target whose name looks like production is refused outright unless
#      REGX_ALLOW_PROD_RESTORE=1 is also set, so a mistyped flag cannot take out
#      a live system.
#   5. Every checksum is verified BEFORE any mutation. A tampered or truncated
#      artefact stops the run while the target is still intact.
#
# Restore order matters: services that write are stopped first, the database is
# replaced, then files, then the company database, then services come back and
# the migration state is checked. See docs/BACKUP_RESTORE_DR.md.
set -euo pipefail

FROM=""
PROJECT=""
CONFIRMED=0
VERIFY_ONLY=0

while [ $# -gt 0 ]; do
    case "$1" in
        --from) FROM="$2"; shift 2 ;;
        --project) PROJECT="$2"; shift 2 ;;
        --yes-destroy-data) CONFIRMED=1; shift ;;
        --verify-only) VERIFY_ONLY=1; shift ;;
        -h|--help) sed -n '2,28p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "error: unknown argument: $1" >&2; exit 2 ;;
    esac
done

fail() { echo "FAIL: $*" >&2; exit 1; }

[ -n "$FROM" ] || fail "--from DIR is required"
[ -d "$FROM" ] || fail "backup set directory not found: $FROM"

MANIFEST="${FROM}/manifest.json"
[ -f "$MANIFEST" ] || fail "manifest.json is missing from the backup set: $FROM"

# -- Verify the manifest parses and every artefact matches its checksum ------
# Done before anything else, so a bad set can never reach the mutation stage.
echo "verifying backup set: $FROM"
python - "$FROM" <<'PYEOF' || exit 1
import hashlib, json, os, sys

set_dir = sys.argv[1]
manifest_path = os.path.join(set_dir, "manifest.json")

try:
    with open(manifest_path, encoding="utf-8") as fh:
        manifest = json.load(fh)
except (json.JSONDecodeError, UnicodeDecodeError) as exc:
    print(f"FAIL: manifest.json is not valid JSON: {exc}", file=sys.stderr)
    sys.exit(1)

for field in ("backup_set_id", "artifacts", "checksum_algorithm", "created_at_utc"):
    if field not in manifest:
        print(f"FAIL: manifest.json is missing required field {field!r}", file=sys.stderr)
        sys.exit(1)

if manifest["checksum_algorithm"] != "sha256":
    print(f"FAIL: unsupported checksum algorithm {manifest['checksum_algorithm']!r}", file=sys.stderr)
    sys.exit(1)

artifacts = manifest["artifacts"]
if not artifacts:
    print("FAIL: manifest lists no artifacts", file=sys.stderr)
    sys.exit(1)

required = {"postgres.dump", "document_storage.tar.gz", "company_db.sqlite3"}
missing_required = required - set(artifacts)
if missing_required:
    print(f"FAIL: backup set is incomplete, missing: {', '.join(sorted(missing_required))}", file=sys.stderr)
    sys.exit(1)

def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

problems = []
for name, meta in sorted(artifacts.items()):
    path = os.path.join(set_dir, name)
    if not os.path.exists(path):
        problems.append(f"{name}: artifact file is missing")
        continue
    actual_size = os.path.getsize(path)
    if actual_size != meta.get("bytes"):
        problems.append(f"{name}: size {actual_size} != manifest {meta.get('bytes')}")
    actual = sha256(path)
    if actual != meta.get("sha256"):
        problems.append(f"{name}: checksum mismatch")
    else:
        print(f"  OK  {name}  ({actual_size} bytes)")

if problems:
    for p in problems:
        print(f"FAIL: {p}", file=sys.stderr)
    print("\nRefusing to restore from an unverified backup set.", file=sys.stderr)
    sys.exit(1)

print(f"\nmanifest OK: {manifest['backup_set_id']}")
print(f"  created:    {manifest['created_at_utc']}")
print(f"  commit:     {manifest.get('application_commit', 'unknown')}")
print(f"  migrations: {manifest.get('applied_migrations', 'unknown')}")
PYEOF

if [ "$VERIFY_ONLY" -eq 1 ]; then
    echo
    echo "OK: verification passed. Nothing was modified (--verify-only)."
    exit 0
fi

# -- Destructive-action guards ----------------------------------------------
[ -n "$PROJECT" ] || fail "--project NAME is required for a restore. There is no default target."
[ "$CONFIRMED" -eq 1 ] || fail "--yes-destroy-data is required. Restoring replaces all data in project '$PROJECT'."

case "$PROJECT" in
    # *prod* already covers "production"; listing both is a dead alternative.
    *prod*|*live*)
        if [ "${REGX_ALLOW_PROD_RESTORE:-0}" != "1" ]; then
            fail "target '$PROJECT' looks like production. Refusing. Set REGX_ALLOW_PROD_RESTORE=1 only if you are certain."
        fi
        echo "WARNING: restoring into production-like target '$PROJECT' (override was set)" >&2
        ;;
esac

compose() { docker compose -p "$PROJECT" "$@"; }
compose ps --services >/dev/null 2>&1 || fail "compose project '$PROJECT' is not usable from here"

echo
echo "RESTORING into project '$PROJECT'. Current data will be replaced."
echo

# -- 1. Stop the writers ----------------------------------------------------
# The database and files must not change under us mid-restore. postgres stays
# up because we restore into it; the company site stops so its SQLite file is
# not open for writing when it is replaced.
echo "  [1/6] stopping writers (backend, celery, company_site)"
compose stop backend celery company_site >/dev/null 2>&1 || true

# -- 2. PostgreSQL ----------------------------------------------------------
# --clean --if-exists is baked into the dump; pg_restore drops and recreates.
# Errors are surfaced rather than ignored: a partially restored database is
# worse than a failed restore.
echo "  [2/6] restoring postgres"
compose exec -T postgres pg_restore -U regx -d regx --clean --if-exists --no-owner \
    < "${FROM}/postgres.dump" 2>"${FROM}/.restore-pg.log" \
    || { sed -n '1,20p' "${FROM}/.restore-pg.log" >&2; rm -f "${FROM}/.restore-pg.log"; fail "pg_restore failed"; }
rm -f "${FROM}/.restore-pg.log"

# -- 3. Document storage ----------------------------------------------------
echo "  [3/6] restoring document storage"
compose start backend >/dev/null 2>&1
# Wait for the container to accept exec.
for _ in $(seq 1 30); do
    compose exec -T backend true >/dev/null 2>&1 && break
    sleep 1
done
compose exec -T backend sh -c 'rm -rf /app/document_storage/* /app/document_storage/.[!.]* 2>/dev/null; true' \
    || fail "could not clear document storage"
compose exec -T backend sh -c 'cd /app && tar xzf -' < "${FROM}/document_storage.tar.gz" \
    || fail "document storage restore failed"

# -- 4. Company SQLite ------------------------------------------------------
echo "  [4/6] restoring company database"
compose start company_site >/dev/null 2>&1
for _ in $(seq 1 30); do
    compose exec -T company_site true >/dev/null 2>&1 && break
    sleep 1
done
compose exec -T company_site sh -c 'cat > /app/data/db.sqlite3' < "${FROM}/company_db.sqlite3" \
    || fail "company database restore failed"

# -- 5. Company media, only if the set carried it ---------------------------
if [ -f "${FROM}/company_media.tar.gz" ]; then
    echo "  [5/6] restoring company media"
    compose exec -T company_site sh -c 'cd /app && tar xzf -' < "${FROM}/company_media.tar.gz" \
        || fail "company media restore failed"
else
    echo "  [5/6] company media not in this set -- re-seed with scripts/sync_company_runtime_assets.sh if needed"
fi

# -- 6. Bring everything back and check -------------------------------------
echo "  [6/6] restarting services and checking migration state"
compose up -d >/dev/null 2>&1 || fail "could not restart services"

# nginx resolves its upstream hostnames ONCE at startup and caches the IPs for
# the life of the process. Restoring recreates backend/celery/company_site,
# which hands them new addresses on the compose network -- so a long-running
# nginx keeps proxying to the old ones. The symptom is not a 502 but a 404,
# because the stale address now belongs to a different container that answers
# and simply does not have the route. Restarting nginx re-resolves them.
# This applies to any container recreation, not only to a restore.
compose restart nginx >/dev/null 2>&1 || fail "could not restart nginx to re-resolve upstreams"
for _ in $(seq 1 60); do
    compose exec -T backend true >/dev/null 2>&1 && break
    sleep 1
done
compose exec -T backend python manage.py migrate --check >/dev/null 2>&1 \
    || echo "WARNING: 'migrate --check' reports unapplied migrations. The dump may predate the current code. Review before use." >&2
compose exec -T backend python manage.py check >/dev/null 2>&1 \
    || fail "django system check failed after restore"

echo
echo "OK: restore complete into project '$PROJECT'."
echo "Verify the recovered data before returning the system to service."
