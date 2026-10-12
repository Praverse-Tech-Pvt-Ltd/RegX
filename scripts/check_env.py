#!/usr/bin/env python3
"""Pre-flight environment check. Run before starting the REGX stack.

Validates the *actual* contract, reconstructed from `compose.yaml` and the
Django settings rather than from documentation.

This script previously required `DATABASE_URL`, which nothing in the codebase
reads -- the backend reads `DB_NAME`/`DB_USER`/`DB_PASSWORD`/`DB_HOST`/`DB_PORT`
-- and omitted `POSTGRES_PASSWORD` and `COMPANY_SECRET_KEY`, both of which
compose hard-requires with `:?` guards. It therefore failed on a correct
environment and passed on one that could not start. It was also wired into
nothing, so the discrepancy never surfaced.

The required set below is exactly the four variables compose guards. Everything
else either has a safe default or is supplied by compose itself; see
docs/DEPLOYMENT_BOUNDARIES.md.

With `--production`, the stub malware scanner is a failure rather than a note:
`DOCUMENT_SCANNER_BACKEND` unset or `stub`, or `DOCUMENT_SCANNER_ALLOW_STUB`
set, means uploads would be marked clean without being scanned. Without the
flag the behaviour is unchanged, because the local compose stack and CI run the
stub on purpose.
"""

from __future__ import annotations

import argparse
import os
import sys

_TRUTHY = {"1", "true", "yes", "on"}

#: The four variables `compose.yaml` guards with `:?`. Without any one of them
#: `docker compose config` fails before a container starts. Keep this list in
#: step with those guards -- it is the same contract, checked earlier and with a
#: friendlier message.
REQUIRED = [
    "DJANGO_SECRET_KEY",
    "POSTGRES_PASSWORD",
    "MFA_ENCRYPTION_KEY",
    "COMPANY_SECRET_KEY",
]

#: Substrings that indicate a template value was copied without being replaced.
#: Applied to every required variable: a placeholder secret is worse than a
#: missing one, because it starts successfully.
PLACEHOLDER_MARKERS = [
    "change-me",
    "changeme",
    "insecure",
    "example",
    "placeholder",
    "your-",
    "dummy",
    "test-key",
]

#: Read but never required: compose supplies them, or the settings default is
#: safe. Reported only as information, never as failure.
INFORMATIONAL = [
    "INTEGRATED_APP_URL",
    "COMPANY_BASE_URL",
    "COMPANY_SERVER_MODE",
    "DOCUMENT_SCANNER_BACKEND",
]


def _scanner_failures() -> list[str]:
    """Production-only: the reasons uploads would not actually be scanned."""
    failures = []
    backend = os.environ.get("DOCUMENT_SCANNER_BACKEND", "").strip() or "stub"
    if backend == "stub":
        failures.append(
            "DOCUMENT_SCANNER_BACKEND is 'stub' (or unset) -- every upload would be "
            "marked CLEAN without being scanned. Set it to 'clamav'."
        )
    if os.environ.get("DOCUMENT_SCANNER_ALLOW_STUB", "").strip().lower() in _TRUTHY:
        failures.append(
            "DOCUMENT_SCANNER_ALLOW_STUB is set -- it switches off the production "
            "refusal to run the stub scanner. Remove it (compose.yaml defaults it to true)."
        )
    return failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--production",
        action="store_true",
        help="also fail if the stub malware scanner would be active",
    )
    args = parser.parse_args(argv)

    missing: list[str] = []
    placeholders: list[str] = []
    scanner = _scanner_failures() if args.production else []

    for var in REQUIRED:
        value = os.environ.get(var, "").strip()
        if not value:
            missing.append(var)
            continue
        lowered = value.lower()
        for marker in PLACEHOLDER_MARKERS:
            if marker in lowered:
                # The value itself is never printed -- only which variable and
                # which marker matched.
                placeholders.append(f"{var} still contains the placeholder text {marker!r}")
                break

    for message in (f"FAIL: missing required environment variable: {v}" for v in missing):
        print(message, file=sys.stderr)
    for message in placeholders:
        print(f"FAIL: {message}", file=sys.stderr)
    for message in scanner:
        print(f"FAIL: {message}", file=sys.stderr)

    if missing or placeholders:
        print(
            "\nSee docs/DEPLOYMENT_BOUNDARIES.md section 2. These four are the only "
            "variables with no default; everything else compose supplies or defaults.",
            file=sys.stderr,
        )
    if scanner:
        print("\nSee docs/DEPLOYMENT_BOUNDARIES.md section 3 (malware scanner).", file=sys.stderr)
    if missing or placeholders or scanner:
        return 1

    print("OK: all four hard-required environment variables are present and non-placeholder.")

    unset = [v for v in INFORMATIONAL if not os.environ.get(v, "").strip()]
    if unset:
        print(f"note: using defaults for {', '.join(unset)} (see DEPLOYMENT_BOUNDARIES.md section 3)")

    if os.environ.get("DOCUMENT_SCANNER_BACKEND", "stub").strip() == "stub":
        print(
            "note: DOCUMENT_SCANNER_BACKEND is 'stub' -- uploads are NOT scanned. "
            "Set a real scanner before accepting production uploads."
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
