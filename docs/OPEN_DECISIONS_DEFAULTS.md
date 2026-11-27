# Open decisions: recommended defaults (2026-11-27)

These are the five decisions listed in `docs/OPEN_ISSUES_PLAN.md` §3 step 5.
- **What each default is:** one recommendation and the reason, so that building can start if the owner agrees. The owner or the client can still change any of them.
- **What they are not:** decisions.
- **What changing one later costs:** rework, roughly the estimate in `OPEN_ISSUES_PLAN.md`.

| # | Decision | Recommended default | Reason |
|---|---|---|---|
| 1 | **Phone pages (QA-09)** | **Read-only on a phone:** sign-in, dashboard, lists, and result pages (IID preview result, checklist and execution status, documents list) must be readable at 375 px. Data entry and authoring stay desktop-only, with a plain "use a larger screen to edit" note | Regulatory data entry with wide tables is done at a desk. Making every form and table work on a phone is the 2–4 day upper end, and touches every page for little real use |
| 2 | **IID number display (QA-15)** | **Show 3 decimals for percentages and up to 6 significant digits for amounts, always with the unit** (for example "30.800 % w/w", "120 mg/day"). Keep the exact value in a tooltip, and replace raw tokens (`DATA_REQUIRED`, `percent_w_w`) with plain words | Matches what the percentage display already does (3 decimals, exact value on hover). A unit on every number removes the "daily exposure with no unit" problem found in the 2026-11-27 run. Stored values do not change |
| 3 | **Dashboard by role (QA-17)** | **One panel each: "Waiting for me"** (Doer: returned items; Reviewer: items to review; VP: items to approve; Tenant Admin: member and MFA issues) **plus "Recent results"** (last 10 IID previews and checklist executions in the tenant) | Uses data REGX already has (workflow states and audit events), so no new data model. Answers the first question each role has on sign-in. Scores and readiness claims stay out (the regulatory-claim rule) |
| 4 | **Admin screens (QA-18)** | **Tenant Admin can do three things:** list members, change a member's role, and reset a member's MFA. Adding new members stays an operator command for now | These use the member list, roles and MFA reset the API already has. Self-service member creation touches the "no self-registration" rule and needs new endpoints and a decision on invitations, so leave it for later |
| 5 | **Home-page links (QA-21)** | **The REGX home page (`/signin` → dashboard) is the entry point.** "Explore RegX" opens the REGX dashboard, and "Request access" opens a plain contact page (no self-registration). The legacy tools leave the main sidebar and go under one "Legacy tools" link | Users currently land in the legacy app by default. Pointing everything at REGX matches the platform's purpose. Keeping the legacy tools behind one link avoids removing anything a client may still use (the company_site rules in `constraints.md`) |

**If the owner accepts all five:** QA-09, QA-15, QA-17, QA-18 and QA-21 move from "[decision first]" to estimable. The upper ends of their ranges in `OPEN_ISSUES_PLAN.md` should then come down. The effect of a second developer is in `docs/SECOND_DEVELOPER_ESTIMATE.md`.
