# Data integrity issues found and fixed, November 2026

**Date:** 2026-11-27. **Covers:** QA-08, QA-09, QA-10 and QA-18 from the independent code review of 19 November 2026 (`docs/qa/QA_CODEX_REPORT.md`), plus two related audit-trail changes (#162, #163). All six changes are merged into `regx-main`.

## How they were found

1. **Code review (19 Nov).** An independent review (Codex) read the code and marked these four as **suspected**: it saw how they could go wrong but did not try to make them happen.
2. **Proof against PostgreSQL (20–23 Nov).** Each one was then reproduced with a real test on PostgreSQL, the database REGX runs on: two connections doing the same thing at the same moment, a database trigger that makes audit writes fail on purpose, and direct SQL. All four were **confirmed** (PR #154, kept as evidence and closed, not merged).
3. **Fix (23 Nov).** Each fix brought that test over. The test fails on the code before the fix and passes after it. Every fix also passed the full local test suite and a check against a copy of the development database.

## What was wrong and how it was fixed

| Issue | What was wrong, in plain words | Fix | How it was tested |
|---|---|---|---|
| **QA-08** | If two people approved two different versions of the same product at the same moment, the product could end up with **two approved versions**. | **#159.** Approval now locks the product first, so approvals of one product run one after the other. The database also refuses a second approved version per product. | 2 tests: two simultaneous approvals, plus a direct SQL insert. Both fail before the fix. Dev-DB copy: 0 products with two approved versions. Live: two simultaneous approvals left one approved and one superseded. |
| **QA-09** | In some places a change was saved first and its audit record written separately. If the audit write failed, the change stayed **with no audit record**. | **#160.** All 155 places that write an audit record were listed and checked. Every place that could split was changed so the change and its record are saved together or not at all. | 27 tests that make the audit write fail on purpose. Each checks that the change is rolled back. All fail before the fix. Live: with audit writes failing, adding a component returned an error and nothing was saved. |
| **QA-10** | Two imports of the same FDA data at the same moment (same content, different line endings) could **both be registered**. | **#158.** The database refuses a second ordinary import with the same content fingerprint. The refused import gets a clear "duplicate" answer (command exit code 3; API 409) instead of a server error. | 1 two-connection test, which fails before the fix (4 tests in all). Dev-DB copy: 0 duplicates. Live: two simultaneous imports; one was accepted and one refused. |
| **QA-18** | A protection in the database left the "submitted by" and other review fields **changeable while a formulation version was under review**. The self-approval check could then read a changed value. | **#157.** The database rule now freezes those fields during review, and the self-approval check reads the value from before the change. | 8 tests using direct SQL; 7 fail before the fix. Dev-DB copy: 0 versions under review. Live: the SQL was refused. |
| **MFA audit gap** | Setting up MFA, activating it and using a recovery code wrote **no audit record at all**. | **#162.** Each now writes one record, saved together with the change. The record holds counts only, never the secret, a code or the recovery codes. | 11 tests (7 fail before the fix). Records were checked against the real secret and codes to confirm none appear. Live: one record each for enrol, verify, recovery and reset. |
| **Audit in the same transaction** | Seven checklist and assessment events were written only after the change was saved ("on commit"), so a failure in between could lose the record. The controlled export could hand out a file without a saved record. | **#163.** All seven are now saved together with the change. The export saves its record first and refuses to release the file (503) if it cannot. The design spec was amended to match (owner's decision, 23 Nov). | 23 new tests (17 fail before the fix). Live: one approval wrote one record; one real export wrote exactly one record; with audit writes failing, the export was refused and no file was released. |

## What this means

- **No sign that wrong data was created.** On a copy of the development database, no product had two approved versions, no import was duplicated, and no version was under review when its stamps could have changed. These were gaps in the protections, not failures seen in use.
- **What was not checked:** any server outside this machine. Whether the code before these fixes ran anywhere else, and whether any data there was affected, is not known from this work. This was a code and test review, not an audit of production data.
- **Where the details are:** the four rows of §11 item 37 and the Work Log entries for 20–23 November in `PROJECT_OVERVIEW.md`, and the PR descriptions of #154 and #157–#163.
