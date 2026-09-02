# Stacked merge plan — Milestones 9 to 16

**Nothing in this document has been executed. It is the plan, not a record.**

Eight pull requests sit in one chain. Each is based on its predecessor, not on
`regx-main`, so merging them out of order pulls a parent's changes in with the
child and makes the review of that parent meaningless.

## The chain

```
regx-main
  ↓ #37  regx/feat/submission-dossiers                57c0a15   M9
  ↓ #38  regx/feat/dossier-blueprints                 a6c3e35   M10
  ↓ #39  regx/feat/dossier-upgrades                   1cd885a   M11
  ↓ #40  regx/feat/submission-operations-dashboard    12ea155   M12
  ↓ #41  regx/feat/submission-packages                9ebfbba   M13
  ↓ #42  regx/feat/external-integrations              e7bcc4c   M14
  ↓ #43  regx/feat/reliability-hardening              77b0aeb   M15
  ↓ #NN  regx/feat/final-validation-release           <head>    M16
```

Verified in Milestone 16: every branch tip equals the head recorded here, and
every parent is an ancestor of its child. The chain is strictly linear — no
merge commits, no divergence — which is also the proof that **no child depends
on a file outside its declared parent**: everything a child sees, it inherited.

## The sequence

| Step | PR | Base while stacked | Retarget to `regx-main` when | Merge |
|---|---|---|---|---|
| 1 | #37 | `regx-main` | already based there | merge first |
| 2 | #38 | `regx/feat/submission-dossiers` | #37 is on `regx-main` | then merge |
| 3 | #39 | `regx/feat/dossier-blueprints` | #38 is on `regx-main` | then merge |
| 4 | #40 | `regx/feat/dossier-upgrades` | #39 is on `regx-main` | then merge |
| 5 | #41 | `regx/feat/submission-operations-dashboard` | #40 is on `regx-main` | then merge |
| 6 | #42 | `regx/feat/submission-packages` | #41 is on `regx-main` | then merge |
| 7 | #43 | `regx/feat/external-integrations` | #42 is on `regx-main` | then merge |
| 8 | M16 | `regx/feat/reliability-hardening` | #43 is on `regx-main` | merge last |

For every step, the same four requirements:

* **CI** must be green on the child *after* retargeting, not only before. The
  diff changes when the base changes, and a check that passed against the parent
  branch has not been run against `regx-main`.
* **Review** must be against the retargeted diff for the same reason.
* **A normal two-parent merge commit.** Not a squash: squashing collapses the
  milestone's history into one commit and destroys the review trail that each PR
  body refers to.
* **No rebase of the child.** See below.

## Retargeting

After a parent merges, retarget its child to `regx-main` — **and only once the
parent's content is actually on `regx-main`.** Retargeting earlier makes the
child's diff include its parent's changes, which is exactly the confusion the
stack exists to avoid.

Retarget by changing the PR's base in the GitHub UI or with
`gh pr edit <n> --base regx-main`. That is a metadata change: it rewrites no
commits.

**Do not rebase. Do not squash. Do not force push.** The child already contains
its parent's commits; once the parent is on `regx-main` those commits are common
ancestors and the diff resolves itself. Rebasing rewrites every SHA in the
child, breaks the head SHAs recorded in each PR body and in `ROADMAP.md`, and
discards the ancestry this plan is verified against.

## What a merge of each step brings

| PR | Commits | Files | New migrations | Class C on rollback once data exists |
|---|---|---|---|---|
| #37 M9 | 4 | 40 | 4 | `submission_dossiers/0001` |
| #38 M10 | 2 | 41 | 3 | `dossier_blueprints/0001` |
| #39 M11 | 2 | 35 | 3 | `dossier_upgrades/0001` |
| #40 M12 | 2 | 28 | 0 | none — read model only |
| #41 M13 | 2 | 40 | 3 | `submission_packages/0001` |
| #42 M14 | 2 | 49 | 2 | `external_integrations/0001` |
| #43 M15 | 2 | 26 | 0 | none — code and settings only |
| M16 | — | — | 0 | none — validation, tests and docs |

Per-migration classification, including the one **required operator action**
before deploying #41, is in [`MIGRATION_INVENTORY.md`](MIGRATION_INVENTORY.md).

## Before step 5 (#41, Milestone 13)

`submission_packages/0003_package_revision_family` will refuse to build its
uniqueness constraint if any existing package family holds two packages with the
same `revision_number`. Run the check in `MIGRATION_INVENTORY.md` against the
target database first. This is the only step in the plan with a pre-deploy
query.

## After the last merge

Only then does `regx-main` hold the whole platform. Until then, `regx-main` is
at the Milestone 8 merge (`8c4d19d`) and every claim in the milestone documents
describes a branch, not the main line.

## What this plan does not do

It does not merge anything, retarget anything, or change any PR. It does not
decide whether the release is approved — that is governance, and the standing
approval state is unchanged. And it assumes CI can run; see
[`RELEASE_BLOCKERS.md`](RELEASE_BLOCKERS.md) for the organisation-level
condition that currently prevents that.
