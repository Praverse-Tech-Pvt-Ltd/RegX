# Client data check: every REGX environment on this machine (2026-11-27)

**Question:** do any of the databases or stores on this development machine hold client data, meaning anything that is not synthetic test data or seeded demo data?

**Answer:** **No client data was found on this machine.** Every user, product, document and checklist row found is one of three things:
- synthetic test data;
- seeded demo data;
- seeded sample data from the repository's own `seed_sample_data.py`.

The files in the document stores are test fixtures and public FDA data.

**Not checked: any server outside this machine** (staging, UAT, a client or cloud host, or the legacy iPharmaAI server). This document says nothing about them.

**When and how:**
- Run on 2026-11-26 07:16–07:35 UTC by this machine's clock. The file name follows the date of the owner's request.
- **Read-only queries only.** Each Postgres database was opened with `default_transaction_read_only=on`, so any write would have been refused (confirmed in the output: `read_only = on`).
- SQLite files were opened with `mode=ro&immutable=1`.
- File stores were mounted read-only (`:ro`).
- For each Postgres volume, a throwaway `postgres:16-alpine` container was started on it and removed afterwards. Nothing was migrated, changed or deleted.
- Email addresses are reported as domains only.

## 1. What was checked

| Environment (Docker volumes) | What it is | REGX Postgres: users / products / formulation versions / documents / checklist executions | User email domains | Rows not synthetic or seeded |
|---|---|---|---|---|
| `regx` (dev, since 2026-09-08) | The main development stack | 10 / 5 / 5 / 2 / 1 | `demo.regx.invalid` (4), `praverse.local` (3), `praverse.test` (3) | **None.** Four realistic product names in tenant `praverse` (for example "Metoprolol Succinate ER Tablets 50 mg") come from `seed_sample_data.py` in the repository. One document, "pypdf 6.20 upgrade check" (2026-10-12), was uploaded by a session to test the PDF library |
| `regx-codex` (2026-11-19) | The independent QA (Codex) | 11 / 11 / 18 / 8 / 12 | `demo.regx.invalid` (11) | None: every row is `DEMO-`, `QA-…` or "Synthetic …" |
| `regx-qa` (2026-11-18) | Browser test, 18 Nov | 4 / 2 / 2 / 4 / 1 | `demo.regx.invalid` (4) | None |
| `regx-s20` (2026-11-17) | Local test stack | 4 / 24 / 25 / 11 / 10 | `demo.regx.invalid` (4) | None |
| `regx-v25` (2026-11-25) | Browser regression and live checks | 4 / 13 / 11 / 5 / 3 | `demo.regx.invalid` (4) | None |
| `regx-val` (2026-11-19) | Validation run, 19 Nov | 4 / 59 / 58 / 3 / 7 | `demo.regx.invalid` (4) | None |
| 90 unnamed Postgres volumes | Left behind by CI and test containers (`regx_test`, `test_regx_test`), plus 4 `devcopy` databases (copies of the dev database made to check migrations) | 64 databases hold REGX tables | `demo.regx.invalid` (16), `praverse.local` (12), `praverse.test` (12), `example.test` (1) | **None.** The only rows not marked synthetic are in the 4 `devcopy` databases: the same seeded sample products and the same pypdf check document as the dev database. One volume was skipped because it belongs to the running test container (a fresh test database) |

**Also on the machine, not REGX:**
- 81 unnamed volumes hold neither Postgres nor Redis data, and 21 hold Redis data. They were classified and counted only.
- The Supabase volumes belong to a separate project (Elmiron) and were not opened.

## 2. Document stores (`<environment>_document_storage`)

| Environment | Files | What they are |
|---|---|---|
| `regx` (dev) | 27,237 | **Test-run leftovers and public FDA files.**<br>• Test runs inside the dev container wrote here; the dev database itself lists only 2 documents.<br>• Sampled: text files containing `SYNTHETIC`; PDFs of 1–48 bytes; 3,000,049-byte PDFs (the oversize-upload test); synthetic FDA fixtures ("SYNTH LABS", "Synthetic Pharma Inc", `EXCIPIENT-ALPHA`).<br>• Also copies of public FDA files: the Orange Book products file, the IID CSV and the SPL route terms.<br>• Files modified between 2026-09-08 and 2026-11-17.<br>• Not every file was opened: 25 text files and 15 PDFs were sampled, and every CSV header was read. |
| `regx-codex` | 951 | QA fixtures (not opened individually) |
| `regx-qa`, `regx-s20`, `regx-v25`, `regx-val` | 9, 16, 11, 13 | One per synthetic document listed in that database |

## 3. company_site databases (`<environment>_company_db`)

- **`regx-qa`, `regx-s20`, `regx-v25`, `regx-val`:** byte-identical to `company_site/db.sqlite3` in git (SHA-256 `81c5ac64…`).
  - Its 9 user accounts are already anonymised: `disabled-user-1` to `-9`, with no email, name, phone, address or company.
  - Its other filled tables hold public FDA content (483 observations, ANDA lists), the question banks of the legacy tools, and Django's own tables.
- **`regx` (dev):** the same file after use. 16 accounts: the 9 anonymised ones, `regx_admin`, `regx_checker` and `regx_user` (created by sessions), and four test addresses (`praverse.test` ×3, `demo.regx.invalid` ×1). Also 70 session rows.
- **`regx-codex`:** a separate synthetic file with no accounts.

## 4. Exact queries and scripts

All in the session folder `D:/Praverse/session-work/2026-11-27/`, with their raw output under `evidence/client_data_check/`.

| Step | Script | What it does |
|---|---|---|
| Named environments | `client_data_check.sh` + `tools/client_data_check.sql` | Starts Postgres on each `<env>_postgres_data` volume and runs the SQL file read-only, then lists the document store and the company_site volume read-only |
| Unnamed volumes | `classify_volumes.sh`, then `anon_db_check.sh` + `tools/anon_db_check.sql` | Classifies every unnamed volume (Postgres, Redis or other), then queries each Postgres one read-only |
| Document store sample | `tools/storage_sample.sh` | Largest files, date range, first lines of sampled files, PDF metadata |
| company_site files | `tools/company_db_check.py`, `tools/company_users_peek.py` | Table row counts and email domains; which user columns are filled (shown as "set" or "-", values never printed) |

The key queries from `tools/client_data_check.sql`, as run:

```sql
SELECT 'identity_user' AS t, count(*) FROM identity_user
UNION ALL SELECT 'formulations_productdevelopmentrecord', count(*) FROM formulations_productdevelopmentrecord
UNION ALL SELECT 'documents_document', count(*) FROM documents_document
UNION ALL SELECT 'iig_checklist_checklistexecution', count(*) FROM iig_checklist_checklistexecution;   -- and 7 more tables
SELECT split_part(email, '@', 2) AS domain, count(*), min(created_at)::date, max(created_at)::date
  FROM identity_user GROUP BY 1 ORDER BY 2 DESC;
SELECT t.slug, p.product_code, left(p.proposed_product_name, 60), left(p.active_ingredient, 40), p.created_at::date
  FROM formulations_productdevelopmentrecord p JOIN tenancy_tenant t ON t.id = p.tenant_id ORDER BY p.created_at;
SELECT t.slug, left(d.title, 70), d.created_at::date
  FROM documents_document d JOIN tenancy_tenant t ON t.id = d.tenant_id ORDER BY d.created_at;
SELECT left(original_filename, 70), size_bytes, created_at::date FROM documents_documentversion ORDER BY created_at;
SELECT left(code, 40), left(title, 70), created_at::date FROM iig_checklist_checklistdefinition ORDER BY created_at;
SELECT split_part(actor_email, '@', 2), count(*) FROM audit_auditevent GROUP BY 1 ORDER BY 2 DESC;
```

For the unnamed volumes, "not marked synthetic" means the code, name or title contains none of: demo, qa, synthetic, test, e2e, sample, example, fixture, zz, fake, dummy (`tools/anon_db_check.sql`). Every such row was then read by a person.

## 5. Beyond this machine: what git history and GitHub show (owner condition C)

Checked on 2026-11-26 (UTC 11:09 for GitHub) from the main checkout after `git fetch --prune origin`: 267 refs, 824 commits, both histories (`regx-main` and the legacy `main`). Scripts and raw output: `tools/c_history_scan.py`, `tools/c_hand_checks.sh`, `tools/c_github_access.sh` and `evidence/client_data_check/c_*.txt` in the session folder (copied into the review hand-off). Read-only throughout: no file in any account was changed, and no deployed site was requested.

### 5.1 Preview, branch or hosted deployments

| What was searched | Found | Who can reach it |
|---|---|---|
| `vercel.json`, `netlify.toml`, `render.yaml`, `fly.toml`, `Procfile`, `app.yaml`, `railway.json/.toml`, `heroku.yml`, `amplify.yml`, `firebase.json`, `.platform.app.yaml`, `now.json`, in every commit on every ref | **One file: `render.yaml`**, added in `8ed8cf4` (2026-07-22) on the legacy `main` branch and still at its tip. It defines a Render web service **`booking-demo-final`** (free plan, `gunicorn RAAI.wsgi`, `ALLOWED_HOSTS=.onrender.com`, `DEBUG=False`, `SECRET_KEY` generated by Render) | **If it is deployed, anyone on the internet** (a Render web service is public at its `onrender.com` address). Whether it exists can only be seen in the Render account. **Not requested from here on purpose:** it is the legacy app, and `docs/CREDENTIAL_INVENTORY.md` §4 records that a deployment of `main` calls OpenAI with the key in its code |
| Every workflow ever committed (`backend.yml`, `company-site.yml`, `docker-integration.yml`, `frontend.yml`, `operational-scripts.yml`) for deploy targets (Vercel, Netlify, Heroku, Render, Fly, Railway, Firebase, Google Cloud, Azure, AWS, SSH/rsync, kubectl, helm, `docker push`, GHCR, "deploy") | **None deploys anywhere.** The only hit is a comment in `operational-scripts.yml` (line 203) saying the script must never deploy | Nobody: CI only builds and tests (and GitHub Actions is switched off) |
| GitHub: environments, deployments, Pages, webhooks, Actions secrets, deploy keys | **None of each** (Pages: 404 not found) | Nobody |
| REGX itself (`regx-main`) | No hosting file. It runs only through `compose.yaml` on a developer machine | See 5.3 for the ports |

### 5.2 Cloud database URLs ever committed

Every added line in the whole history was scanned (`git log --all -p`, text conversion off) for `postgres://`, `postgresql://`, `mysql://`, `mariadb://`, `mongodb://`, `mongodb+srv://`, `redis://`, `rediss://`, and separately for known cloud database hosts (Supabase, Neon, AWS RDS, Azure Database, MongoDB Atlas, Upstash, Render, Railway, Heroku, Vercel, Netlify, Fly). **Values were never printed;** only the file, the commit and the kind of host.

- **No cloud database URL has ever been committed.** All 17 locations (in `.env.example`, `compose.yaml`, `backend.yml`, settings files of both apps, a test and four docs) point at a local service name (`db`, `redis`, `localhost`) or a placeholder.
- The one host the script could not classify is a placeholder: `docs/OPERATIONAL_LOGGING.md` (commit `9109e17`, line 188) shows the pattern `redis://user:password@host` as an example of what the log redaction hides.
- Cloud names without a URL: only `render.yaml` (above) and, in the legacy `.env.example` (`4193f09`), a comment `e.g. https://example.onrender.com` and empty `AZURE_*` placeholders.

### 5.3 Shared test accounts

| Accounts | Where they exist | Who can reach them |
|---|---|---|
| REGX demo users `doer@`, `reviewer@`, `vp@`, `tenant_admin@demo.regx.invalid` (`seed_regx_demo`) | Only in databases where someone ran the seed. On this machine: the environments in §1. The password is generated at seed time or taken from `--password-env`; it is not in the repo | Anyone who can reach a running stack. **`compose.yaml` publishes 5432 (Postgres), 6379 (Redis), 8000, 3000, 8001 and 8080 on every network interface, not only on localhost**, so while a stack runs, other machines on the same network may reach it, depending on the Windows firewall, which this session did not check |
| Legacy company_site demo admin and user (`company_site/create_demo_users.py`, passwords in the file) | Only where that script was run (manual step) | Anyone with read access to the repo can read the passwords (`docs/CREDENTIAL_INVENTORY.md` #6) |
| Six REGX demo passwords once written in `handoff.md` (removed 2026-10-12, still in history) | Only where demo users were created with them | Anyone with read access to the repo (`docs/CREDENTIAL_INVENTORY.md` #7) |
| 9 password hashes in the legacy `db_17_1_2.sqlite3` on `main` | In the file | Anyone with read access (`docs/CREDENTIAL_INVENTORY.md` #9) |

### 5.4 Everyone with access to the GitHub repository

Checked as the account this machine is signed in to (repository admin). Repository `Praverse-Tech-Pvt-Ltd/RegX`: **private**, owned by an organisation on the **free** GitHub plan, **0 forks**.

| GitHub login | Role on the repo | How |
|---|---|---|
| `coutprat` | admin | organisation owner |
| `praversetech` | admin | organisation owner |
| `praversetech2-sudo` | admin | organisation owner |
| `Rabbitshah` | admin | direct collaborator (organisation member) |
| `Patilhetal` | read | organisation member |
| `raj33720` | read | organisation member |

- Outside collaborators on the repo: **none**. Pending invitations: **none**. Teams: **none**. Deploy keys: **none**. Webhooks: **none**.
- **Organisation-wide outside collaborators: not visible** (GitHub answered 403, "You must be an owner of this organization"). **Installed GitHub Apps** (for example a Render or Vercel app that can read the repo): **not visible** from this account.
- **Branch protection:** `regx-main` reports `protected=false`. Both branch protection and rulesets were refused with "Upgrade to GitHub Pro or make this repository public to enable this feature" (HTTP 403), so on the current plan **branch protection cannot be switched on** for this private repository. See §12 of `PROJECT_OVERVIEW.md`.

## 6. Limits: what this machine could NOT check

- **Servers outside this machine were NOT checked.** Nothing here shows what runs on any server, laptop or cloud account.
- **The Render account:** whether `booking-demo-final` (or any service built from `main`) exists, what it stores and who has used it.
- **Any hosting or database account that git does not mention.** The history only shows what was committed; a service set up by hand leaves no trace here.
- **Organisation outside collaborators and installed GitHub Apps** (need an organisation owner), and GitHub audit logs.
- **Copies outside GitHub:** clones, zips, Docker images or hand-off folders that any of the six people above, or anyone they shared with, may hold. No workflow pushes an image, but a manual push cannot be seen from here.
- **The Windows firewall** on this machine, which decides whether the published stack ports are reachable from the local network.
- "Synthetic" is a judgement from names, codes, domains and seed scripts. A real record deliberately named like a test record would not have been noticed.
- In the dev document store, about 27,000 files were sampled, not all opened.
- The Elmiron Supabase volumes and the 102 unnamed non-Postgres volumes were not opened.
