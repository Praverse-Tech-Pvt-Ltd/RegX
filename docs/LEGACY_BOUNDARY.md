# Legacy Boundary

## What is the legacy codebase?

The `main` branch of this repository contains the original booking demo application (iCretegy booking system). It includes:

- `AIDatabase/` — AI assistant Django app
- `AdminMaster/` — admin app
- `RAAI/` — project settings for booking demo
- `RATools/` — regulatory tools (legacy)
- `templates/`, `static/`, `staticfiles/`, `media/`

## What is REGX?

REGX is a clean-room implementation on the `regx-main` orphan branch. It shares **no code, no migrations, and no database schema** with the legacy codebase.

## `company_site` is on `regx-main` — and that changed what this page means

This document originally described `regx-main` as excluding the legacy tree
entirely. That is **no longer accurate**. Commit `87cc45a` ("Carry the company
website into REGX as its own service") brought `company_site/` onto `regx-main`
as its own container, and it is served, tested and maintained here.

What did **not** change is the code boundary. `company_site` runs as a separate
Django project against its own SQLite database. REGX imports nothing from it,
it imports nothing from REGX, and no legacy data is migrated into the REGX
database. The two share a repository and a compose stack, not a codebase.

For a surface-by-surface classification of the legacy tree — what is required,
what is superseded, what is governance-sensitive and what may safely be removed
— see [LEGACY_RATOOLS_CLASSIFICATION.md](LEGACY_RATOOLS_CLASSIFICATION.md).

## Enforcement

- `company_site/` is present on `regx-main` as a separate service. The
  historical `.gitignore` exclusion described in earlier revisions of this page
  no longer applies.
- The import-linter contract `no-aidatabase-imports-anywhere` bans `AIDatabase` imports in all REGX modules.
- The CI guard test `TestNoAIDatabase` scans every Python file for references to `AIDatabase`.
- No legacy 483 data may be migrated into the REGX database.
- `company_site` has **no audit infrastructure of its own**; see
  [LEGACY_RATOOLS_CLASSIFICATION.md](LEGACY_RATOOLS_CLASSIFICATION.md) §4.3.

## Why orphan branch?

An orphan branch (`git checkout --orphan regx-main`) creates a branch with no shared commit history. This gives REGX a clean git history independent of the booking demo commits.
