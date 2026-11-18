#!/usr/bin/env bash
# Real-stack browser check: every REGX page as each demo role, plus the main
# user flows, against a RUNNING integrated stack. Nothing is mocked.
#
#   REAL_STACK_PASSWORD=... scripts/real_stack_smoke.sh [--flows] [--origin URL] [--out DIR]
#
# Pages (always): signs in as doer, reviewer, vp and tenant_admin and opens every
# sidebar page, the "new" pages and one example of every detail page the data
# reaches. Records per page: loads yes/no, HTTP status, console errors, failed
# API calls, error text, screenshot ($OUT/pages.jsonl, $OUT/screenshots/).
#
# Flows (--flows): Doer creates a product, a formulation version and two
# components, runs an IID preview, answers and submits the seeded draft IIG
# checklist execution, uploads a PDF; the VP approves the execution.
#
# Prerequisites (the script checks nothing it cannot see and changes nothing):
#   * a stack migrated and seeded with `manage.py seed_regx_demo` (tenant "demo");
#   * REAL_STACK_PASSWORD: the demo password (environment only, never a file);
#   * for --flows: an ACTIVE FDA IID release with approved route/dosage-form
#     mappings (the IID preview needs real reference data), a seeded draft
#     checklist execution (a fresh seed has one; the flow consumes it), and
#     REAL_STACK_MFA_FILE: a local JSON file {email: TOTP secret} for the VP,
#     who must be enrolled in MFA to approve.
#
# It writes to the stack only what a user would (the flows create records).
# Run it against a local or test stack, never production.
set -euo pipefail

ORIGIN="http://localhost:8080"
OUT="${REAL_STACK_OUT:-$(pwd)/real-stack-results}"
FLOWS=0

while [ $# -gt 0 ]; do
    case "$1" in
        --flows) FLOWS=1; shift ;;
        --origin) ORIGIN="$2"; shift 2 ;;
        --out) OUT="$2"; shift 2 ;;
        -h|--help) sed -n '2,25p' "$0"; exit 0 ;;
        *) echo "unknown argument: $1" >&2; exit 2 ;;
    esac
done

if [ -z "${REAL_STACK_PASSWORD:-}" ]; then
    echo "REAL_STACK_PASSWORD is not set (the demo password; environment only)." >&2
    exit 2
fi
if [ "$FLOWS" = 1 ] && [ -z "${REAL_STACK_MFA_FILE:-}" ]; then
    echo "--flows needs REAL_STACK_MFA_FILE (the VP signs in with MFA)." >&2
    exit 2
fi

code=$(curl -s -o /dev/null -w '%{http_code}' -A "REGX-dev-research" "$ORIGIN/signin" || true)
if [ "$code" != "200" ]; then
    echo "The stack does not answer at $ORIGIN/signin (HTTP $code). Start it first." >&2
    exit 2
fi

mkdir -p "$OUT"
export REAL_STACK_URL="$ORIGIN" REAL_STACK_OUT="$OUT"
cd "$(dirname "$0")/../frontend"

specs=(e2e-real/pages.spec.ts)
if [ "$FLOWS" = 1 ]; then
    specs+=(e2e-real/flows.spec.ts)
fi

status=0
npx playwright test -c playwright.real.config.ts "${specs[@]}" || status=$?

echo
echo "Results: $OUT/pages.jsonl$([ "$FLOWS" = 1 ] && echo " and $OUT/flows.jsonl"), screenshots in $OUT/screenshots/"
exit "$status"
