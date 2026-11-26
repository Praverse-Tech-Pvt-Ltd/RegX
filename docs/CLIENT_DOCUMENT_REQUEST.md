# Documents needed from the client

**Date:** 2026-11-27. **Source:** the owner's 19 Nov mail, "Documents needed from the client" (text supplied by Maanav in the 2026-11-27 session). **Status:** request list only. Nothing here has been sent to the client by this session.

**Order:** by what blocks development first. An item that stops engineering work today comes before one that only blocks sign-off or go-live. Where the repo already records the blocker, the document is named.

| # | What we need | What it blocks | Why this place in the order |
|---|---|---|---|
| 1 | **The 20-item gate list, and Approval Register items 13 and 14**, decided and signed. | All real checklist content (none may go live until the gate is signed: 0 of 20 approved, `docs/REGULATORY_CONTENT_GATE_20_ITEM_DECISION_INTAKE.md`). Item 13 (`SYSTEM_CALCULATED` bindings) and item 14 (calculation order) block the calculated-answer engine (`docs/EXTERNAL_BLOCKER_READINESS.md` §6). | Every checklist feature waits on it. Without it, real content cannot be loaded even when it arrives. |
| 2 | **IIG checklist content for each dosage form.** | Real checklists in REGX. Today only the `DEMO-` definition exists. | Needed straight after item 1. **Caution:** the checklists received on 16 Nov look like cGMP site-audit checklists (possibly for Part 1 / AuditIQ), not IIG checklists. The owner is confirming with the client. **Do not assume they are IIG content.** |
| 3 | **Calculator files and formulas** (units, rounding), **3 to 5 worked examples per calculator with the expected answers**, and **a named formula owner** for each calculator. | SOW 2.3 calculators (P9, BLOCKED; a blank item blocks that calculator, `docs/EXTERNAL_BLOCKER_READINESS.md` §2). | A whole SOW deliverable cannot start. Worked examples become the tests, so they are needed before any code. |
| 4 | **How injections should be handled, and the answer to Q8.** | IID checks for injectable routes and dosage forms (route and dosage-form mapping, and which limit applies). | It decides behaviour of an engine that already exists, so wrong guesses would have to be undone. |
| 5 | **Part 11 expectations in writing** (electronic signatures, audit trail). | The design of approval steps (approve, return, reject, supersede, reinstate) and of the audit record. Today REGX keeps an audit trail and requires typed reasons, but has **no electronic signature in the Part 11 sense** and makes no Part 11 claim. | Approval flows are being built now (PRs #167, #169 and the reinstate follow-up). Learning the signature rules late means reworking them. |
| 6 | **Answers to white-paper questions Q1 to Q8, and the 92-question bank.** | The question bank is checklist content (waits on item 1 too). Q1 to Q7 shape scope details; Q8 is covered by item 4. | Important, but each answer changes a part of the product rather than stopping all work. |
| 7 | **Written approval to use the FDA IID file as the source.** | Any claim that IID results rest on an approved source; go-live of the IID checks. | Development already uses the July 2026 file, so this blocks go-live more than coding. **Also ask which release:** FDA's online IID database now says "Data Through: September 21, 2026" and "Database Last Updated: October 19, 2026" (read on 2026-11-26), newer than the July 2026 file REGX uses (`docs/F3_IID_RECHECK_2026-11-27.md`). |
| 8 | **The 13 open Word add-in items.** | The Word add-in (P10, BLOCKED on 13 product and security decisions, `docs/EXTERNAL_BLOCKER_READINESS.md` §3). | Blocks one separate deliverable completely, but nothing else depends on it. |
| 9 | **What M1 means and how it will be accepted.** | Sign-off of milestone 1. | Blocks acceptance and payment, not engineering. Still worth asking now so the work is aimed at the right test. |

## What this list does not do

- It does not decide anything for the client, and it does not fill any gap with assumptions. `docs/EXTERNAL_BLOCKER_READINESS.md` ("What must NOT be inferred or invented") still applies to every item.
- It makes no regulatory or approval claim about REGX.
