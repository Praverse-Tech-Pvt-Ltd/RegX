# Admin verification checklist

**Date:** 2026-11-13. **Why:** the repositories cannot show what happened outside git (registries, deployments, key usage, visibility changes). Pratham's direction §1B: "absence of a push command is not evidence". These checks need account access that this session does not have; **none of them has been done.**
**Related:** credential register `docs/CREDENTIAL_INVENTORY.md` §9 (rows C1–C19), plan v2 §A.2–A.3, tracker rows "Security".

**How to use it**
- Each check names **who must do it**, **where** (menu path or URL), **what to look for**, and **how to record the result**.
- **Path confidence:** **[Sure]** = I am confident of the path; **[Check]** = provider menus change; the path may differ slightly, search the provider's docs for the named feature.
- **Record every result** in the table at the end: date, who checked, what was seen, a screenshot file name (stored in the company drive, **not** in a git repository), and "independently re-checked by". **Never paste a key, token, password or full key suffix into the record, a ticket or chat.**
- "Org" = the GitHub organisation `Praverse-Tech-Pvt-Ltd`.

---

## G. GitHub (org owner)

| ID | Check | Where | What to look for | Record |
|---|---|---|---|---|
| G1 | Container packages `ipharmai-api`, `ipharmai-nginx` | `https://github.com/orgs/Praverse-Tech-Pvt-Ltd/packages` [Sure]. Also each member's own profile → Packages, in case images were pushed to a personal namespace [Sure] | Any package with those names (or any image at all). If found: its visibility (public/private), versions and dates, and download count | "None found" or package name, visibility, version list, first/last publish date. If public: **escalate the same day** |
| G2 | Repository visibility changes | Org **Settings → Logs → Audit log** (URL `https://github.com/organizations/Praverse-Tech-Pvt-Ltd/settings/audit-log`) [Check: "Logs" sits under the "Archive" group in recent UI] | Filter `action:repo.access` (visibility change) and `action:repo.create`. Look for any of `RegX`, `booking-demo-final`, `Django-booking-demo-page`, `483-AI-final`, `iCretegy-SaaS`, `OCR-FDA` ever being made public, and when `iCretegy-AI483` / `iPharmaAi-booking-demo-page` were made public | Each event: repo, old → new visibility, actor, date. Note the audit log's retention limit (it may not reach back to February) [Check] |
| G3 | Members allowed to create public repos or change visibility | Org **Settings → Member privileges** [Sure]: "Repository creation" and "Repository visibility change" | Whether members (not only owners) can create public repositories or change visibility | Current setting; recommended: owners only |
| G4 | Collaborators per repository | Each repo **Settings → Collaborators and teams** (`/settings/access`) [Sure] for the 8 repos in G2 plus `iCretegy-AI483`, `iPharmaAi-booking-demo-page` | Every person and team with access and their role; **outside collaborators** (org **People → Outside collaborators**) [Sure]; anyone who has left the company | Table: repo, person/team, role, still needed yes/no |
| G5 | Installed GitHub Apps and authorised OAuth apps | Org **Settings → GitHub Apps** (under "Third-party Access"; URL `/settings/installations`) [Check] and **Settings → OAuth application policy** [Check] | Each app, which repositories it can read (deployment tools such as Render or Vercel, CI services, AI coding tools); any app with "All repositories" | App, repo scope, installed by, still needed yes/no |
| G6 | Forks and deploy keys | Each repo **Insights → Forks** [Sure] and **Settings → Deploy keys** [Sure] | Any fork (we saw 0 on 2026-11-06); any deploy key and its last use | Count and names |
| G7 | Actions secrets in `483-AI-final` | Repo **Settings → Secrets and variables → Actions** [Sure] | `GHCR_TOKEN`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `TAVILY_API_KEY` (register C17). The workflow that used them was removed on 2026-07-02 | Delete unused secrets; record which were deleted and whether the provider keys were rotated |

## R. Render (Render account owner)

| ID | Check | Where | What to look for | Record |
|---|---|---|---|---|
| R1 | Which services exist | Render **Dashboard** (lists all services) [Sure]; check every workspace/team the company uses [Check] | A service named `booking-demo-final` (from RegX `main`'s `render.yaml`) or any other service of these products; suspended vs running | Service name, type, status, URL, created date |
| R2 | Which repository and branch each deploys | Service → **Settings → Build & Deploy** ("Repository", "Branch") [Check] | Whether it deploys RegX `main`, `booking-demo-final` or `Django-booking-demo-page`. **Any of these runs with OpenAI key C in code** (register C5) | Repo, branch, auto-deploy on/off, last deploy date |
| R3 | Environment variables referencing leaked keys | Service → **Environment** [Sure] | Variables named `OPENAI_API_KEY`, `EMAIL_HOST_PASSWORD`, `SECRET_KEY`, `GEMINI_API_KEY`, `GOOGLE_API_KEY`. **Do not copy values**: compare the last characters in the OpenAI/Google dashboards privately | Variable names present; "matches a leaked key: yes/no/unknown" |
| R4 | Logs and access | Service → **Logs**, **Events** [Sure]; account **Members** [Check] | Recent traffic (is it used?), who can access the Render account | Last request date; member list |

## V. Vercel (Vercel account owner)

| ID | Check | Where | What to look for | Record |
|---|---|---|---|---|
| V1 | The booking demo site project | Vercel **Dashboard → Projects**; find the project behind the homepage URL listed on `iPharmaAi-booking-demo-page` [Sure] | Which team owns it; whether it is still deployed and public | Project name, team, production URL, status |
| V2 | Repository and branch | Project **Settings → Git** ("Connected Git Repository", "Production Branch") [Check] | Whether the `django-rewrite` branch (public `django-insecure` default, register C8) is or was deployed; preview deployments of other branches (**Deployments** tab) [Sure] | Repo, production branch, list of branches with deployments |
| V3 | Environment variables | Project **Settings → Environment Variables** [Sure] | `DJANGO_SECRET_KEY` set for Production and Preview (if not, the public default was in use); SMTP or API keys used by the booking form | Names present per environment; "secret key set: yes/no" |
| V4 | Access | Team **Settings → Members** [Check] | Who can see variables and deploy | Member list |

## C. Google Cloud (owners of the two Google keys)

| ID | Check | Where | What to look for | Record |
|---|---|---|---|---|
| C1 | Find each key's project | **Google AI Studio → API keys** (lists Gemini keys and their Cloud projects) [Check]; otherwise each project's **APIs & Services → Credentials** [Sure]. Match by the key's name and the last characters shown, privately | Project id and owner for key P1 (public `iCretegy-AI483`, register C1) and key R7 (`483-AI-final`, register C2) | Project id, key name, creator, created date (no characters of the key) |
| C2 | Usage since February | **APIs & Services → Enabled APIs & services → Generative Language API → Metrics**, filter by credential [Check]; **Billing → Reports** for the project [Sure] | Requests per day since 2026-02-20 (P1) and 2026-06-18 (R7); spikes, unknown regions, cost | A chart screenshot and the monthly totals |
| C3 | Revoke | Credentials page → the key → **Delete** (or **Regenerate**) [Sure]; or add API and application restrictions if it must stay alive [Sure] | After revocation, a test call with the old key fails | Date revoked; who confirmed the test call failed (independent person) |
| C4 | Project access | **IAM & Admin → IAM** [Sure] | Who can create or read keys in that project | Member list |

## Linked checks already in plan v2 §A.2

OpenAI (keys A–C: **Settings → API keys** and **Usage**) [Check], Microsoft 365 mailbox (sign-in logs, password reset) [Check], and the 483-AI-final server (who has root, which OpenAI key it holds; register C18). Same recording rules.

---

## Result record

| ID | Date | Checked by | Result (no values) | Evidence file (company drive) | Re-checked by | Done |
|---|---|---|---|---|---|---|
| G1 | | | | | | ☐ |
| G2 | | | | | | ☐ |
| G3 | | | | | | ☐ |
| G4 | | | | | | ☐ |
| G5 | | | | | | ☐ |
| G6 | | | | | | ☐ |
| G7 | | | | | | ☐ |
| R1 | | | | | | ☐ |
| R2 | | | | | | ☐ |
| R3 | | | | | | ☐ |
| R4 | | | | | | ☐ |
| V1 | | | | | | ☐ |
| V2 | | | | | | ☐ |
| V3 | | | | | | ☐ |
| V4 | | | | | | ☐ |
| C1 | | | | | | ☐ |
| C2 | | | | | | ☐ |
| C3 | | | | | | ☐ |
| C4 | | | | | | ☐ |

**Who:** GitHub checks need an org owner (Pratham or whoever holds owner rights). Render, Vercel and Google checks need the owner of each account; **if nobody can say who owns an account, that is itself a finding**: record it.
