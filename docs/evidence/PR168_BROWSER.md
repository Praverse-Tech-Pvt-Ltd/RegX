# PR #168 in the browser: old code against the branch

**Owner condition A (2026-11-27).** Try to submit, approve and activate a checklist version with no questions. Exact steps, then the screen on the old code (`regx-main`) and on the branch. Screenshots are **not in git**: they are in the review hand-off only, under the file names given here.

**Setup note.** There is no authoring screen yet (N-1), so the empty version is created through the API. Where a step is refused, the next state is set with one SQL update on the synthetic test database so that the next button can still be tried in the browser; each such update is listed in the steps as "Test setup (not a user action)". Titles are labelled "SAMPLE – not real checklist content" (owner condition E).

### Old code (`regx-main`, 4ff74d7)

Stack: `regx-v25` rebuilt from `regx-main` (4ff74d7), origin `http://localhost:8080`, run at 2026-11-27T04:46:55.239Z (UTC).

**Steps:**

1. Signed in as doer@demo.regx.invalid.
2. Test setup through the API (no authoring screen yet, N-1): definition "SAMPLE-EMPTY-803668" (HTTP 201), version 1 with effective date 2026-12-01 and no sections or questions (HTTP 201).
3. Opened /iig-checklists/versions/45b195de-3bef-4e8a-9c86-995b4fa87163?tenant=demo as the Doer.
4. Clicked "Submit for review".
5. Status after Submit: under_review.
6. Signed in as vp@demo.regx.invalid; opened the same version page.
7. Clicked "Approve".
8. Status after Approve: approved.
9. Clicked "Activate".
10. Status after Activate: active.
11. Test setup (not a user action): UPDATE iig_checklist_checklistversion SET status = 'retired' WHERE public_id = '45b195de-3bef-4e8a-9c86-995b4fa87163';

| Button | Shown | HTTP | Message on screen |
|---|---|---|---|
| Submit for review | yes | 200 | (none) |
| Approve | yes | 200 | (none) |
| Activate | yes | 200 | (none) |

**Final status:** `active`.

**Submit for review:** screenshot `review-handoff/evidence__shot__evA168_old_1_submit.png`. Screen text:

```text
Checklist version 1
Status
under review
Effective date
2026-12-01
Submitted by
not yet submitted
Approved by
not yet approved
Activated by
not yet activated
Sections

No sections defined yet.

Approve
Reject
Return reason (required to return)
Return for edits

This screen governs checklist structure and lifecycle only. It does not present or run checklist execution, responses, or calculation outcomes.
```

**Approve:** screenshot `review-handoff/evidence__shot__evA168_old_2_approve.png`. Screen text:

```text
Checklist version 1
Status
approved
Effective date
2026-12-01
Submitted by
not yet submitted
Approved by
not yet approved
Activated by
not yet activated
Sections

No sections defined yet.

Activate
Retire

This screen governs checklist structure and lifecycle only. It does not present or run checklist execution, responses, or calculation outcomes.
```

**Activate:** screenshot `review-handoff/evidence__shot__evA168_old_3_activate.png`. Screen text:

```text
Checklist version 1
Status
active
Effective date
2026-12-01
Submitted by
not yet submitted
Approved by
not yet approved
Activated by
not yet activated
Sections

No sections defined yet.

Supersede
Retire

This screen governs checklist structure and lifecycle only. It does not present or run checklist execution, responses, or calculation outcomes.
```

### Branch (#168, 27dd168)

Stack: `regx-v25` rebuilt from the #168 branch (27dd168), origin `http://localhost:8080`, run at 2026-11-27T04:57:12.753Z (UTC).

**Steps:**

1. Signed in as doer@demo.regx.invalid.
2. Test setup through the API (no authoring screen yet, N-1): definition "SAMPLE-EMPTY-421097" (HTTP 201), version 1 with effective date 2026-12-01 and no sections or questions (HTTP 201).
3. Opened /iig-checklists/versions/a1cececa-bea0-4642-891c-a8af5f7eb09c?tenant=demo as the Doer.
4. Clicked "Submit for review".
5. Status after Submit: draft.
6. Test setup (not a user action): UPDATE iig_checklist_checklistversion SET status = 'under_review' WHERE public_id = 'a1cececa-bea0-4642-891c-a8af5f7eb09c';
7. Signed in as vp@demo.regx.invalid; opened the same version page.
8. Clicked "Approve".
9. Status after Approve: under_review.
10. Test setup (not a user action): UPDATE iig_checklist_checklistversion SET status = 'approved' WHERE public_id = 'a1cececa-bea0-4642-891c-a8af5f7eb09c';
11. Clicked "Activate".
12. Status after Activate: approved.

| Button | Shown | HTTP | Message on screen |
|---|---|---|---|
| Submit for review | yes | 400 | This checklist version has no questions. Add at least one section with at least one question before submitting for review. |
| Approve | yes | 400 | This checklist version has no questions. Add at least one section with at least one question before approval. |
| Activate | yes | 400 | This checklist version has no questions. Add at least one section with at least one question before activation. |

**Final status:** `approved`.

**Submit for review:** screenshot `review-handoff/evidence__shot__evA168_branch_1_submit.png`. Screen text:

```text
Checklist version 1
Status
draft
Effective date
2026-12-01
Submitted by
not yet submitted
Approved by
not yet approved
Activated by
not yet activated
Sections

No sections defined yet.

Submit for review
Retire

This checklist version has no questions. Add at least one section with at least one question before submitting for review.

This screen governs checklist structure and lifecycle only. It does not present or run checklist execution, responses, or calculation outcomes.
```

**Approve:** screenshot `review-handoff/evidence__shot__evA168_branch_2_approve.png`. Screen text:

```text
Checklist version 1
Status
under review
Effective date
2026-12-01
Submitted by
not yet submitted
Approved by
not yet approved
Activated by
not yet activated
Sections

No sections defined yet.

Approve
Reject
Return reason (required to return)
Return for edits

This checklist version has no questions. Add at least one section with at least one question before approval.

This screen governs checklist structure and lifecycle only. It does not present or run checklist execution, responses, or calculation outcomes.
```

**Activate:** screenshot `review-handoff/evidence__shot__evA168_branch_3_activate.png`. Screen text:

```text
Checklist version 1
Status
approved
Effective date
2026-12-01
Submitted by
not yet submitted
Approved by
not yet approved
Activated by
not yet activated
Sections

No sections defined yet.

Activate
Retire

This checklist version has no questions. Add at least one section with at least one question before activation.

This screen governs checklist structure and lifecycle only. It does not present or run checklist execution, responses, or calculation outcomes.
```
