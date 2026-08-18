#!/usr/bin/env bash
# Take a RegX backup set.
#
# Captures the authoritative stores and writes a manifest with SHA-256 checksums
# so a restore can verify what it is about to install before touching anything.
#
#   scripts/backup.sh [--output DIR] [--project NAME] [--include-company-media]
#
# What is captured, and why:
#
#   postgres.dump          pg_dump custom format. All RegX operational data:
#                          executions, responses, snapshots, audit.
#   document_storage.tar.gz  Uploaded evidence. DocumentVersion rows reference
#                          these by storage_key AND assert a sha256_checksum, so
#                          the database and this archive form ONE consistency
#                          unit -- restoring them from different points in time
#                          produces rows pointing at missing or wrong files.
#   company_db.sqlite3     The company site's SQLite database, taken through
#                          Python's sqlite3 backup API rather than a file copy,
#                          which is not safe against a live writer.
#   company_media.tar.gz   Optional (--include-company-media). Runtime uploads
#                          written by the company app. Large (~200 MB) and
#                          mostly re-seedable from the read-only company source
#                          via scripts/sync_company_runtime_assets.sh, so it is
#                          off by default -- but anything the app itself wrote
#                          exists ONLY here.
#
# NOT captured, deliberately: Redis (no volume is configured, so it holds no
# durable state -- cache and Celery transport only), and every secret. Deployment
# secrets are restored through your secret-management process, never from an
# application backup. See docs/BACKUP_RESTORE_DR.md.
#
# This is a technical backup capability. It is not a validated DR system.
set -euo pipefail

OUTPUT_DIR="./backups"
PROJECT="${COMPOSE_PROJECT_NAME:-regx}"
INCLUDE_COMPANY_MEDIA=0

while [ $# -gt 0 ]; do
    case "$1" in
        --output) OUTPUT_DIR="$2"; shift 2 ;;
        --project) PROJECT="$2"; shift 2 ;;
        --include-company-media) INCLUDE_COMPANY_MEDIA=1; shift ;;
        -h|--help) sed -n '2,32p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "error: unknown argument: $1" >&2; exit 2 ;;
    esac
done

compose() { docker compose -p "$PROJECT" "$@"; }

fail() { echo "FAIL: $*" >&2; exit 1; }

# Every artefact is written into a staging directory first and only promoted on
# success, so an interrupted run can never leave a directory that looks like a
# complete backup set.
STAGING=""
cleanup() {
    if [ -n "$STAGING" ] && [ -d "$STAGING" ]; then
        rm -rf "$STAGING"
        echo "cleaned up incomplete staging directory" >&2
    fi
}
trap cleanup EXIT

command -v docker >/dev/null 2>&1 || fail "docker is not on PATH"
compose ps --services >/dev/null 2>&1 || fail "compose project '$PROJECT' is not usable from here"

for svc in postgres backend company_site; do
    state="$(compose ps --status running --services 2>/dev/null | grep -Fx "$svc" || true)"
    [ -n "$state" ] || fail "service '$svc' is not running; start the stack before backing up"
done

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
COMMIT="$(git rev-parse --short HEAD 2>/dev/null || echo unknown)"
SET_ID="regx-backup-${STAMP}-${COMMIT}"
SET_DIR="${OUTPUT_DIR}/${SET_ID}"

[ -e "$SET_DIR" ] && fail "backup set already exists: $SET_DIR (refusing to overwrite)"

mkdir -p "$OUTPUT_DIR"
STAGING="$(mktemp -d "${OUTPUT_DIR}/.staging-XXXXXX")"

echo "backup set: ${SET_ID}"
echo

# -- PostgreSQL -------------------------------------------------------------
# Custom format (-Fc): compressed, and pg_restore can rebuild selectively.
# --clean --if-exists so the dump can be replayed onto a populated database.
echo "  [1/4] postgres -> postgres.dump"
compose exec -T postgres pg_dump -U regx -d regx -Fc --clean --if-exists \
    > "${STAGING}/postgres.dump" \
    || fail "pg_dump failed"
[ -s "${STAGING}/postgres.dump" ] || fail "pg_dump produced an empty file"

# -- Document storage -------------------------------------------------------
# Streamed out of the container so no host path translation is involved.
echo "  [2/4] document_storage -> document_storage.tar.gz"
compose exec -T backend sh -c 'cd /app && tar czf - document_storage' \
    > "${STAGING}/document_storage.tar.gz" \
    || fail "document storage archive failed"

# -- Company SQLite ---------------------------------------------------------
# sqlite3.Connection.backup() is the online-backup API: it takes a consistent
# copy while another connection may be writing. `cp` of a live SQLite file can
# capture a torn page or miss the WAL entirely.
echo "  [3/4] company_db -> company_db.sqlite3"
compose exec -T company_site python -c "
import sqlite3, sys
src = sqlite3.connect('file:/app/data/db.sqlite3?mode=ro', uri=True)
dst = sqlite3.connect('/tmp/_backup.sqlite3')
with dst:
    src.backup(dst)
dst.close(); src.close()
" || fail "sqlite online backup failed"
compose exec -T company_site sh -c 'cat /tmp/_backup.sqlite3; rm -f /tmp/_backup.sqlite3' \
    > "${STAGING}/company_db.sqlite3" \
    || fail "could not retrieve the sqlite backup"
[ -s "${STAGING}/company_db.sqlite3" ] || fail "sqlite backup is empty"

# -- Company media (optional) -----------------------------------------------
if [ "$INCLUDE_COMPANY_MEDIA" -eq 1 ]; then
    echo "  [4/4] company media -> company_media.tar.gz"
    compose exec -T company_site sh -c 'cd /app && tar czf - media' \
        > "${STAGING}/company_media.tar.gz" \
        || fail "company media archive failed"
else
    echo "  [4/4] company media -> SKIPPED (pass --include-company-media to include)"
fi

# -- Integrity and manifest -------------------------------------------------
echo
echo "  computing SHA-256 checksums"
( cd "$STAGING" && sha256sum ./* > SHA256SUMS ) || fail "checksum generation failed"

# Migration state makes a restore verifiable: a dump replayed against a
# different schema generation is a silent corruption, not an error.
MIGRATION_COUNT="$(compose exec -T backend python manage.py showmigrations --plan 2>/dev/null | grep -c '^\[X\]' || echo 0)"

python - "$STAGING" "$SET_ID" "$STAMP" "$COMMIT" "$MIGRATION_COUNT" "$INCLUDE_COMPANY_MEDIA" <<'PYEOF'
import hashlib, json, os, subprocess, sys

staging, set_id, stamp, commit, migrations, media = sys.argv[1:7]

def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

def tool(cmd):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=30).stdout.strip().splitlines()[0]
    except Exception:
        return "unknown"

artifacts = {}
for name in sorted(os.listdir(staging)):
    if name in ("manifest.json", "SHA256SUMS"):
        continue
    path = os.path.join(staging, name)
    artifacts[name] = {"sha256": sha256(path), "bytes": os.path.getsize(path)}

manifest = {
    "backup_set_id": set_id,
    "schema_version": 1,
    "created_at_utc": stamp,
    "application_commit": commit,
    "applied_migrations": int(migrations),
    "checksum_algorithm": "sha256",
    "includes_company_media": media == "1",
    "artifacts": artifacts,
    "tooling": {
        "pg_dump": tool(["docker", "compose", "exec", "-T", "postgres", "pg_dump", "--version"]),
    },
    # Stated in the manifest so a restorer cannot mistake the guarantee.
    "consistency": (
        "postgres.dump and document_storage.tar.gz form one recovery unit: "
        "DocumentVersion rows reference storage_key and assert sha256_checksum. "
        "They are captured sequentially, NOT in a single cross-volume transaction; "
        "back up with writers quiesced for a strictly consistent set."
    ),
    "secrets": "none - deployment secrets are never included in a backup set",
}
with open(os.path.join(staging, "manifest.json"), "w", encoding="utf-8") as fh:
    json.dump(manifest, fh, indent=2, sort_keys=True)
    fh.write("\n")
print("  manifest written: %d artifact(s)" % len(artifacts))
PYEOF

mv "$STAGING" "$SET_DIR"
STAGING=""   # promoted; the cleanup trap must not remove it

echo
echo "OK: backup set written to ${SET_DIR}"
echo
echo "Artifacts:"
( cd "$SET_DIR" && ls -la | tail -n +2 | awk '{printf "  %10s  %s\n", $5, $9}' | grep -v '^\s*\S*\s*\.\.\?$' )
echo
echo "Verify later with:  scripts/restore.sh --from ${SET_DIR} --verify-only"
