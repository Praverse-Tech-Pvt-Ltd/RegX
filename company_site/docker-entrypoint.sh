#!/bin/sh
# Seed the company SQLite database onto its named volume on first start.
#
# The image ships /app/db.sqlite3 exactly as copied from the company source.
# The volume mounted at /app/data is what the app actually opens (see
# COMPANY_DB_PATH), so that writes — session rows, demo bookings — persist
# across rebuilds instead of being discarded with the container layer.
set -e

DB_TARGET="${COMPANY_DB_PATH:-/app/data/db.sqlite3}"

if [ ! -f "$DB_TARGET" ]; then
    echo "Seeding company database at $DB_TARGET from the copied db.sqlite3"
    cp /app/db.sqlite3 "$DB_TARGET"
fi

exec "$@"
