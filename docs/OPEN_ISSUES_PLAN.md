# Open issues: estimates, dependencies and order (2026-11-27)

**Scope:**
- the 15 issues still present in the browser regression of 2026-11-25 (`docs/VALIDATION_REPORT_2026-11-25.md` §4);
- the IIG checklist authoring screens (`docs/IIG_AUTHORING_UI_SCOPE.md`).

**How the estimates are meant:**
- Working days for one developer who knows this codebase.
- Each estimate includes this project's fixed cost per change: tests written first, full local CI (about 1–1½ hours of machine time), a browser check on a rebuilt stack, and the 40 GPT cases. That adds about half a day to every item, however small.
- **These are estimates, not commitments.** A wide range means the work is not yet defined well enough to estimate tightly, usually because a decision is missing. Items marked **[decision first]** cannot be estimated properly until someone decides what "done" looks like.

## 1. The 15 open browser issues

| QA | Issue | Estimate | Depends on | Confidence |
|---|---|---|---|---|
| QA-11 | Irreversible actions on one click | **Supersede on an execution: done in #167 (open).** The rest, about 1–1½ days: confirmations for checklist version Reject, Retire and Supersede. | Nothing | High |
| QA-12 | Internal field names in errors (`non_field_errors: …`, `total_dosage_unit_weight: …`) | 1½–2 days | Nothing | High: one place (`frontend/src/lib/api.ts`), plus a label map per form |
| QA-10 | Session ended mid-task: technical message, no way back | 1 day | Nothing | High |
| QA-16 | Execution screen shows internal values (raw status, ISO timestamps, UUIDs, raw ID boxes) | 1–1½ days | Nothing | High |
| QA-25 | Long names overflow the page | ½ day | Nothing | High |
| QA-26 | "DEMO-Tenant (demo) (demo)" | ¼ day (with another item) | Nothing | High |
| QA-27 | Execution page unstyled | 1 day | Nothing | Medium: depends on how far the shared styles reach |
| QA-22 | Version screen details ("not yet calculated" on mass rows; the form keeps the last unit and meaning, N-6) | 1 day | Nothing | High |
| QA-20 | Upload details: a .docx typed as PDF is stored as PDF; the image-only warning is not on the list; no auto-refresh | 1½–2 days | Nothing | Medium: the file-type check is a server change and needs care around the scanner |
| QA-15 | Numbers without units and raw tokens on the IID preview (`30.800 percent_w_w`, six decimals, `DATA_REQUIRED`) | 2–3 days | **[decision first]** how many decimals to show and the wording of each token. Display only; the stored values do not change | Medium |
| QA-04 | Components and versions of a draft cannot be edited or deleted | 3–4 days | Nothing to start. **No edit or delete endpoint exists** (`backend/formulations/urls.py`), so this is API work (audited, draft-only, inside the database rules) plus UI | Medium |
| QA-09 | Phone width unusable | 2–4 days | **[decision first]** which pages must work on a phone (all of them, or only reading results) | Low: it touches the shell and every table |
| QA-21 | Home page leads to legacy tools | ½–1 day **after a decision** | **[decision first]** where the home page, "Explore RegX" and "Request access" should go, and whether the legacy items stay in the sidebar | High once decided |
| QA-17 | Dashboard empty | 2–4 days | **[decision first]** what each role should see (for example items waiting for me, recent results) | Low |
| QA-18 | Tenant Admin has no admin screens | 4–6 days | **[decision first]** which admin tasks are in scope (members, roles, MFA reset). The API has a member list, roles and an MFA reset; adding and removing members and assigning roles may need new endpoints | Low |

**Subtotal:** about **22–33 working days** for all 15. Of those, 10½–18 days are items that need a decision first (QA-09, QA-15, QA-17, QA-18, QA-21). Without those, the rest is about **12–15 days**.

## 2. IIG checklist authoring screens

From `docs/IIG_AUTHORING_UI_SCOPE.md` §4. The API changes are A1–A4 and the screens are S1–S8.

| Part | Estimate | Depends on |
|---|---|---|
| S1 + S3 + A1: execution scope and effective date in the UI (closes N-1 for synthetic and demo use) | about 2 days | Nothing |
| The rest of A1–A3 (A4 optional) | about 2–3 days | Nothing |
| S2, S4, S5, S8 | about 3–4 days | Nothing |
| S6: questions editor | about 1–1½ weeks (5–8 days) | Built best when the client's content is close, so its forms match the real content |
| S7: applicability rules | about 2–3 days | Same |
| **Total** | **about 15–20 working days (3–4 weeks)**, synthetic content only | **Real content cannot be activated** until the 20-item content gate is signed off (0 of 20). That also needs a named regulatory reviewer, approved option labels (5A-DEC-002) and Approval Register 13/14 |

## 3. Suggested order

1. **Land the open PRs first:** #166–#169 and the follow-ups opened on 2026-11-27. They close N-2, N-3, N-4, N-5, N-7, N-9 and QA-11 (Supersede), and add Reinstate and the server rule for Reject/Return. Nothing new should be built on top of unmerged work (the PR rule in `CLAUDE.md`).
2. **S1 + S3 + A1 (2 days).** This makes a checklist created in the UI executable, the biggest functional gap from the regression.
3. **Quick fixes that need no decision (about 7–9 days):** QA-12, QA-10, QA-16, QA-22 (with N-6), QA-25, QA-26, QA-27 and the rest of QA-11. Together they remove most of what a tester sees as unfinished.
4. **QA-04 (3–4 days) and QA-20 (1½–2 days):** real behaviour gaps that need server work.
5. **Ask for the five decisions now, in one message:** phone scope (QA-09), number display (QA-15), dashboard content (QA-17), admin scope (QA-18) and home-page links (QA-21). Build each item once its decision arrives.
6. **The rest of the authoring screens (S2, S4–S8)** once the client's IIG content is close, so the editor matches it.

## 4. What these numbers do not include

- **The other new issues from 2026-11-25:** N-6 (counted in QA-22), N-8 (MFA codes shown early, about ½–1 day) and N-10 (no export button, about 1 day).
- **Owner review and merge time.** Merges are paused until branch protection is confirmed (owner, 2026-11-27).
- **Client-blocked work:** calculators (SOW 2.3), real IIG content, the F-3 per-day rule (Q8) and the AI scope.
- **Rework if a decision changes what was built.**
