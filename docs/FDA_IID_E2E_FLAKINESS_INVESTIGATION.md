# FDA-IID E2E Flakiness — Investigation

**Outcome: reproduced, root-caused, and fixed with one configuration line. The
spec was not modified, and the flake is not specific to `fda-iid.spec.ts`.**

Investigated against `regx-main` `c79cf0717b53c454ab645750587a7609549ecb3c`.

---

## 1. The original concern

Recorded in `INTEGRATION_E2E_EVIDENCE.md` during the site integration:

> Under full-suite parallel load, a varying subset of `fda-iid.spec.ts` fails
> with `expect(page).toHaveURL(expected) failed` after a form submit — the URL
> is still the pre-submit path.

It was left unfixed deliberately, with a note suggesting "a separate ticket to
add an explicit `waitForURL` or to await the submit response". It did not
reproduce during F-1, so F-7 was opened at low priority to settle it.

**The concern was real.** It reproduces. The suggested fix was aimed at the
wrong thing.

---

## 2. Environment

| | |
|---|---|
| Machine | 20 logical cores; the Docker stack running throughout |
| Browser | chromium, headless |
| Local workers | `undefined` → Playwright default (10 here) |
| Local retries | 0 |
| CI workers | **1** |
| CI retries | **2** |
| `expect` timeout before this change | Playwright default, **5000 ms** |
| Command | `npx playwright test` (F-1 harness: own dev server on `:3100`, `reuseExistingServer: false`) |

Results were read from Playwright's **JSON reporter**, parsed structurally. No
`grep`/`tail` counting was used anywhere in this investigation.

---

## 3. Reproduction strategy and results

Escalating contention until it broke, then isolating the variable.

| # | Scope | Executions | Result |
|---|---|---|---|
| 1 | `fda-iid` alone, cold server | 29 | **29 passed** |
| 2 | `fda-iid --repeat-each=10` | 290 | **290 passed** |
| 3 | Full suite × 10, default workers | 1,120 | **1,120 passed, 0 flaky** |
| 4 | Full suite `--repeat-each=2 --workers=20` | 224 | **2 failed** |

**At the default worker count nothing failed in 1,410 executions.** It took
doubling the workers — 20 on one dev server — to surface it.

### The failure, exactly

```
Error: expect(page).toHaveURL(expected) failed

Expected pattern: /\/formulations\/product-e2e-2/
Received string:  "http://localhost:3100/formulations/new?tenant=alpha"
Timeout: 5000ms

Call log:
  - Expect "toHaveURL" with timeout 5000ms
    13 × unexpected value "http://localhost:3100/formulations/new?tenant=alpha"
```

The URL never left the pre-submit path across 13 polls in 5 s — matching the
historical description precisely. The surrounding test ran 11.6 s in total, so
the *test* had time; only the assertion's budget expired.

### It is not an `fda-iid` problem

Under the same contention, `regx-shell.spec.ts` fails the same way — five of
eight failures in one run, four of five in another. Every failure observed in
this entire investigation, in every spec, was an `expect(page).toHaveURL(...)`
timeout. Not one was a locator, mock, isolation or assertion-content failure.

`fda-iid.spec.ts` is simply where it was first noticed, being the largest spec
with the most post-submit navigations.

---

## 4. Root cause

**A latency ceiling, not a race.**

`router.push()` in the Next.js App Router does not change the URL until the
destination route's payload is ready. `npm run dev` compiles routes **on
demand**. With 20 workers driving one dev server, a cold route compile queues
behind every other worker's cold compile and can exceed 5 s — so
`expect(page).toHaveURL(...)` expires while the navigation is still legitimately
in flight.

The assertion outruns the compiler. The application is behaving correctly.

### Proof: the budget is the only variable

Same command, same contention, same machine; only the `expect` timeout differs.

| Arm | `expect` timeout | Runs | Executions | Failures |
|---|---|---|---|---|
| **A** | 5,000 ms (the default) | 4 | 896 | **16** |
| **B** | 30,000 ms | 4 | 896 | **0** |
| **C** | 15,000 ms | 3 | 672 | **0** |

Every one of Arm A's 16 failures was a `toHaveURL` timeout. Raising only the
budget removed all of them — which is only possible if the navigation does
complete, just later than 5 s.

Arm A **is** the mutation proof required before accepting a fix: it is the same
suite with the change reverted, and the failures return, four runs out of four.

---

## 5. What was changed

One line of configuration in `frontend/playwright.config.ts`:

```ts
expect: { timeout: 15_000 },
```

**No spec file was modified.** In particular:

- **No `waitForURL` was added.** The historical suggestion would have worked, but
  for a misleading reason: `page.waitForURL()` uses the *navigation* timeout
  (30 s default), not the *expect* timeout (5 s). Sprinkling it through the
  specs would have been a timeout increase disguised as a synchronisation fix,
  applied one call site at a time, and it would have left every other
  `toHaveURL` in the suite exposed.
- **No `waitForTimeout`, sleep or fixed delay.** Every assertion still polls for
  the real condition and returns the moment it holds; a passing run is no slower
  than before.
- **No reduction in workers**, and no `workers: 1`.
- **No test-isolation change** — none was needed, see §6.

15 s rather than 30 s is deliberate: it absorbs dev-mode compile latency while
keeping a genuinely wrong assertion failing promptly. This raises a ceiling; it
does not hide a race.

`playwright.integrated.config.ts` was **left alone**. That suite runs against a
compiled production build behind nginx, where no on-demand compilation happens,
so it does not have this failure mode. Changing it would have been speculative.

---

## 6. What was ruled out

| Candidate | Finding |
|---|---|
| Test isolation across workers | **Not the cause.** Each test gets a fresh browser context; all API calls are `page.route()`-mocked per test; no shared storage state, no server mutation, no reused identifiers. Failures are pure timeouts, not wrong data. |
| Route mock registered too late | **No.** Mocks are registered before `page.goto()` in every failing test, and a missed mock would produce a wrong-content failure, not a URL timeout. |
| Locator matching multiple elements | **No.** No locator error occurred in any run. |
| Backend or database state collision | **No.** These specs never reach a backend; everything is mocked. |
| A product defect in navigation | **No.** Arm B shows the navigation completes correctly under identical load. |
| The F-1 harness | **No.** `:3100`, `reuseExistingServer: false` and the pinned `baseURL` are intact and were used throughout. |

---

## 7. Local / CI parity

Material differences, and they matter here:

| | Local | CI |
|---|---|---|
| Workers | default (10 on this machine) | **1** |
| Retries | 0 | **2** |
| Server | Playwright's own `next dev` on `:3100` | same |

**CI is not exposed to this failure mode** — it runs serially, so no contention
builds on the dev server, and two retries would absorb a stray timeout anyway.
The exposure is local runs, and it only appeared at double the default worker
count.

This also means **local reproduction does not prove CI equivalence**, and no such
claim is made. What it does prove is that the ceiling exists and that raising it
is safe.

---

## 8. Verification after the change

| Check | Result |
|---|---|
| `fda-iid --repeat-each=50` | **1,450 passed / 0 failed / 0 flaky** |
| Full suite × 3, default workers | **112 passed** each |
| Full suite `--repeat-each=2 --workers=20` (the condition that broke it) | **224 passed** each |
| Frontend unit tests | **263 passed**, 14 files |
| F-1 config-contract test | **9 passed** — harness contract intact |
| `npm run type-check` | **PASS** |
| `npm run lint` | **PASS** — no ESLint warnings or errors |

---

## 9. Limitations

- **A ceiling is not a guarantee.** On a slower machine, or at a still higher
  worker count, 15 s could be exceeded. The failure mode is contention-dependent
  by nature and cannot be eliminated by a timeout, only given adequate margin.
- **Dev-mode compilation is the underlying cost.** Running the E2E suite against
  a production build would remove it at the source. That is a larger change to
  the harness and was not undertaken here.
- **CI behaviour is inferred, not measured.** CI runs serially with retries and
  has not exhibited this; that is reasoning from the configuration, not from a
  reproduction in CI.
- **A genuinely broken assertion now takes up to 15 s to fail** instead of 5 s.
  That is the cost of the margin, and why 30 s was rejected.
- The historical observations were recorded before F-1 corrected the harness.
  This investigation does not attempt to re-derive what exactly was happening
  then; **it does not claim the original issue never existed.** It did, and it
  still does under load.

---

## 10. Closure

**F-7: CLOSED — reproduced, root-caused, fixed at the configuration level.**

No production data was used at any point; every fixture in these specs is
synthetic. No trace, screenshot or video is committed. No spec, product code,
regulatory content or governance state was changed.
