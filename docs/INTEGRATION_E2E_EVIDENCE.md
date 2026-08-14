# E2E Evidence for the Company-Site Integration

Required by the pre-push hardening pass: exact proof of what the end-to-end
suites do, and of whether any failure is caused by this integration.

## Correction to the previous report

An earlier report on this branch stated "100 passed / 6 failed" and described
all six as pre-existing. **That was wrong on both counts**, and the method
that produced it was faulty. What actually happened:

1. Playwright's `webServer` has `reuseExistingServer: true`. The integrated
   stack publishes the frontend container on the same port 3000, so the run
   silently tested the **container**, not a dev server.
2. That container is built with `NEXT_PUBLIC_API_URL=http://localhost:8080`,
   while every historical spec mocks `http://localhost:8000`. The mocks
   therefore never matched, real API calls returned 403, and pages redirected
   to `/signin` mid-test.

Re-running with the container stopped (so Playwright starts its own dev server
on the origin the mocks expect) gives a completely different picture:
**91 passed / 1 failed**, and that one failure was a genuine regression from
this integration, described below. The "6" was an artifact of the harness, not
a property of the code.

Method used from here on: stop `regx-frontend` before running any suite that
relies on `:8000` mocks.

## The one genuine regression — found and fixed

| | |
| --- | --- |
| Test | `e2e/iig-checklist-executions.spec.ts` › "execution list page renders execution rows" |
| Signature | `expect(locator).toHaveCount(expected) failed` — `getByRole('link', { name: 'View' })` Expected 2, Received 3 |
| Cause | Playwright matches the accessible name by **substring** by default. The page now renders the company shell, whose sidebar contains the legacy tool "DMF Re**view** Checklist" — that contains "view", so the loose locator matched a third link. |
| Fix | `{ name: "View", exact: true }` in that assertion. No production code changed; the sidebar keeps the company's own label. |
| Status | **Fixed.** Suite green afterwards. |

This is a general hazard worth knowing: the shell adds ~60 links to every
operational page, so any `getByRole(..., { name })` written against a bare
page can now match sidebar text. Prefer `exact: true`, or scope to
`.dashboard-main-panel`.

## Pre-existing flakiness in `fda-iid.spec.ts` — not caused by this work

Under full-suite parallel load, a varying subset of `fda-iid.spec.ts` fails
with `expect(page).toHaveURL(expected) failed` after a form submit — the URL
is still the pre-submit path, i.e. the assertion outran a client-side
navigation.

Evidence that it is load-sensitive flakiness rather than a regression:

| Run | Scope | Result |
| --- | --- | --- |
| 1 | full suite | 2 failed / 110 passed / 20 skipped |
| 2 | full suite | 1 failed / 111 passed / 20 skipped — **different test** |
| 3 | full suite | 2 failed / 110 passed / 20 skipped — different again |
| 4 | `fda-iid` alone | 1 failed / 28 passed |
| 5 | `fda-iid` alone | **29 passed** |
| 6 | `fda-iid` alone, `--workers=1` | **29 passed** |

A deterministic regression does not change which test it hits between runs,
and does not disappear at `--workers=1`. None of these tests touch the shell:
they assert post-submit navigation inside a single module page.

Independently corroborated against the base commit: with the pre-integration
frontend source checked out (`git checkout d2b80d4 -- frontend/src
frontend/next.config.ts`), the same specs failed — 4 of them in one run —
before any of this integration's code existed.

Left unfixed deliberately: the hardening brief says not to fix unrelated
failures. Worth a separate ticket to add an explicit `waitForURL` or to await
the submit response in those tests.

## Current status

| Suite | Command | Result |
| --- | --- | --- |
| Shell (`regx-shell.spec.ts`) | `npx playwright test regx-shell` | **21 passed** |
| Integrated origin (`company-site-integration.spec.ts`) | `BASE_URL=http://localhost:8080 npx playwright test company-site-integration` | **20 passed** |
| Historical suite | `npx playwright test --grep-invert "regx-shell\|company-site-integration"` (container stopped) | **91 passed** |
| Full suite at `:3000` | `npx playwright test` | 110–111 passed, 20 skipped, 0–2 flaky `fda-iid` |

Honest summary:

- **NEW INTEGRATION E2E: PASS** (21 + 20 = 41 tests, deterministic).
- **NO NEW E2E REGRESSION: PASS** — the one regression this integration caused
  was identified, explained and fixed.
- **FULL HISTORICAL SUITE: GREEN WHEN RUN CORRECTLY (91/91)**, with known
  pre-existing flakiness in `fda-iid.spec.ts` under parallel load.

## Reproducing

```bash
docker compose stop frontend          # free :3000 so Playwright runs its own dev server
cd frontend
npx playwright test                   # historical + shell
docker compose up -d frontend
BASE_URL=http://localhost:8080 npx playwright test company-site-integration
```
