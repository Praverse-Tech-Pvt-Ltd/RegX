# Team merge rules (2026-11-27)

**Why these rules exist:** on the organisation's current GitHub plan, branch protection and rulesets are not available for this private repository. GitHub answers: "Upgrade to GitHub Pro or make this repository public". So nothing technical stops a direct push or an unreviewed merge. **These rules replace that protection by agreement until the plan changes.**

## The rules

1. **No direct pushes to `regx-main`.** Every change reaches `regx-main` through a pull request.
2. **The AI tool works from its own fork, through pull requests.** It never pushes to the organisation repository's branches directly. Its PRs target `regx-main`.
3. **Only Maanav or Pratham merge.** Nobody else merges a pull request into `regx-main`, and the AI tool never merges.
4. **The merger records the approval.** Before or at the merge, the person merging adds a PR comment that says exactly: `Approved by <name>`. This comment is the review record, because GitHub cannot enforce a required review on this plan.

## When to revisit the GitHub Team plan

Revisit a paid plan (GitHub Team, which allows branch protection and rulesets on private repositories) **as soon as any of these happens:**
- **real client data goes into REGX** (until now it holds synthetic and public FDA data only);
- **a client pilot starts;**
- **an auditor asks for enforced review rules.**

At that point, switch on branch protection for `regx-main`: require a pull request and one approving review, and block force-pushes and deletion. The rules above then become settings rather than an agreement.
