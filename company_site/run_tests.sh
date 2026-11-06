#!/bin/sh
# Run the company_site test suites (smoke tests + the existing AIDatabase tests).
#
#   docker compose exec -T company_site ./run_tests.sh          # inside the running container
#   docker run --rm --entrypoint ./run_tests.sh regx-company_site   # from the image (what CI does)
#
# Hard rule: OPENAI_API_KEY must never be set while these tests run (the FDA-483
# summariser calls OpenAI whenever a key is present). This check fails before
# anything is imported; smoke_tests/__init__.py repeats it for direct runs.
set -eu

if [ -n "${OPENAI_API_KEY:-}" ]; then
    echo "OPENAI_API_KEY is set. company_site tests must run without it. Nothing was executed." >&2
    exit 2
fi

# Throwaway values for settings that have no default; never real secrets.
export SECRET_KEY="${SECRET_KEY:-company-site-tests-not-a-secret}"
export BASE_URL="${BASE_URL:-http://localhost:8080}"
export SERVER="${SERVER:-LOCAL}"
export DJANGO_SETTINGS_MODULE="${DJANGO_SETTINGS_MODULE:-RAAI.settings_integration}"

# The test database is Django's in-memory SQLite database; db.sqlite3 is not opened.
exec python manage.py test smoke_tests AIDatabase --noinput "$@"
