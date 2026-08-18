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

**This is now fixed in configuration rather than procedure (F-1).** The local
suite runs on a dedicated port that the compose stack does not use, and never
reuses a server it did not start, so a running container cannot affect it. The
"remember to stop the container first" instruction below is obsolete and is kept
only to explain the earlier evidence. See §"Test modes" at the end of this
document.

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
cd frontend
npm run test:e2e              # local frontend  -> Playwright's own server on :3100
npm run test:e2e:integrated   # integrated origin -> the compose stack on :8080
```

Neither command depends on the other, and neither depends on whether the compose
stack is running. Stopping containers is no longer part of the procedure.

## Test modes

Two families, two configs, two commands. They cannot exercise each other's
environment.

| | **Local frontend E2E** | **Integrated-origin E2E** |
|---|---|---|
| Command | `npm run test:e2e` | `npm run test:e2e:integrated` |
| Config | `playwright.config.ts` | `playwright.integrated.config.ts` |
| Server | Next.js dev server **Playwright starts and owns** | the **compose stack**; Playwright starts nothing |
| Origin | `http://localhost:3100` — pinned, ignores env | `http://localhost:8080` (override: `INTEGRATED_BASE_URL`) |
| API target | `http://localhost:8000`, **mocked** via `page.route` | real backend through nginx, **not mocked** |
| Specs | everything except `company-site-integration.spec.ts` | only `company-site-integration.spec.ts` |
| Needs the stack? | **No** | **Yes** — `docker compose up -d` first |

**A running Docker frontend must not affect local E2E results, and no longer
can.** Three things enforce that, none of them a convention someone has to
remember:

1. The local suite runs on **port 3100**, which nothing in `compose.yaml`
   publishes. The container is on 3000.
2. `reuseExistingServer: false`, always — in CI and locally alike. Playwright
   owns 3100 or fails immediately with a port error. That loud failure is the
   guard.
3. The local config **pins `baseURL`** instead of reading an environment
   variable, so nothing can silently aim the suite at another environment.

`tests/unit/playwright-config-contract.test.ts` asserts all three, plus that the
two configs target different origins. It is a configuration test, so it cannot
flake.

**Why the override is named `INTEGRATED_BASE_URL` and not `BASE_URL`:** Vite
sets `process.env.BASE_URL` to `"/"` in its own process, so a config reading
`BASE_URL` can resolve to `"/"` instead of the intended origin. The
config-contract test caught exactly that during this work.

### Measured before and after

Same command, same commit, with the compose stack running:

| | Local suite result |
|---|---|
| Before F-1 | **40 failed / 72 passed** — silently attached to the container |
| After F-1 | **112 passed / 0 failed** — ran against its own server on `:3100` |

With the container stopped, after F-1: **112 passed / 0 failed**. The suite now
gives the same answer either way, which is the point.
