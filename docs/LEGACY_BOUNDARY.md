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

## Enforcement

- The `.gitignore` on `regx-main` excludes all legacy directories and files.
- The import-linter contract `no-aidatabase-imports-anywhere` bans `AIDatabase` imports in all REGX modules.
- The CI guard test `TestNoAIDatabase` scans every Python file for references to `AIDatabase`.
- No legacy 483 data may be migrated into the REGX database.

## Why orphan branch?

An orphan branch (`git checkout --orphan regx-main`) creates a branch with no shared commit history. This gives REGX a clean git history independent of the booking demo commits.
