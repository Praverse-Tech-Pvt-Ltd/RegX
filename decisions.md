# Decisions

One entry per meaningful decision. Newest first.

## 2026-09-08 — Rebuild the local database instead of patching the snapshot
- Decision: build `db.sqlite3` fresh with `migrate --run-syncdb`, then port 7,679
  reference rows from `db_17_1_2.sqlite3` copying only columns present in both
  schemas.
- Alternatives considered: (a) keep the snapshot and `ALTER TABLE` in the 135
  missing columns plus 24 missing tables; (b) keep the snapshot as-is.
- Why this one won: the snapshots are far behind the models, and (a) would have
  meant inventing `NOT NULL` defaults with no migration history to check against.
  (b) left login and every authenticated page 500ing. The fresh DB is verifiably
  consistent with the models (0 missing tables, 0 missing columns).
- Cost accepted: no FDA 483 or warning-letter data locally; repopulate via the
  `import_*` management commands.
- Model: Claude Opus 5.

## 2026-09-08 — Gate OpenAI summary generation behind an env flag, default off
- Decision: add `ENABLE_OBSERVATION_SUMMARIES`, default `False`, checked at the top
  of `process_observation_summary()`.
- Alternatives considered: (a) let it run and pay; (b) revert to the stale snapshot,
  whose missing table blocked the path; (c) remove the hardcoded key.
- Why this one won: (a) has an unbounded and unpredictable bill; (b) trades a
  billing bug for a broken app; (c) was explicitly out of scope. The gate stops
  generation while still serving summaries already present in the data.
- Note: the fix was prompted by an incident — see `handoff.md` §5.
- Model: Claude Opus 5.

## 2026-09-08 — Admin sees all submissions, read-only, still authorisation-gated
- Decision: the 64 new `else` branches give `role="admin"` every submission for
  that report type, with `view_sample = False` and `flag = False` (no
  approve/reject controls).
- Alternatives considered: (a) show admins nothing (empty list); (b) treat admin as
  `company_user`; (c) give admins a position in the 7-level checker workflow.
- Why this one won: "admin sees everything" already has precedent in
  `show_regulatory_audit_trail`. (a) leaves the role useless; (b) misrepresents
  ownership; (c) would be inventing workflow semantics the codebase does not
  define. The pre-existing `assigned_report` gate still applies, so this widens
  visibility without widening authorisation — verified.
- Correction made during review: the first implementation used `.objects.all()`,
  which dropped the report-type filter as well as the user filter and bled
  checklists across dosage forms. Queries now keep each view's own non-user
  filters.
- Model: Claude Opus 5.

## 2026-09-08 — Review-gate admin is view-only rather than field-locked
- Decision: `RegulatoryReviewGateAdmin` extends `_ReadOnlyModelAdmin`.
- Alternatives considered: make only `status`/`version`/`version_locked` read-only;
  leave it fully editable.
- Why this one won: gates are created by `gap_analysis.py` and advanced only by
  `review_gate_action`, which writes an audit entry. Nothing legitimately edits one
  by hand, and `ModelAdmin.save_model()` would mutate a gate with no
  `RegulatoryAuditTrail` record — an unaudited path in a Part 11 system. Verified:
  POST to change/delete → 403, audited path still works.
- Model: Claude Opus 5.

## 2026-09-08 — Keep `settings.env()` re-reading through decouple
- Decision: `env()` calls `config()` twice on the non-blank path.
- Alternative considered: `cast(raw)` — one read, two lines shorter.
- Why this one won: `bool("False")` is `True`, so the shorter form made
  `DEBUG=False` resolve to `True` — production with debug on, and the `SECRET_KEY`
  guard (`if not DEBUG`) silently bypassed. Tested and reverted. A comment in the
  code records this.
- Model: Claude Opus 5.

## 2026-09-08 — HSTS starts at 1 hour, subdomains and preload left off
- Decision: `SECURE_HSTS_SECONDS` defaults to 3600 in production;
  `SECURE_HSTS_INCLUDE_SUBDOMAINS` and `SECURE_HSTS_PRELOAD` are not set, so
  `check --deploy` still reports W005 and W021.
- Alternative considered: 31536000 with both flags on, for a clean check output.
- Why this one won: browsers honour HSTS for the full `max-age` and it cannot be
  withdrawn early. A wrong value strands the domain; preload is effectively
  permanent. A clean check report is not worth an irreversible commitment made on
  someone else's behalf.
- Model: Claude Opus 5.

## 2026-09-08 — Preserve the `first_name` status key rather than fix it
- Decision: `checker_has_open_review()` looks up
  `statues[level][str(user.id)][user.first_name]`, exactly as the code it replaced.
- Alternative considered: key by user id alone, or fall back to an integer key.
- Why this one won: the task was a crash fix. Changing the key would alter *who can
  approve what*, which is a workflow change needing sign-off. The latent bug —
  renaming a user orphans their in-flight reviews — is recorded in `handoff.md`
  instead.
- Model: Claude Opus 5.

## 2026-09-08 — Delete `purge_test_accounts`, keep its knowledge
- Decision: removed the 47-line management command; the one-liner and the
  surrounding context live in `CLAUDE.md`.
- Alternative considered: keep the command with its `--dry-run` flag.
- Why this one won: it automated a once-ever action, and `--dry-run` was
  flexibility nobody asked for. Deleting code only works if the reason it existed
  survives somewhere readable.
- Model: Claude Opus 5.
