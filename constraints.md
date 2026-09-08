# Constraints

Hard boundaries for anyone — human or AI — working on this repo. If a request
conflicts with one of these, flag the conflict rather than working around it.

## Money and external calls

- **Never start the dev server without checking `ENABLE_OBSERVATION_SUMMARIES` is
  off.** With it on, a single `GET /` fans out one OpenAI call per observation
  block — 8,362 in the bundled workbook, synchronously inside the request. This
  has already cost real money once (71 calls).
- **Never enable `ENABLE_OBSERVATION_SUMMARIES` without asking.** Run
  `python manage.py export_gpt_input_data --only-pending` first to see the cost.
- No new outbound API integrations without asking.

## Secrets

- `AIDatabase/filters.py` contains a live hardcoded OpenAI key, retained by
  explicit instruction. **Do not** remove it as a "cleanup" — it needs rotating at
  the provider first, and deleting the line does not invalidate the key.
- Never commit `.env`, `db.sqlite3`, or any `db.sqlite3.bak.*`. All are gitignored;
  keep it that way.
- Do not print, log, or paste key values into commits, PR bodies, or issues.

## Database

- **Never run `makemigrations` for `AdminMaster` or `AIDatabase` casually.** Those
  apps have no committed migrations and their schema exists only in the sqlite
  snapshots, which are 24 tables and 135 columns behind the models. Generating
  migrations there without a plan will produce something that does not match any
  real database.
- Never overwrite `db_17_1_2.sqlite3`, `db_old.sqlite3`, or `db_corrupted.sqlite3`
  — they are the only copy of the reference data (question banks, deficiency
  tables) and the only record of the pre-drift schema.
- Take a dated backup before any destructive DB operation.

## Audit trail (21 CFR Part 11)

- `RegulatoryAuditTrail` and `RegulatoryGapAnalysisReport` are immutable by design —
  their `save()`/`delete()` raise. Do not "fix" that.
- **Never add an editable admin, management command, or view that mutates
  `RegulatoryReviewGate` without writing a `RegulatoryAuditTrail` entry.** The only
  sanctioned mutation path is `RATools.views.review_gate_action`, which logs via
  `audit.log_event()`. This is why the review-gate admin is view-only.
- Write audit entries through `RATools.audit.log_event()`, never by constructing
  `RegulatoryAuditTrail` directly.

## Code boundaries

- **Do not merge the two role systems.** Legacy `CustomUser.role` +
  `AssignChecker` (7 checker levels) and the newer `RegulatoryRole`
  (doer/reviewer/vp) are deliberately separate so that changing one does not
  retroactively alter 483 workflow behaviour.
- `AIDatabase.models.ANDA` and `RATools.models.ANDAUserReports` etc. are unrelated
  despite the name collision, and both apps use `from .models import *`. Be
  explicit about which `ANDA` is meant.
- Match the existing procedural style in `views.py`. It is ~14.5k lines of one
  function per route; do not refactor it as a side effect of another task.
- New RATools logic goes in its own module (`audit.py`, `gap_analysis.py`), not
  into `views.py`.

## Dependencies

- No new dependencies without asking.
- Pin anything added. An unpinned `openai` is what broke the observation search —
  it resolved to a major version where `openai.ChatCompletion` no longer exists.

## Settings

- `settings.env()` re-reads through `decouple` for casting on purpose.
  **Do not simplify it to `cast(raw)`** — `bool("False")` is `True`, which silently
  turns on `DEBUG` in production. There is a comment saying this; leave it.
- Do not restate Django defaults in `settings.py`. Only settings whose default is
  wrong for this deployment belong there.

## Process

- Do not push to `main`. Branch, then open a PR.
- Do not claim a change works because the route returns 200 — a 200 does not catch
  wrong data. Check the rendered content or the database.
