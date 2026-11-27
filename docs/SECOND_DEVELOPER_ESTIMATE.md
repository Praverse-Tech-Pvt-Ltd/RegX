# Would a second developer shorten the screen work? (2026-11-27)

**Short answer:** yes, but by about a quarter to a third, not by half, and hardly at all in the first two weeks. These are estimates from how this project works, not measurements.

**The work it is measured against:** the screen work estimated in `docs/OPEN_ISSUES_PLAN.md`.
- The 15 open browser issues from the 2026-11-25 regression: about 22–33 working days.
- The IIG checklist authoring screens (`docs/IIG_AUTHORING_UI_SCOPE.md`, in PR #170, not merged yet): about 15–20 working days.
- Together: about **37–53 working days** for one developer who knows the codebase.

## What can run in parallel, and what collides

| Developer 1 (knows the code) | Developer 2 (new) | Collision risk |
|---|---|---|
| Authoring API and screens (A1–A4, S1–S8) | Frontend-only quick fixes: QA-10, QA-25, QA-26, QA-27, QA-22 (+N-6), N-8 | Low. Except QA-27 / QA-16 against S4–S8: both touch the checklist execution pages, so do those in sequence |
| QA-04 (edit/delete endpoints: audited, draft-only, database triggers) | QA-20 (upload details), QA-16 | Low |
| Decision-gated items as decisions arrive (QA-17, QA-18) | QA-09 phone layout (after the decision) | QA-09 touches the shell and every table, so it collides with everything. Best done last or by one person |
| — | QA-12 (field names in errors) | **High:** it changes `frontend/src/lib/api.ts`, the one file every screen uses. One person, early, merged before the others build on it |

## Onboarding

About **5–10 working days** before a new developer delivers reviewed changes on their own. The reasons:
- 25 apps, 16 import-linter contracts, database-level immutability triggers, and the regulatory-claim guard;
- the local CI, which takes about 1–1½ hours per branch and has Windows Docker traps (`handoff.md`, `test-checklist.md`);
- the evidence rules: tests first, browser check, the review hand-off.

During that time developer 1 loses about 1–2 days to questions and pairing.

## Review overhead

- Every change from developer 2 needs a code review by developer 1: roughly 10–20 % of developer 1's time while both are active.
- The owner's merge approval is a **shared queue**. Merges are paused today (owner, 2026-11-27). While they are, two developers produce unmerged branches faster, and later branches pile up behind earlier ones. The PR rule forbids building on unmerged work.

## The real limits, which a second developer does not remove

1. **The five open screen decisions** (phone pages, number display, dashboard, admin screens, home-page links; defaults proposed in `docs/OPEN_DECISIONS_DEFAULTS.md`). About 10½–18 days of the work cannot start until they are made.
2. **The owner's merge pause.**
3. **The client's IIG content and the 20-item content gate.** The question editor and applicability screens are best built close to the real content.
4. **One test stack and one CI machine.** A second developer needs their own machine with Docker. Otherwise CI runs queue, because they must run one at a time on this machine.

## Estimate

- **With all five decisions made and merges flowing:** about **37–53 days for one developer becomes about 27–38 calendar days for two.** That saves roughly 10–15 days, mostly in weeks 3 onwards.
- **If the decisions and merges stay blocked:** the saving is close to zero. A second developer would mostly wait.
