#!/usr/bin/env bash
# Verify a deployed RegX stack. READ-ONLY.
#
#   scripts/release_verify.sh [--project NAME] [--origin URL] [--expect-commit SHA]
#
# This script observes and reports. It does not deploy, migrate, restart,
# restore, write, or mutate anything -- it may be run at any time against a
# running stack, including a production one, without changing it.
#
# What it is NOT:
#   * not a regulatory approval, and it makes no regulatory decision;
#   * not a validation protocol;
#   * not business acceptance -- that is an owner decision, see
#     docs/RELEASE_ROLLBACK_RUNBOOK.md section 12.
#
# It answers one narrow question: is the deployed stack technically healthy and
# behaving as expected. Exit 0 if every check passed, non-zero otherwise.
set -uo pipefail

PROJECT="regx"
ORIGIN="http://localhost:8080"
EXPECT_COMMIT=""
#: Bounded wait for a service to leave "starting". Long enough to cover the
#: slowest configured start_period (celery, 30s) plus a probe interval.
HEALTH_WAIT_SECONDS="${REGX_HEALTH_WAIT_SECONDS:-60}"

while [ $# -gt 0 ]; do
    case "$1" in
        --project) PROJECT="$2"; shift 2 ;;
        --origin) ORIGIN="$2"; shift 2 ;;
        --expect-commit) EXPECT_COMMIT="$2"; shift 2 ;;
        -h|--help) sed -n '2,19p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "error: unknown argument: $1" >&2; exit 2 ;;
    esac
done

PASS=0
FAIL=0
SERVICES="postgres redis backend celery frontend company_site nginx"

ok()   { echo "  PASS  $1"; PASS=$((PASS + 1)); }
bad()  { echo "  FAIL  $1"; FAIL=$((FAIL + 1)); }
head_() { echo; echo "== $1"; }

compose() { docker compose -p "$PROJECT" "$@"; }
code_for() { curl -s -o /dev/null -w "%{http_code}" --max-time 15 "$1"; }

# -- 1. Source identity ------------------------------------------------------
head_ "Release identity"
HEAD_SHA="$(git rev-parse HEAD 2>/dev/null || echo unknown)"
echo "  working tree HEAD: ${HEAD_SHA}"
if [ -n "$EXPECT_COMMIT" ]; then
    if [ "$HEAD_SHA" = "$EXPECT_COMMIT" ]; then
        ok "working tree is at the expected commit"
    else
        bad "expected ${EXPECT_COMMIT}, working tree is at ${HEAD_SHA}"
    fi
fi
# Honest about what this proves: the checkout the operator deployed FROM, not
# the commit baked into a running image. Nothing stamps a commit into the
# images today -- see the runbook's limitations section.
if [ -n "$(git status --porcelain 2>/dev/null)" ]; then
    bad "working tree is dirty -- the deployed source is not a clean commit"
else
    ok "working tree is clean"
fi

# -- 2. Containers -----------------------------------------------------------
head_ "Containers"
for svc in $SERVICES; do
    cid="$(compose ps -q "$svc" 2>/dev/null)"
    if [ -z "$cid" ]; then
        bad "${svc}: no container"
        continue
    fi
    state="$(docker inspect --format='{{.State.Status}}' "$cid" 2>/dev/null)"
    [ "$state" = "running" ] && ok "${svc}: running" || bad "${svc}: ${state}"
done

# -- 3. Health ---------------------------------------------------------------
# Waits, rather than sampling once. A single sample taken shortly after a
# restart reports "starting" for a service that is about to be fine -- nginx's
# interval is 10s, so a check run 5s after `compose restart nginx` fails a
# healthy stack. A verification tool that produces false failures is worse than
# none: it teaches an operator to roll back a good release, or to ignore it.
head_ "Healthchecks (waiting up to ${HEALTH_WAIT_SECONDS}s each)"
for svc in $SERVICES; do
    cid="$(compose ps -q "$svc" 2>/dev/null)"
    [ -z "$cid" ] && continue
    status=""
    waited=0
    while [ "$waited" -le "$HEALTH_WAIT_SECONDS" ]; do
        status="$(docker inspect --format='{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$cid" 2>/dev/null)"
        # "starting" is the only transient worth waiting on. An explicit
        # "unhealthy" is a decided answer -- do not sit on it.
        [ "$status" = "starting" ] || break
        sleep 3
        waited=$((waited + 3))
    done
    case "$status" in
        healthy) ok "${svc}: healthy${waited:+ (after ${waited}s)}" ;;
        none)    bad "${svc}: no healthcheck configured" ;;
        *)       bad "${svc}: ${status}" ;;
    esac
done

# -- 4. Restart loops --------------------------------------------------------
head_ "Restart counts"
for svc in $SERVICES; do
    cid="$(compose ps -q "$svc" 2>/dev/null)"
    [ -z "$cid" ] && continue
    count="$(docker inspect --format='{{.RestartCount}}' "$cid" 2>/dev/null)"
    [ "$count" = "0" ] && ok "${svc}: 0 restarts" || bad "${svc}: ${count} restarts -- possible crash loop"
done

# -- 5. Integrated origin ----------------------------------------------------
# Also the check that catches nginx holding stale upstream addresses after
# container recreation: the services above can all be healthy while these fail.
head_ "Integrated origin (${ORIGIN})"
for route in /healthz / /ratools/ /signin /documents; do
    got="$(code_for "${ORIGIN}${route}")"
    [ "$got" = "200" ] && ok "${route} -> 200" || bad "${route} -> ${got} (expected 200)"
done

# -- 6. Backend readiness ----------------------------------------------------
head_ "Backend readiness"
READY="$(curl -s --max-time 15 "${ORIGIN}/api/regx/v1/readiness/" 2>/dev/null)"
echo "$READY" | grep -q '"status":"ready"'   && ok "readiness: ready"    || bad "readiness: not ready"
echo "$READY" | grep -q '"database":"ok"'    && ok "readiness: database" || bad "readiness: database not ok"
echo "$READY" | grep -q '"cache":"ok"'       && ok "readiness: cache"    || bad "readiness: cache not ok"

# -- 7. Authorisation still enforced -----------------------------------------
# A representative protected endpoint. 404 would mean the route is unwired; 200
# would mean anonymous access, which is worse than a failed deploy.
head_ "Authorisation"
for api in /api/regx/v1/formulations/products/ /api/regx/v1/fda-data/releases/; do
    got="$(code_for "${ORIGIN}${api}")"
    case "$got" in
        401|403) ok "${api} -> ${got}" ;;
        *)       bad "${api} -> ${got} (expected 401 or 403)" ;;
    esac
done

# -- 8. Request correlation --------------------------------------------------
head_ "Request correlation"
PROBE_ID="$(python -c 'import uuid; print(uuid.uuid4())' 2>/dev/null)"
RETURNED="$(curl -s -D - -o /dev/null --max-time 15 \
    -H "X-Request-ID: ${PROBE_ID}" "${ORIGIN}/api/regx/v1/version/" 2>/dev/null \
    | tr -d '\r' | awk 'tolower($1) == "x-request-id:" { print $2 }')"
if [ -n "$RETURNED" ]; then
    ok "response carries X-Request-ID"
else
    bad "no X-Request-ID on the response"
fi
[ "$RETURNED" = "$PROBE_ID" ] && ok "supplied request id was honoured" \
                              || bad "supplied request id not echoed (got '${RETURNED}')"

# -- 9. Structured logs ------------------------------------------------------
head_ "Operational logging"
LOGS="$(compose logs --no-log-prefix --since 60s backend 2>/dev/null | grep '^{' || true)"
if [ -z "$LOGS" ]; then
    bad "no JSON log lines from backend in the last 60s"
else
    if echo "$LOGS" | python -c '
import json, sys
bad = 0
for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    try:
        json.loads(line)
    except Exception:
        bad += 1
sys.exit(1 if bad else 0)
' 2>/dev/null; then
        ok "backend log lines parse as JSON"
    else
        bad "some backend log lines are not valid JSON"
    fi
    echo "$LOGS" | grep -q "$PROBE_ID" && ok "probe request is correlatable in the log" \
                                       || bad "probe request id not found in backend logs"
fi

# -- 10. No obvious secret in recent output ----------------------------------
# Defence in depth, not a guarantee -- see docs/OPERATIONAL_LOGGING.md. The
# matched text is never echoed; only the fact of a match.
head_ "Secret exposure in recent output"
RECENT="$(compose logs --no-log-prefix --since 5m backend celery 2>/dev/null || true)"
if echo "$RECENT" | grep -qiE "DJANGO_SECRET_KEY=|POSTGRES_PASSWORD=|MFA_ENCRYPTION_KEY=|COMPANY_SECRET_KEY=|sk-proj-|-----BEGIN|Bearer [A-Za-z0-9._-]{20,}"; then
    bad "a credential-shaped string appears in recent service output -- investigate (value not printed here)"
else
    ok "no credential-shaped string in recent service output"
fi

# -- 11. Celery ---------------------------------------------------------------
# Targeted ping, matching the healthcheck contract: asks THIS worker to answer.
head_ "Celery worker"
if compose exec -T celery sh -c 'celery -A regx inspect ping -d celery@$(hostname) --timeout 5' >/dev/null 2>&1; then
    ok "worker replied to a targeted inspect ping"
else
    bad "worker did not reply to a targeted inspect ping"
fi

# -- 12. Audit subsystem -----------------------------------------------------
# Read-only. The regulated audit trail is AuditEvent rows, NOT the operational
# logs checked above -- this asks only whether that subsystem is reachable.
# It counts; it never writes an event.
head_ "Audit subsystem (read-only)"
if compose exec -T backend python -c "
import django, os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'regx.settings.production')
django.setup()
from audit.models import AuditEvent
AuditEvent.objects.count()
" >/dev/null 2>&1; then
    ok "AuditEvent is queryable"
else
    bad "AuditEvent is not queryable"
fi

# -- 13. Migration state -----------------------------------------------------
head_ "Migration state"
if compose exec -T backend python manage.py migrate --check >/dev/null 2>&1; then
    ok "no unapplied migrations"
else
    bad "unapplied migrations exist -- the deployed code expects a schema that is not present"
fi
if compose exec -T backend python manage.py check >/dev/null 2>&1; then
    ok "django system check"
else
    bad "django system check failed"
fi

# -- Result ------------------------------------------------------------------
echo
echo "-------------------------------------------------------------"
echo "  passed: ${PASS}   failed: ${FAIL}"
if [ "$FAIL" -gt 0 ]; then
    echo "  RESULT: FAIL -- see docs/RELEASE_ROLLBACK_RUNBOOK.md section 9"
    echo "-------------------------------------------------------------"
    exit 1
fi
echo "  RESULT: PASS -- technical checks only, not business acceptance"
echo "-------------------------------------------------------------"
