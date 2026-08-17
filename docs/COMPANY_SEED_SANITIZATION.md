# Company Seed Sanitization and Credential Rotation

Two separate security items, recorded together because both were found while
preparing the company-site integration for merge.

- **Section 1** — what was removed from the committed database seed. Done.
- **Section 2** — credentials that only the owners can revoke. **Outstanding.**

---

## 1. The committed `db.sqlite3` seed has been sanitized

`company_site/db.sqlite3` is retained deliberately: it is the only reason the
legacy company pages render anything (homepage counters, Audit IQ, the 217
gated tools). See `COMPANY_RUNTIME_ASSETS.md` for why it is versioned at all.

It arrived carrying real authentication material. That has been removed from
the copy under `company_site/`, **and from this branch's history**, so it is
not retrievable from the repository at any commit.

The read-only company source at `Booking final/booking-demo-final/` was not
touched — it still holds the original database, byte-identical.

### What changed

| Item | Before | After |
| --- | --- | --- |
| `django_session` rows | 2 | **0** |
| Usable password hashes (`pbkdf2_sha256`) | 9 | **0** |
| Unusable passwords (Django `!`-prefixed) | 0 | **9** |
| `last_login` timestamps | 2 | **0** |
| `authtoken_token` rows | 0 | **0** |
| Non-empty user emails | 1 | **0** |
| Non-empty personal names | 9 | **0** |

Passwords were replaced with Django's unusable-password form — `!` followed by
40 random characters, exactly what `set_unusable_password()` writes.
`check_password()` returns `False` for any value beginning with `!`, so no
credential can authenticate against these rows.

`VACUUM` was run afterwards, so the freed pages are gone rather than lingering
as unreferenced data: a raw byte scan of the file finds no `pbkdf2_sha256$`
string anywhere.

### What was deliberately kept

The 9 user **rows** remain, because other tables reference them by integer id:

- `AdminMaster_assignchecker.user_id` — 8 rows of real checker-workflow
  configuration
- 7 `AdminMaster_assignchecker_assigned_checker_level_*` join tables — 1 row each
- `django_admin_log.user_id` — 9 rows

Deleting the users would break that company configuration. Roles
(`admin`, `company_checker`, `company_user`), `is_active`, `is_staff` and
`is_superuser` are preserved so application logic behaves as the company built
it. `username` was replaced with `disabled-user-<id>`, which keeps the column's
uniqueness constraint satisfied while carrying no personal information.

Anonymisation was safe because every relationship is by integer id, not by
email or name. The only functional reader of those fields is an SMTP
notification path in `RATools/views.py` that is not configured in this stack.

**Company business and regulatory data is untouched** — 12,036 rows across 30
tables, including 6,306 ANDA records, 2,025 Form 483 observation contents, 851
observations and 187 Form 483 masters.

### There is no demo login in the repository

No account in the seed can authenticate, and no demo credential is committed.
The integration tests do not need one: every company page they exercise
(`/`, `/ratools/`, `/termsofuse/`, `/adminmaster/login/`, Audit IQ) is public.

If you need to click through an authenticated company screen locally:

```bash
COMPANY_DEMO_EMAIL=dev@example.invalid \
COMPANY_DEMO_PASSWORD='<a password you choose>' \
docker compose exec company_site python manage.py create_demo_user
```

`AdminMaster/management/commands/create_demo_user.py` has no default password,
refuses to run without both variables, requires at least 12 characters, and
refuses to run when `DEBUG` is False unless explicitly forced. The account it
creates exists only in your local database.

---

## 2. OUTSTANDING — credentials the owners must rotate

A pre-push scan found live credentials inside the company application code.
They were removed from our copy and purged from this branch's history before
the branch was ever published, so they were never pushed to GitHub.

**Removing them from our branch does not invalidate the original credentials.**
They are still present in the company's own source tree at
`Booking final/booking-demo-final/`, which is read-only to us and which we did
not modify. Anyone with a copy of that folder still has working credentials.

**These require provider-side rotation or revocation. Nothing we did revokes
them.**

| Credential | Where it was | Action required |
| --- | --- | --- |
| OpenAI project key #1 | `AIDatabase/filters.py` (active code) | Revoke in the OpenAI dashboard, issue a replacement |
| OpenAI project key #2 | `AIDatabase/filters.py` (commented) | Revoke |
| OpenAI project key #3 | `AIDatabase/views.py` (commented) | Revoke |
| SMTP password | `RAAI/settings.py` (commented) | Change on the mail provider |

Three distinct OpenAI project keys in total, appearing across 8 lines. One was
in live code; the rest sat in commented-out blocks, which does not make them
any less valid.

Values are not reproduced here or anywhere else in this repository.

**Rotation status: NOT CONFIRMED.** No one has told us these have been
rotated, and we have no way to verify it. This line should be updated only
when an owner confirms the keys are dead.

Once rotated, the replacement values belong in the environment, never in code.
`filters.py` now reads `OPENAI_API_KEY` from the environment; the ChatGPT
synonym lookup it feeds has no live callers, so leaving that variable unset
simply leaves the dead feature dormant.
