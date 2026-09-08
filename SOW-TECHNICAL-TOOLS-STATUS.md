# SOW Section 2 — Technical Tools (Regulatory), AI Based

Status checklist for **`RATools` only**. Nothing outside that app is in scope here.

- **Source:** `SOW - Praverse (Pratham)  iCretegy_April 22, 2026.pdf`, section 2 (pages 7–9), items 2.1–2.11
- **Code state:** branch `fix/backend-wiring-and-deploy-hardening`, commit `cdf1b5f`, PR #45 (open, not merged)
- **Tests:** `python manage.py test` → **50 passed** (re-run at time of writing)
- **Date:** 2026-09-08

Every "Built" claim below names a file and line so it can be checked directly.
Line numbers are as of `cdf1b5f`.

---

## Legend

| Mark | Meaning |
|---|---|
| ✅ | Built and verified working |
| 🟡 | Partially built — works, but narrower than the SOW asks for |
| ⬜ | Not started, unblocked, buildable inside `RATools` today |
| 🔒 | Not started, **blocked** — dependency named |
| 💤 | SOW itself marks it "will see later if this point is feasible" |

---

## 1. Scorecard by SOW item

| SOW | Item | Status | Where it stands |
|---|---|---|---|
| 2.1 | Module architecture & toolkit restructure | ⬜ | Checklists still render as separate scattered routes, not one module-wise toolkit |
| 2.2 | IIG checklist automation (FDA IIG database) | 🔒 | Target fields exist and are manual. Needs the FDA IIG dataset from iCretegy |
| 2.3 | HTML calculators (dissolution, impurity, stability) | 🔒 | No calculator code in `RATools`. Needs formulas/spec from iCretegy |
| 2.4 | Role hierarchy: Doer / Reviewer / VP + review gates | ✅ | Built and working end to end |
| 2.5 | FDA Orange Book integration | 🔒 | No model, no importer. Needs the Orange Book dataset from iCretegy |
| 2.6 | Chatbot across workflow | 🔒 | Blocked on the hardcoded OpenAI key |
| 2.7 | Word plug-in (contextual drafting) | 🔒 | Office add-in — a separate deliverable, plus blocked on the key |
| 2.8 | AI-driven gap analysis engine | 🟡 | Scoring works for ANDA + DMF. No section drill-down, no heatmap, no playbook |
| 2.9 | Stability & impurity AI assistant | 💤 | SOW marks feasibility TBD. Its audit-trail sub-bullet is 🟡 (see 2.9 below) |
| 2.10 | Intelligent document management | 💤 | SOW marks feasibility TBD |
| 2.11 | Timeline | — | SOW: decided when phase 2 starts |

---

## 2. What is built ✅

### 2.4 Role hierarchy — complete

| Component | Location |
|---|---|
| `RegulatoryRole` (doer / reviewer / vp) | `RATools/models.py:831` |
| `RegulatoryReviewGate` (pending_review → pending_vp → approved / rejected) | `RATools/models.py:852` |
| `RegulatoryAuditTrail` (immutable: `save()`/`delete()` raise) | `RATools/models.py:911` |
| `audit.log_event()` — the only sanctioned writer | `RATools/audit.py:13` |
| Review action endpoint (writes an audit entry on every transition) | `RATools/views.py:14583` |
| Audit trail listing page | `RATools/views.py:14436` |
| Admin registration; audit trail + gap report + review gate are **view-only** | `RATools/admin.py` |

**Deliberate design decisions**

- Kept separate from the legacy `AssignChecker` 7-level checker flow, so 483 workflow behaviour is not retroactively changed.
- Review gate admin is view-only because `ModelAdmin.save_model()` would change a gate's status **without** writing an audit entry — an unaudited path in a Part 11 system.

**How to verify**

```bash
python manage.py test RATools          # role, gate, audit-trail, gap-analysis tests
# In the UI: /ratools/gap-analysis/ → generate → approve as a reviewer
#            /ratools/audit-trail/  → the transition appears
# In admin:  /admin/RATools/regulatoryreviewgate/<id>/change/ → no Save button; POST returns 403
```

---

## 3. What is partially built 🟡

### 2.8 Gap analysis engine

| SOW requirement | Status | Detail |
|---|---|---|
| Gap score 0–100 | ✅ | `RATools/gap_analysis.py`, stored on `RegulatoryGapAnalysisReport` (`models.py:978`) |
| ANDA scoring | ✅ | `gap_analysis.py:30` |
| DMF scoring | ✅ | `gap_analysis.py:86` (CA answers only) |
| **Drill-down breakdown by section** | ⬜ | `gap_details` already stores `module` / `chapter` / `category` per gap — the data is there, the aggregation is not |
| **Other checklist families** | ⬜ | Validation, VP, General/White Paper are not scored |
| Predictive deficiency heatmap | 🔒💤 | Needs the deficiency DB (see §6) and SOW marks it feasibility-TBD |
| Resolution playbook | 🔒 | Needs the deficiency DB and an LLM |

**Coverage today: 2 of 6 checklist families.**

| Family | Answer shape | Generic scoring path works? |
|---|---|---|
| ANDA | `answer` CharField | ✅ already scored |
| DMF (CA) | `answer` CharField | ✅ already scored |
| Validation | `answer` CharField | ⬜ **yes — same shape, not wired up** |
| VP | `answer` CharField | ⬜ **yes — same shape, not wired up** |
| General / White Paper | `answer` CharField | ⬜ **yes — same shape, not wired up** |
| DMF (review) | 3 booleans (`drf`/`ra`/`ard`), `models.py:137` | ❌ needs bespoke handling |
| IIG | 25 typed fields, `models.py:202` | ❌ needs bespoke handling |

### 2.9 Part 11 audit trail for calculator inputs/outputs

The model and helper exist and are correct. Coverage is the gap: **3 production call sites**.

```
RATools/gap_analysis.py:71     gap analysis generated (ANDA)
RATools/gap_analysis.py:128    gap analysis generated (DMF)
RATools/views.py:14611         review gate approve / reject
```

Checklist submit, approve, reject and export currently write **no** audit entry.

**Verify:** `grep -rn "audit.log_event(" RATools/ --include=*.py | grep -v tests.py`

---

## 4. Not started, unblocked — buildable in `RATools` today ⬜

No external data, no LLM, no new dependencies. Ordered by value per effort.

| # | Item | SOW | Outcome | Size |
|---|---|---|---|---|
| 1 | Score Validation / VP / General checklists | 2.8 | Gap scoring across 5 of 6 families instead of 2. Reuses the existing generic path | S |
| 2 | Section-level drill-down on the score | 2.8 | "Module 3.2.P is 40% complete, 3.2.S is 90%" instead of one number. Pure aggregation over `gap_details` — no new model, no migration | S |
| 3 | Complete the audit trail | 2.9, 2.4 | Every submit / approve / reject / export logged. The difference between owning the model and passing an audit | M |
| 4 | Review gates on all checklist types | 2.4 | `RegulatoryReviewGate` uses a generic FK and already works on any model — it is instantiated in exactly one place (`gap_analysis.py:175`) | M |
| 5 | Checklist version control | 2.7, 2.10 | Re-submitting a section creates v2 rather than overwriting. Reuses the immutable + `version` pattern already on `RegulatoryGapAnalysisReport` | M |
| 6 | Module-wise toolkit restructure | 2.1 | Navigation and grouping only — no model changes | M–L |

**Open question on #4:** this would run alongside the legacy `AssignChecker` 7-level flow. Two review systems on one object needs a product decision before any code.

---

## 5. Blocked 🔒

| Item | SOW | Blocked on | Notes |
|---|---|---|---|
| IIG checklist automation | 2.2 | **FDA IIG dataset from iCretegy** | Highest-value item in the section. See §7 |
| Orange Book integration | 2.5 | **Orange Book dataset from iCretegy** | SOW 2.5: "iCretegy shall provide the FDA database excel" |
| HTML calculators | 2.3 | **Formulas / spec from iCretegy** | Self-contained once specified. Pair with audit-trail item #3 to satisfy 2.9's audit bullet |
| Chatbot | 2.6 | **Hardcoded OpenAI key** | The project's own baseline report states no AI work proceeds until it is rotated |
| Word plug-in | 2.7 | **Key**, plus scope | An Office add-in is a separate deliverable, not a change inside this repo |
| Predictive deficiency flagging | 2.7, 2.8 | **Key + deficiency-data boundary** (§6) | Also feasibility-TBD in the SOW |

---

## 6. Three decisions that gate everything else

**1. Rotate the OpenAI API key.**
Live in `AIDatabase/filters.py`, and present in git history. Items 2.6, 2.7 and the predictive half of 2.8 — roughly a third of the section — cannot start until this is done. Rotate at the provider first; deleting the line does not invalidate the key.

**2. Decide the deficiency-data boundary.**
Predictive flagging and the resolution playbook need the deficiency tables, which live in `AIDatabase.ANDA` and `AIDatabase.MajorCR` (6,306 + 1,152 rows) — **outside the "only RATools" boundary**. Options:
  - (a) read cross-app — it is only an import, but it crosses the line as stated;
  - (b) re-home the deficiency data into `RATools` under non-colliding names, which the project's own baseline report already recommends.
  Note `AIDatabase.ANDA` collides by name with three unrelated `RATools` ANDA models.

**3. `RATools` has migrations; `AdminMaster` and `AIDatabase` do not.**
This is why "only `RATools`" is a genuinely safe constraint — new models there are routine. Anything needing a schema change in the other two apps is materially riskier, which is an argument for keeping this work inside `RATools` regardless.

---

## 7. Why 2.2 (IIG automation) is the highest-value item

`IIGTableRowsAnswers` (`RATools/models.py:235`) already has **exactly** the fields the automation would populate. Every one is a free-text field typed by hand today:

```
rm_code              ingredients          func_of_excpt
all_strength_dose    all_strength_amount  all_strength_w
molar_ratio          max_amount           route
max_potency          max_dailyexp
```

SOW 2.2 asks for: auto-fetch ingredient limits, route-of-administration mapping, auto-calculated limits, and a citation back to the IIG database. The destination schema is built; only the reference data and the lookup are missing.

**Outcome if built:** enter ingredient + route, get FDA IIG limits filled in with a citation and max daily exposure calculated. Removes the most error-prone manual step in the toolkit, and is pure `RATools` — a new reference model, an importer, and a lookup.

**Blocked only on iCretegy supplying the IIG Excel.**

---

## 8. Suggested first slice

Items **1, 2 and 3** from §4. All are computation or additive calls over data already being stored — no external input, no LLM, no new dependencies, no cross-app reads. Together they turn 2.8 from "a number for two checklist types" into the scored, section-broken-down, fully audited engine the SOW describes.

Item 6 in §4 (IIG) is worth more, but cannot start until the dataset arrives.

---

## 9. Deliberately not estimated

No day counts. Effort here depends heavily on how much of the 14,655-line `RATools/views.py` each change has to touch, and on team familiarity. Sizes in §4 are relative (S / M / L) and are a starting point for scoping, not a commitment.

## 10. Known caveats on this document

- Reflects `RATools` at commit `cdf1b5f`; PR #45 is **not merged**, so `main` does not yet contain the 2.4 work marked ✅.
- Status is judged against SOW section 2 as written on 2026-04-22. The SOW itself says scope "may be finalized later (in phase 2) once we have detailed discussion after one month of development of Point #1 — 483 Database AI."
- "Built and verified" means verified locally, by driving the running app and by the test suite. Nothing here has run in production.
